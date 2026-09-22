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
    simulate_strategy,
    run_backtest_engine,
)
from .model_registry import dataset_fingerprint
from .prediction_intelligence import (
    CALIBRATION_VERSION,
    FEATURE_VERSION,
    build_backtest_rows,
    evaluate_probabilities,
    parse_timestamp,
)

RESEARCH_ENGINE_VERSION = "p14-research-v2"
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
FD_SOURCE_ALIASES = frozenset({"football-data", "football_data", "football-data.co.uk", "fd"})


def _requires_llm_poisson_comparison(hypothesis: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(hypothesis.get(key) or "")
        for key in ("statement", "selection_rule")
    ).casefold()
    return "poisson" in text and ("llm" in text or "deepseek" in text or "chatgpt" in text)


def filter_settlement_rows_by_source(
    settlement_rows: Iterable[Mapping[str, Any]],
    *,
    source: str = "football-data",
    fixture_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Keep only rows whose fixture source is explicitly the requested feed.

    Older settlement payloads did not persist a source. Those rows are
    resolved through the fixture repository when possible; unresolved rows
    are excluded so a confirmatory FD report cannot silently mix sources.
    """

    requested = str(source).strip().casefold()
    aliases = FD_SOURCE_ALIASES if requested in FD_SOURCE_ALIASES else frozenset({requested})
    filtered: list[dict[str, Any]] = []
    for row in settlement_rows:
        payload = dict(row)
        value = payload.get("data_source") or payload.get("source")
        if not value and callable(fixture_reader):
            fixture = fixture_reader(str(payload.get("fixture_id") or ""))
            value = (fixture or {}).get("source")
        normalized = str(value or "").strip().casefold()
        if normalized in aliases:
            payload["data_source"] = normalized
            filtered.append(payload)
    return filtered


def _market_odds_from_assessment(assessment: Mapping[str, Any] | None) -> dict[str, float]:
    odds: dict[str, float] = {}
    for row in (assessment or {}).get("markets") or []:
        if row.get("market") != "1x2" or row.get("selection") not in {"home", "draw", "away"}:
            continue
        try:
            price = float(row.get("price") or row.get("odds"))
        except (TypeError, ValueError):
            continue
        if price > 1:
            odds[str(row["selection"])] = price
    return odds


def _execution_rows(
    settlement_rows: Iterable[Mapping[str, Any]],
    model_key: str,
) -> list[dict[str, Any]]:
    """Prepare only persisted executions for the strategy simulator."""

    rows: list[dict[str, Any]] = []
    for row in settlement_rows:
        row_model = str(row.get("model_key") or (row.get("experiment") or {}).get("model_key") or "")
        if row_model != model_key or not (row.get("bet_id") or row.get("execution_id")):
            continue
        payload = dict(row)
        if not payload.get("market_odds"):
            odds = _market_odds_from_assessment(payload.get("market_assessment"))
            if odds:
                payload["market_odds"] = odds
        rows.append(payload)
    return rows


def _llm_vs_poisson_comparison(
    settlement_rows: Iterable[Mapping[str, Any]],
    *,
    minimum_samples: int = 30,
) -> dict[str, Any]:
    """Return paired frozen-probability and execution metrics for LLM models."""

    raw_rows = [dict(row) for row in settlement_rows]
    paired_rows = build_backtest_rows(raw_rows)
    llm_keys = sorted(
        {
            str(model)
            for row in paired_rows
            for model in (row.get("base_predictions") or {})
            if str(model) != "poisson"
        }
    )
    paired_sample = [
        row
        for row in paired_rows
        if (row.get("base_predictions") or {}).get("poisson")
    ]
    poisson = evaluate_probabilities(
        paired_sample,
        lambda row: (row.get("base_predictions") or {}).get("poisson"),
    )
    models: dict[str, Any] = {}
    for model_key in llm_keys:
        model_rows = [
            row
            for row in paired_sample
            if (row.get("base_predictions") or {}).get(model_key)
        ]
        metrics = evaluate_probabilities(
            model_rows,
            lambda row, key=model_key: (row.get("base_predictions") or {}).get(key),
        )
        strategy_rows = _execution_rows(raw_rows, model_key)
        strategy = simulate_strategy(
            strategy_rows,
            probabilities_by_fixture={
                str(row.get("fixture_id") or ""): (row.get("model_probabilities") or row.get("probabilities") or {})
                for row in strategy_rows
            },
        )
        models[model_key] = {
            **metrics,
            "strategy": strategy,
            "paired_samples": len(model_rows),
            "brier_improvement_vs_poisson": (
                round(float(poisson["brier"]) - float(metrics["brier"]), 6)
                if poisson.get("brier") is not None and metrics.get("brier") is not None
                else None
            ),
            "log_loss_improvement_vs_poisson": (
                round(float(poisson["log_loss"]) - float(metrics["log_loss"]), 6)
                if poisson.get("log_loss") is not None and metrics.get("log_loss") is not None
                else None
            ),
        }
    llm_sample_size = max(
        (int(item.get("paired_samples") or 0) for item in models.values()),
        default=0,
    )
    sample_size = min(int(poisson.get("samples") or 0), llm_sample_size)
    return {
        "status": "ok" if sample_size >= minimum_samples and models else "insufficient_sample",
        "sample_size": sample_size,
        "required_samples": minimum_samples,
        "poisson": poisson,
        "models": models,
    }


def _stable(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def sample_size_status(sample_size: int, minimum_samples: int = 30) -> str:
    """P6/MODEL_EVALUATION_POLICY confidence gates."""

    if sample_size < minimum_samples:
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


def _statistical_summary(
    result: Mapping[str, Any],
    *,
    minimum_samples: int = 30,
) -> dict[str, Any]:
    ensemble = result.get("ensemble_brier") or {}
    comparison = result.get("llm_vs_poisson") or {}
    sample_size = int(
        comparison.get("sample_size")
        or result.get("sample_size")
        or ensemble.get("sample_size")
        or 0
    )
    return {
        "sample_size": sample_size,
        "sample_status": sample_size_status(sample_size, minimum_samples),
        "required_samples": minimum_samples,
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
    comparison = result.get("llm_vs_poisson") or {}
    comparison_requested = _requires_llm_poisson_comparison(hypothesis)
    direct_comparison = manifest.get("mode") == "model_comparison" and comparison_requested
    if statistics["sample_status"] != "adequate_sample":
        limitations.append(f"样本量 {statistics['sample_size']}（{statistics['sample_status']}），结论置信度受限")
    market = result.get("market_baseline_brier") or {}
    if market.get("status") == "unavailable":
        unanswerable.append("市场基准对比不可用（缺少完整历史赔率）")
    if result.get("strategy", {}).get("status") == "unavailable":
        unanswerable.append("策略模拟不可用（执行链不完整）")
    if result.get("window_count", 0) == 0 and not direct_comparison:
        limitations.append("没有可评估的时间窗口")
    if comparison_requested and comparison.get("status") != "ok":
        limitations.append(
            f"LLM 与 Poisson 配对样本 {comparison.get('sample_size', 0)}，"
            f"未达到 {comparison.get('required_samples', statistics.get('required_samples', 30))} 场门槛"
        )
    conclusion = None
    if direct_comparison and audit["passed"] and comparison.get("status") == "ok":
        conclusion_scope = "探索性低置信度复盘，不构成确认结论" if hypothesis.get("kind") == "exploratory" else "预注册确认性复盘"
        conclusion = (
            f"在数据集 {manifest.get('dataset_fingerprint')} 上完成 LLM 与 Poisson 配对比较；"
            f"结果仅用于{conclusion_scope}，不自动晋升模型"
        )
    elif result.get("status") == "ok" and audit["passed"] and result.get("window_count"):
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
            "weights_learned_per_window_from_train_only": not direct_comparison,
            "required_samples": statistics.get("required_samples"),
        },
        "metrics": {
            "ensemble_brier": result.get("ensemble_brier"),
            "model_briers": result.get("model_briers"),
            "market_baseline_brier": result.get("market_baseline_brier"),
            "improvement": result.get("improvement"),
            "llm_vs_poisson": comparison,
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
    minimum_samples: int = 30,
    job_id: str | None = None,
    created_by: str = "admin",
    repository: Any | None = None,
) -> dict[str, Any]:
    """Execute the full research pipeline and archive an immutable run."""

    stages: dict[str, Any] = {stage: None for stage in PIPELINE_STAGES}
    settlement_rows = [dict(row) for row in settlement_rows if isinstance(row, Mapping)]
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

    required_floor = 30 if hypothesis["kind"] == "confirmatory" else 20
    try:
        minimum_samples = int(minimum_samples)
    except (TypeError, ValueError):
        minimum_samples = 0
    if minimum_samples < required_floor:
        return {
            "run_id": None,
            "status": "failed",
            "error": f"minimum_samples must be at least {required_floor} for {hypothesis['kind']} research",
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
    result["llm_vs_poisson"] = _llm_vs_poisson_comparison(
        settlement_rows,
        minimum_samples=minimum_samples,
    )
    manifest = result.get("manifest") or {}
    direct_comparison = mode == "model_comparison" and _requires_llm_poisson_comparison(hypothesis)
    experiment_ok = (
        result["llm_vs_poisson"].get("status") == "ok"
        if direct_comparison
        else result.get("status") == "ok"
    )
    stages["experiment"] = {
        "status": "ok" if experiment_ok else "failed",
        "window_count": result.get("window_count"),
        "method": "paired_llm_vs_poisson" if direct_comparison else "rolling_backtest",
    }
    stages["backtest"] = {
        "status": "not_required" if direct_comparison else "ok" if result.get("status") == "ok" else "failed",
        "mode": mode,
    }
    statistics = _statistical_summary(result, minimum_samples=minimum_samples)
    minimum_sample_passed = int(statistics.get("sample_size") or 0) >= minimum_samples
    stages["statistical_check"] = {
        "status": "ok" if minimum_sample_passed else "insufficient_sample",
        **statistics,
    }
    audit = leakage_audit(rows)
    stages["leakage_audit"] = {"status": audit["status"], "violation_count": audit["violation_count"]}

    manifest = {
        **manifest,
        "engine_version": BACKTEST_ENGINE_VERSION,
        "feature_version": manifest.get("feature_version") or FEATURE_VERSION,
        "calibration_version": manifest.get("calibration_version") or CALIBRATION_VERSION,
        "strategy_version": manifest.get("strategy_version") or STRATEGY_VERSION,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "minimum_samples": minimum_samples,
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

    experiment_failed = not experiment_ok
    if not audit["passed"]:
        status = "failed" if audit["violation_count"] else "partial"
    elif experiment_failed or (not direct_comparison and not result.get("window_count")) or not minimum_sample_passed:
        status = "partial"
    elif (
        hypothesis["kind"] == "confirmatory"
        and _requires_llm_poisson_comparison(hypothesis)
        and result["llm_vs_poisson"].get("status") != "ok"
    ):
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
            "required_samples": minimum_samples,
            "ensemble_brier": result.get("ensemble_brier"),
            "improvement": result.get("improvement"),
            "llm_vs_poisson": result.get("llm_vs_poisson"),
        },
        "leakage_audit": {"status": audit["status"], "violation_count": audit["violation_count"], "violations": audit["violations"]},
        "created_by": created_by,
        "job_id": job_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "engine_version": RESEARCH_ENGINE_VERSION,
    }
    if status != "completed" or not audit.get("passed"):
        stages["archive"] = {
            "status": "skipped",
            "reason": "research eligibility gates did not pass",
        }
        return run

    # Content-addressed identity: eligible retries and duplicates converge to
    # the same stored run instead of creating a second report.
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
