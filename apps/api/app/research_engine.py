"""P14 Automated Research: auditable hypothesis → report pipeline.

A ResearchRun walks `Hypothesis → Dataset Freeze → Experiment → Backtest →
Statistical Check → Leakage Audit → Report → Archive`. Every stage result
is recorded; any failure marks the run failed/partial and no success
conclusion is generated. Runs are content-addressed (same hypothesis +
dataset + versions + seed → same run id), so scheduler retries can never
duplicate predictions or reports. The engine reuses the P12 backtest
contract and never bypasses P0-P13 provenance rules.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping

from .backtest_engine import (
    BACKTEST_ENGINE_VERSION,
    STRATEGY_VERSION,
    run_backtest_engine,
)
from .model_registry import dataset_fingerprint
from .prediction_intelligence import (
    CALIBRATION_VERSION,
    FEATURE_VERSION,
    build_backtest_rows,
    parse_timestamp,
)

RESEARCH_ENGINE_VERSION = "p14-research-v1"
RESEARCH_RUN_STATUSES: tuple[str, ...] = ("running", "completed", "failed", "partial")
HYPOTHESIS_KINDS: tuple[str, ...] = ("exploratory", "confirmatory")
PIPELINE_STAGES: tuple[str, ...] = (
    "hypothesis",
    "dataset_freeze",
    "experiment",
    "backtest",
    "statistical_check",
    "leakage_audit",
    "report",
    "archive",
)


def _stable(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def sample_size_status(sample_size: int) -> str:
    """P6/MODEL_EVALUATION_POLICY confidence gates."""

    if sample_size < 30:
        return "insufficient_sample"
    if sample_size < 100:
        return "low_confidence"
    return "adequate_sample"


def validate_hypothesis(
    *,
    statement: str,
    kind: str,
    selection_rule: str | None = None,
) -> dict[str, Any]:
    """Normalize and validate a hypothesis declaration."""

    if not statement or len(str(statement).strip()) < 8:
        raise ValueError("hypothesis statement is required")
    if kind not in HYPOTHESIS_KINDS:
        raise ValueError(f"hypothesis kind must be one of {HYPOTHESIS_KINDS}")
    if kind == "confirmatory" and not (selection_rule and str(selection_rule).strip()):
        raise ValueError("confirmatory research must pre-register a selection rule")
    return {
        "statement": str(statement).strip(),
        "kind": kind,
        "selection_rule": str(selection_rule).strip() if selection_rule else None,
        "hypothesis_id": f"hyp:{hashlib.sha256(_stable({'statement': statement, 'kind': kind, 'selection_rule': selection_rule}).encode()).hexdigest()[:24]}",
    }


def leakage_audit(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Mandatory point-in-time audit over evaluation rows.

    A row leaks when its prediction timestamp is not strictly before its
    settlement time (i.e., the label could have influenced the prediction).
    """

    violations: list[dict[str, str]] = []
    checked = 0
    for row in rows:
        prediction_at = parse_timestamp(row.get("prediction_created_at") or row.get("created_at"))
        settled_at = parse_timestamp(row.get("settled_at") or row.get("evaluation_timestamp"))
        if prediction_at is None or settled_at is None:
            continue
        checked += 1
        if prediction_at >= settled_at:
            violations.append(
                {
                    "prediction_id": str(row.get("prediction_id") or row.get("fixture_id") or ""),
                    "prediction_created_at": prediction_at.isoformat(),
                    "settled_at": settled_at.isoformat(),
                }
            )
    return {
        "checked": checked,
        "violations": violations[:50],
        "violation_count": len(violations),
        "passed": checked > 0 and not violations,
        "status": "passed" if (checked and not violations) else "failed" if violations else "not_applicable",
    }


def _statistical_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    ensemble = result.get("ensemble_brier") or {}
    sample_size = int(result.get("sample_size") or ensemble.get("sample_size") or 0)
    return {
        "sample_size": sample_size,
        "sample_status": sample_size_status(sample_size),
        "brier_point": round(
            (ensemble.get("low") + ensemble.get("high")) / 2, 6
        )
        if ensemble.get("low") is not None and ensemble.get("high") is not None
        else None,
        "brier_confidence_interval": {"low": ensemble.get("low"), "high": ensemble.get("high")},
        "experiment_count": 1,
        "selection_rule_applied": "pre_declared_parameters",
    }


def build_research_report(
    *,
    hypothesis: Mapping[str, Any],
    manifest: Mapping[str, Any],
    result: Mapping[str, Any],
    audit: Mapping[str, Any],
    statistics: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the immutable report sections from stage outputs only."""

    limitations: list[str] = []
    unanswerable: list[str] = []
    if statistics["sample_status"] != "adequate_sample":
        limitations.append(f"样本量 {statistics['sample_size']}（{statistics['sample_status']}），结论置信度受限")
    market = result.get("market_baseline_brier") or {}
    if market.get("status") == "unavailable":
        unanswerable.append("市场基准对比不可用（缺少完整历史赔率）")
    if result.get("strategy", {}).get("status") == "unavailable":
        unanswerable.append("策略模拟不可用（执行链不完整）")
    if result.get("window_count", 0) == 0:
        limitations.append("没有可评估的时间窗口")
    conclusion = None
    if result.get("status") == "ok" and audit["passed"] and result.get("window_count"):
        improvement = ((result.get("improvement") or {}).get("naive_baseline") or {}).get("brier_improvement")
        conclusion = (
            f"在数据集 {manifest.get('dataset_fingerprint')} 上，ensemble 相对 naive baseline 的 Brier 改进为 {improvement}（{hypothesis['kind']}）"
            if improvement is not None
            else f"在数据集 {manifest.get('dataset_fingerprint')} 上完成回测（{hypothesis['kind']}）"
        )
    return {
        "dataset": {
            "fingerprint": manifest.get("dataset_fingerprint"),
            "as_of_range": manifest.get("as_of_range"),
            "row_count": manifest.get("row_count"),
        },
        "versions": {
            "engine": manifest.get("engine_version"),
            "feature": manifest.get("feature_version"),
            "calibration": manifest.get("calibration_version"),
            "strategy": manifest.get("strategy_version"),
            "research": RESEARCH_ENGINE_VERSION,
        },
        "method": {
            "mode": manifest.get("mode"),
            "windows": result.get("window_count"),
            "weights_learned_per_window_from_train_only": True,
        },
        "metrics": {
            "ensemble_brier": result.get("ensemble_brier"),
            "model_briers": result.get("model_briers"),
            "market_baseline_brier": result.get("market_baseline_brier"),
            "improvement": result.get("improvement"),
        },
        "uncertainty": statistics,
        "limitations": limitations,
        "leakage_audit": {"status": audit["status"], "violation_count": audit["violation_count"]},
        "conclusion": conclusion,
        "unanswerable": unanswerable,
    }


def run_research(
    settlement_rows: Iterable[Mapping[str, Any]],
    *,
    hypothesis: Mapping[str, Any],
    mode: str = "rolling",
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
    seed: int = 20260913,
    competition_scope: str = "all",
    job_id: str | None = None,
    created_by: str = "admin",
    repository: Any | None = None,
) -> dict[str, Any]:
    """Execute the full research pipeline and archive an immutable run."""

    stages: dict[str, Any] = {stage: None for stage in PIPELINE_STAGES}
    try:
        hypothesis = validate_hypothesis(
            statement=hypothesis.get("statement") or "",
            kind=hypothesis.get("kind") or "exploratory",
            selection_rule=hypothesis.get("selection_rule"),
        )
        stages["hypothesis"] = {"status": "ok", "hypothesis_id": hypothesis["hypothesis_id"]}
    except ValueError as error:
        return {
            "run_id": None,
            "status": "failed",
            "error": str(error),
            "stages": stages,
            "report": None,
        }

    rows = build_backtest_rows(settlement_rows)
    if not rows:
        return {
            "run_id": None,
            "status": "failed",
            "error": "no settled model rows available for the dataset",
            "stages": stages,
            "report": None,
        }
    fingerprint = dataset_fingerprint(rows)
    stages["dataset_freeze"] = {"status": "ok", "dataset_fingerprint": fingerprint, "row_count": len(rows)}

    times = sorted(str(parse_timestamp(row.get("prediction_created_at")) or "") for row in rows)
    try:
        result = run_backtest_engine(
            settlement_rows,
            mode=mode,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
            seed=seed,
            competition_scope=competition_scope,
        )
    except ValueError as error:
        return {
            "run_id": None,
            "status": "failed",
            "error": str(error),
            "stages": stages,
            "report": None,
        }
    result.pop("_test_probabilities", None)
    manifest = result.get("manifest") or {}
    stages["experiment"] = {"status": "ok" if result.get("status") == "ok" else "failed", "window_count": result.get("window_count")}
    stages["backtest"] = {"status": "ok" if result.get("status") == "ok" else "failed", "mode": mode}
    statistics = _statistical_summary(result)
    stages["statistical_check"] = {"status": "ok", **statistics}
    audit = leakage_audit(rows)
    stages["leakage_audit"] = {"status": audit["status"], "violation_count": audit["violation_count"]}

    manifest = {
        **manifest,
        "engine_version": BACKTEST_ENGINE_VERSION,
        "feature_version": manifest.get("feature_version") or FEATURE_VERSION,
        "calibration_version": manifest.get("calibration_version") or CALIBRATION_VERSION,
        "strategy_version": manifest.get("strategy_version") or STRATEGY_VERSION,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "dataset_fingerprint": fingerprint,
        "as_of_range": {"start": times[0] if times else None, "end": times[-1] if times else None},
    }
    report = build_research_report(
        hypothesis=hypothesis,
        manifest=manifest,
        result=result,
        audit=audit,
        statistics=statistics,
    )
    stages["report"] = {"status": "ok"}

    experiment_failed = result.get("status") != "ok"
    if audit["violation_count"]:
        status = "failed"
    elif experiment_failed or not result.get("window_count"):
        status = "partial"
    else:
        status = "completed"
    run = {
        "run_id": None,  # assigned below from content
        "status": status,
        "hypothesis": hypothesis,
        "experiment_count": 1,
        "selection_rule": hypothesis.get("selection_rule"),
        "exploratory": hypothesis["kind"] == "exploratory",
        "manifest": manifest,
        "stages": stages,
        "report": report,
        "result_summary": {
            "window_count": result.get("window_count"),
            "sample_size": statistics["sample_size"],
            "sample_status": statistics["sample_status"],
            "ensemble_brier": result.get("ensemble_brier"),
            "improvement": result.get("improvement"),
        },
        "leakage_audit": {"status": audit["status"], "violation_count": audit["violation_count"], "violations": audit["violations"]},
        "created_by": created_by,
        "job_id": job_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "engine_version": RESEARCH_ENGINE_VERSION,
    }
    # Content-addressed identity: retries and duplicates converge to the
    # same stored run instead of creating a second report.
    content = {key: value for key, value in run.items() if key not in {"run_id", "created_at"}}
    run_id = f"research:{hashlib.sha256(_stable(content).encode()).hexdigest()[:32]}"
    run["run_id"] = run_id
    stages["archive"] = {"status": "ok"}
    if repository is not None and callable(getattr(repository, "save_research_run", None)):
        repository.save_research_run(run)
    return run


class ResearchScheduler:
    """Job runner with per-key locks and idempotent submission."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self._locks: dict[str, asyncio.Lock] = {}
        self._completed_results: dict[str, dict[str, Any]] = {}

    def _existing_run(self, run_id: str) -> dict[str, Any] | None:
        reader = getattr(self.repository, "research_runs", None)
        if not callable(reader):
            return None
        return next((row for row in reader(limit=500) if row.get("run_id") == run_id), None)

    async def submit(
        self,
        *,
        job_id: str,
        settlement_provider: Callable[[], Iterable[Mapping[str, Any]]],
        hypothesis: Mapping[str, Any],
        **params: Any,
    ) -> dict[str, Any]:
        """Run (or reuse) one research run under the job's lock.

        The pipeline is content-addressed, so a retry after a crash returns
        the stored run instead of duplicating predictions or reports.
        """

        lock = self._locks.setdefault(job_id, asyncio.Lock())
        async with lock:
            existing_key = f"{job_id}:{_stable(hypothesis)}:{_stable(params)}"
            cached = self._completed_results.get(existing_key)
            if cached:
                return {"reused": True, "run": cached}
            run = run_research(
                settlement_provider(),
                hypothesis=hypothesis,
                job_id=job_id,
                repository=self.repository,
                **params,
            )
            if run.get("run_id"):
                stored = self._existing_run(run["run_id"])
                result = {"reused": stored is not None, "run": stored or run}
                self._completed_results[existing_key] = result["run"]
            else:
                result = {"reused": False, "run": run}
            return result
