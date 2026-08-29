"""Deterministic P6 historical model evaluation and leakage auditing."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping

from .historical_validation import RollingBacktestService, parse_timestamp
from .league_data_pipeline import SUPPORTED_LEAGUES, normalize_league_code
from .prediction_intelligence import (
    CALIBRATION_VERSION,
    ENSEMBLE_VERSION,
    FEATURE_VERSION,
    apply_temperature,
    build_performance_profiles,
    evaluate_probabilities,
    fit_temperature,
    normalize_probabilities,
    weighted_ensemble,
)


P6_VERSION = "p6-historical-evaluation-v1"
MODEL_KEYS = ("baseline", "poisson", "gpt", "deepseek", "ensemble", "calibrated_ensemble")
_P3_MODEL_KEYS = ("deepseek", "chatgpt", "poisson")
_CAPTURE_KEYS = frozenset({"captured_at", "source_captured_at", "synced_at", "updated_at", "result_captured_at"})


def chronological_split(
    rows: Iterable[Mapping[str, Any]],
    *,
    train_ratio: float = 0.6,
    validation_ratio: float = 0.2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows by kickoff/prediction time with deterministic tie ordering."""

    if not 0 < train_ratio < 1 or not 0 <= validation_ratio < 1 or train_ratio + validation_ratio >= 1:
        raise ValueError("split ratios must leave a test slice")

    def order_key(row: Mapping[str, Any]) -> tuple[datetime, str, str]:
        timestamp = parse_timestamp(row.get("kickoff_at") or row.get("kickoff") or row.get("prediction_timestamp") or row.get("prediction_created_at") or row.get("settled_at"))
        return (timestamp or datetime.max.replace(tzinfo=UTC), str(row.get("fixture_id") or ""), str(row.get("prediction_id") or ""))

    ordered = sorted((dict(row) for row in rows), key=order_key)
    count = len(ordered)
    if not ordered:
        return [], [], []
    train_end = max(1, min(count - 1, int(count * train_ratio)))
    validation_end = max(train_end, min(count, int(count * (train_ratio + validation_ratio))))
    if validation_end == train_end and count - train_end > 1:
        validation_end += 1
    return ordered[:train_end], ordered[train_end:validation_end], ordered[validation_end:]


def frozen_dataset_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
    stable = [
        {
            "fixture_id": row.get("fixture_id"),
            "prediction_id": row.get("prediction_id"),
            "prediction_timestamp": row.get("prediction_timestamp") or row.get("prediction_created_at"),
            "actual_outcome": row.get("actual_outcome"),
        }
        for row in rows
    ]
    encoded = json.dumps(sorted(stable, key=lambda value: (str(value["fixture_id"]), str(value["prediction_id"]))), sort_keys=True, separators=(",", ":"), default=str)
    return f"{P6_VERSION}:{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


def sample_confidence(sample_count: int) -> tuple[str, str]:
    if sample_count < 30:
        return "insufficient_sample", "insufficient_sample"
    if sample_count < 100:
        return "low_confidence", "low_confidence"
    return "ok", "adequate"


def _iter_captured(value: Any, path: str = "") -> Iterable[tuple[str, datetime]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if key in _CAPTURE_KEYS:
                timestamp = parse_timestamp(item)
                if timestamp:
                    yield item_path, timestamp
            yield from _iter_captured(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_captured(item, f"{path}[{index}]")


def audit_prediction_leakage(
    row: Mapping[str, Any],
    *,
    auxiliary: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return every capture timestamp after the prediction cutoff."""

    cutoff = parse_timestamp(row.get("prediction_timestamp") or row.get("prediction_created_at"))
    violations: list[dict[str, Any]] = []
    if cutoff is None:
        return [{"prediction_id": row.get("prediction_id"), "field": "prediction_timestamp", "reason": "missing_prediction_timestamp"}]
    sources: dict[str, Any] = {}
    for key in ("result", "odds", "odds_snapshot", "feature_snapshot", "lineup", "injury", "recent_form", "team_statistics", "evidence", "prediction_bundle"):
        if row.get(key) is not None:
            sources[key] = row[key]
    for index, snapshot in enumerate(auxiliary):
        if isinstance(snapshot, Mapping):
            sources[f"auxiliary[{index}]"] = snapshot
        payload = snapshot.get("payload") if isinstance(snapshot, Mapping) else None
        if isinstance(payload, Mapping):
            # Fixture identity contains the future kickoff by definition; it is
            # excluded from the audit while evidence/context/odds are checked.
            for key in ("evidence", "context", "odds", "standings"):
                if payload.get(key) is not None:
                    sources[f"historical_snapshot.{key}"] = payload[key]
    for field, timestamp in _iter_captured(sources):
        if timestamp > cutoff:
            violations.append(
                {
                    "prediction_id": row.get("prediction_id"),
                    "field": field,
                    "captured_at": timestamp.isoformat(),
                    "prediction_timestamp": cutoff.isoformat(),
                    "reason": "captured_after_prediction",
                }
            )
    kickoff = parse_timestamp(row.get("kickoff_at") or row.get("kickoff"))
    if kickoff and cutoff >= kickoff:
        violations.append(
            {
                "prediction_id": row.get("prediction_id"),
                "field": "prediction_timestamp",
                "captured_at": cutoff.isoformat(),
                "kickoff_at": kickoff.isoformat(),
                "reason": "prediction_not_before_kickoff",
            }
        )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for violation in violations:
        key = (violation.get("field"), violation.get("captured_at"), violation.get("reason"))
        if key not in seen:
            seen.add(key)
            unique.append(violation)
    return unique


def leakage_audit(
    rows: Iterable[Mapping[str, Any]],
    *,
    snapshot_reader: Callable[[str], Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = [dict(row) for row in rows]
    details: list[dict[str, Any]] = []
    checked = 0
    for row in rows:
        fixture_id = str(row.get("fixture_id") or "")
        auxiliary = snapshot_reader(fixture_id) if snapshot_reader and fixture_id else ()
        checked += 1
        details.extend(audit_prediction_leakage(row, auxiliary=auxiliary or ()))
    status = "ok" if not details else "failed"
    return {
        "status": status,
        "total_predictions": len(rows),
        "checked_predictions": checked,
        "violations": len(details),
        "violation_rate": round(len(details) / checked, 6) if checked else 0.0,
        "passed": not details,
        "violation_details": details,
    }


def _model_key(row: Mapping[str, Any]) -> str:
    key = str(row.get("model_key") or (row.get("ai") or {}).get("provider") or "").casefold()
    return "gpt" if key in {"chatgpt", "gpt"} else key


def _fixture_rows(
    settlements: Iterable[Mapping[str, Any]],
    *,
    fixture_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
    prediction_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, dict[str, Any]] = {}
    source_rows: list[dict[str, Any]] = []
    for source in settlements:
        row = dict(source)
        if prediction_reader and row.get("prediction_id"):
            prediction = prediction_reader(str(row["prediction_id"]))
            if prediction:
                row = {**dict(prediction), **row}
        fixture_id = str(row.get("fixture_id") or "")
        if not fixture_id:
            continue
        fixture = fixture_reader(fixture_id) if fixture_reader else None
        code = normalize_league_code(row.get("canonical_league") or row.get("league") or row.get("league_key") or (fixture or {}).get("canonical_league") or (fixture or {}).get("league_key"))
        if code is None:
            continue
        item = grouped.setdefault(
            fixture_id,
            {
                "fixture_id": fixture_id,
                "canonical_league": code,
                "league_key": str((fixture or {}).get("league_key") or row.get("league_key") or code.casefold()),
                "season": row.get("season") or (fixture or {}).get("season"),
                "kickoff_at": (fixture or {}).get("kickoff") or row.get("kickoff_at") or row.get("kickoff") or row.get("fixture_date"),
                "prediction_timestamp": row.get("prediction_timestamp") or row.get("prediction_created_at"),
                "settled_at": row.get("settled_at"),
                "actual_outcome": row.get("actual_outcome"),
                "models": {},
                "source_rows": [],
                "versions": {},
            },
        )
        item["source_rows"].append(row)
        source_rows.append({**row, "canonical_league": code, "kickoff_at": item["kickoff_at"]})
        item["actual_outcome"] = item.get("actual_outcome") or row.get("actual_outcome")
        item["prediction_timestamp"] = min(
            (value for value in (item.get("prediction_timestamp"), row.get("prediction_timestamp") or row.get("prediction_created_at")) if value),
            default=item.get("prediction_timestamp"),
        )
        item["settled_at"] = min(
            (value for value in (item.get("settled_at"), row.get("settled_at")) if value),
            default=item.get("settled_at"),
        )
        model = _model_key(row)
        probabilities = normalize_probabilities(row.get("model_probabilities") or row.get("probabilities"))
        if model in {"deepseek", "gpt", "chatgpt"} and probabilities:
            item["models"]["deepseek" if model == "deepseek" else "gpt"] = probabilities
        baseline = (row.get("baseline") or {}).get("probabilities") if isinstance(row.get("baseline"), Mapping) else None
        baseline = normalize_probabilities(baseline)
        if baseline:
            item["models"].setdefault("poisson", baseline)
        if model == "poisson" and probabilities:
            item["models"]["poisson"] = probabilities
        for version_key in ("model_version", "feature_version", "ensemble_version", "calibration_version"):
            if row.get(version_key) is not None:
                item["versions"][version_key] = row[version_key]
    return sorted(grouped.values(), key=lambda row: (parse_timestamp(row.get("kickoff_at")) or datetime.max.replace(tzinfo=UTC), row["fixture_id"])), source_rows


def _p3_inputs(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    models = row.get("models") or {}
    for key, value in models.items():
        p3_key = "chatgpt" if key == "gpt" else key
        if p3_key in _P3_MODEL_KEYS and normalize_probabilities(value):
            result[p3_key] = normalize_probabilities(value) or {}
    return result


def _metric_report(rows: list[dict[str, Any]], model_key: str) -> dict[str, Any]:
    metrics = evaluate_probabilities(rows, lambda row: row.get("probabilities_by_model", {}).get(model_key))
    count = int(metrics.get("samples") or 0)
    status, confidence = sample_confidence(count)
    if count == 0:
        status = "unavailable"
        confidence = "unavailable"
    statistics = _metric_statistics(rows, model_key)
    return {
        "status": status,
        "model_key": model_key,
        "sample_count": count,
        "brier": metrics.get("brier"),
        "log_loss": metrics.get("log_loss"),
        "rps": metrics.get("rps"),
        "ece": metrics.get("ece"),
        "clv": metrics.get("clv"),
        "confidence": confidence,
        "statistics": statistics,
        "betting": {
            "status": "unavailable",
            "clv": metrics.get("clv"),
            "roi": None,
            "yield": None,
            "hit_rate": None,
            "drawdown": None,
            "reason": "complete frozen historical execution chain unavailable",
        },
    }


def _metric_statistics(rows: list[dict[str, Any]], model_key: str) -> dict[str, Any]:
    """Return mean, standard error, and a descriptive 95% CI per forecast metric."""

    values: dict[str, list[float]] = {key: [] for key in ("brier", "log_loss", "rps", "ece")}
    for row in rows:
        probabilities = normalize_probabilities((row.get("probabilities_by_model") or {}).get(model_key))
        actual = row.get("actual_outcome")
        if not probabilities or actual not in {"home", "draw", "away"}:
            continue
        values["brier"].append(sum((probabilities[key] - (1.0 if key == actual else 0.0)) ** 2 for key in ("home", "draw", "away")))
        values["log_loss"].append(-math.log(max(1e-9, probabilities[actual])))
        cumulative = 0.0
        actual_cumulative = 0.0
        rps = 0.0
        for key in ("home", "draw"):
            cumulative += probabilities[key]
            actual_cumulative += 1.0 if actual == key else 0.0
            rps += (cumulative - actual_cumulative) ** 2
        values["rps"].append(rps / 2)
        values["ece"].append(sum(abs(probabilities[key] - (1.0 if key == actual else 0.0)) for key in ("home", "draw", "away")) / 3)

    result: dict[str, Any] = {}
    for key, samples in values.items():
        count = len(samples)
        mean = sum(samples) / count if count else None
        standard_error = None
        interval = None
        if count > 1 and mean is not None:
            variance = sum((value - mean) ** 2 for value in samples) / (count - 1)
            standard_error = math.sqrt(variance / count)
            interval = [round(mean - 1.96 * standard_error, 6), round(mean + 1.96 * standard_error, 6)]
        result[key] = {
            "mean": round(mean, 6) if mean is not None else None,
            "standard_error": round(standard_error, 6) if standard_error is not None else None,
            "confidence_interval_95": interval,
        }
    return result


def _time_range(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = [parse_timestamp(row.get("kickoff_at") or row.get("prediction_timestamp")) for row in rows]
    values = [value for value in values if value]
    return {"start": min(values).isoformat() if values else None, "end": max(values).isoformat() if values else None}


def _prediction_range(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = [parse_timestamp(row.get("prediction_timestamp") or row.get("prediction_created_at")) for row in rows]
    values = [value for value in values if value]
    return {"start": min(values).isoformat() if values else None, "end": max(values).isoformat() if values else None}


class ModelEvaluationService:
    """Build and optionally persist a deterministic P6 evaluation result."""

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository

    def evaluate(
        self,
        settlements: Iterable[Mapping[str, Any]] | None = None,
        *,
        league: str | None = None,
    ) -> dict[str, Any]:
        requested_league = normalize_league_code(league) if league else None
        if league and requested_league is None:
            raise ValueError("Only CSL, EPL, and LAL are supported")
        if settlements is None:
            reader = getattr(self.repository, "fixture_settlements", None)
            settlements = reader() if callable(reader) else []
        fixture_reader = getattr(self.repository, "fixture", None) if self.repository else None
        prediction_reader = getattr(self.repository, "prediction", None) if self.repository else None
        fixtures, source_rows = _fixture_rows(
            settlements,
            fixture_reader=fixture_reader if callable(fixture_reader) else None,
            prediction_reader=prediction_reader if callable(prediction_reader) else None,
        )
        if requested_league:
            fixtures = [row for row in fixtures if row["canonical_league"] == requested_league]
            source_rows = [row for row in source_rows if row["canonical_league"] == requested_league]
        grouped = {code: [row for row in fixtures if row["canonical_league"] == code] for code in SUPPORTED_LEAGUES}
        reports = {code: self._evaluate_partition(code, grouped[code]) for code in SUPPORTED_LEAGUES if not requested_league or code == requested_league}
        all_rows = [row for code in SUPPORTED_LEAGUES for row in grouped[code]]
        reports["GLOBAL"] = self._evaluate_partition("GLOBAL", all_rows)
        dataset_version = frozen_dataset_fingerprint(source_rows)
        test_ids = sorted({fixture_id for report in reports.values() for fixture_id in report.get("test_fixture_ids", [])})
        experiment_key = json.dumps(
            {
                "dataset_version": dataset_version,
                "league": requested_league,
                "test_fixture_ids": test_ids,
                "feature_version": FEATURE_VERSION,
                "ensemble_version": ENSEMBLE_VERSION,
                "calibration_version": CALIBRATION_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        experiment_id = f"p6:{hashlib.sha256(experiment_key.encode()).hexdigest()[:32]}"
        snapshots_reader = None
        if self.repository:
            historical_reader = getattr(self.repository, "historical_snapshots", None)
            evidence_reader = getattr(self.repository, "evidence_snapshots", None)
            odds_reader = getattr(self.repository, "odds_snapshots", None)
            if any(callable(reader) for reader in (historical_reader, evidence_reader, odds_reader)):
                def read_auxiliary(fixture_id: str) -> list[Mapping[str, Any]]:
                    items: list[Mapping[str, Any]] = []
                    if callable(historical_reader):
                        items.extend(historical_reader(fixture_id=fixture_id, limit=100))
                    if callable(evidence_reader):
                        items.extend(evidence_reader(fixture_id))
                    if callable(odds_reader):
                        items.extend(odds_reader(fixture_id))
                    return items
                snapshots_reader = read_auxiliary
        audit = leakage_audit(source_rows, snapshot_reader=snapshots_reader)
        rolling = self._rolling_report(source_rows)
        global_report = reports.get("GLOBAL", {})
        status, confidence = sample_confidence(global_report.get("sample_count", 0))
        result = {
            "experiment_id": experiment_id,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "code_version": P6_VERSION,
            "status": status,
            "league": requested_league or "ALL",
            "dataset_version": dataset_version,
            "feature_version": FEATURE_VERSION,
            "ensemble_version": ENSEMBLE_VERSION,
            "calibration_version": CALIBRATION_VERSION,
            "sample_count": reports.get("GLOBAL", {}).get("sample_count", 0),
            "confidence": confidence,
            "train_range": global_report.get("train_range"),
            "validation_range": global_report.get("validation_range"),
            "test_range": global_report.get("test_range"),
            "reports": reports,
            "model_comparison": {key: value.get("models", {}) for key, value in reports.items()},
            "test_set": {"frozen": True, "fixture_ids": test_ids, "fingerprint": frozen_dataset_fingerprint([row for row in fixtures if row["fixture_id"] in test_ids])},
            "leakage_audit": audit,
            "rolling_backtest": rolling,
            "betting": {"status": "unavailable", "virtual_bankroll": {"initial_bankroll": 10000, "real_account_touched": False}, "reason": "P6 has no complete frozen historical execution chain"},
        }
        return result

    def run(self, settlements: Iterable[Mapping[str, Any]] | None = None, *, league: str | None = None) -> dict[str, Any]:
        """Compatibility alias for callers that use the P4 run convention."""

        return self.evaluate(settlements, league=league)

    @staticmethod
    def _rolling_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
        times = [parse_timestamp(row.get("prediction_created_at") or row.get("prediction_timestamp")) for row in rows]
        times = [value for value in times if value]
        if not times:
            return {"status": "insufficient_sample", "windows": [], "runs": 0}
        start = min(times).isoformat()
        end = max(times).isoformat()
        try:
            return RollingBacktestService(rows).run(start=start, end=end)
        except (TypeError, ValueError):
            return {"status": "insufficient_sample", "windows": [], "runs": 0}

    def _evaluate_partition(self, league: str, fixtures: list[dict[str, Any]]) -> dict[str, Any]:
        train, validation, test = chronological_split(fixtures)
        profile_rows = []
        for row in train:
            for model, probabilities in _p3_inputs(row).items():
                profile_rows.append({"model_key": model, "model_probabilities": probabilities, "actual_outcome": row.get("actual_outcome"), "league_key": row.get("league_key"), "prediction_created_at": row.get("prediction_timestamp"), "settled_at": row.get("settled_at")})
        profiles = build_performance_profiles(profile_rows, as_of=_time_range(train).get("end"))

        def enrich(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            enriched = []
            for row in rows:
                ensemble = weighted_ensemble(_p3_inputs(row), profiles=profiles, league_key=row.get("league_key"))
                enriched.append({**row, "raw_ensemble_probabilities": ensemble.get("ensemble_probabilities"), "ensemble_weights": ensemble.get("weights") or {}})
            return enriched

        validation_enriched = enrich(validation)
        test_enriched = enrich(test)
        validation_ensemble = [
            {**row, "probabilities_by_model": {"ensemble": row.get("raw_ensemble_probabilities")}}
            for row in validation_enriched
        ]
        # Calibration may use validation outcomes only when they were settled
        # before the first test prediction cutoff.
        test_prediction_range = _prediction_range(test)
        first_test_prediction = parse_timestamp(test_prediction_range.get("start"))
        calibration_as_of = (
            (first_test_prediction - timedelta(microseconds=1)).isoformat()
            if first_test_prediction
            else _prediction_range(validation).get("end")
        )
        calibration = fit_temperature(
            validation_ensemble,
            probability_reader=lambda row: row.get("probabilities_by_model", {}).get("ensemble"),
            trained_at=calibration_as_of,
            as_of=calibration_as_of,
        )
        evaluation_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        weights = (test_enriched[0].get("ensemble_weights") if test_enriched else (validation_enriched[0].get("ensemble_weights") if validation_enriched else {})) or {}
        for row in test_enriched:
            models = row.get("models") or {}
            if models.get("poisson"):
                evaluation_rows["baseline"].append({**row, "probabilities_by_model": {"baseline": models["poisson"]}})
                evaluation_rows["poisson"].append({**row, "probabilities_by_model": {"poisson": models["poisson"]}})
            for key in ("gpt", "deepseek"):
                if models.get(key):
                    evaluation_rows[key].append({**row, "probabilities_by_model": {key: models[key]}})
            if row.get("raw_ensemble_probabilities"):
                evaluation_rows["ensemble"].append({**row, "probabilities_by_model": {"ensemble": row["raw_ensemble_probabilities"]}})
                calibrated = row["raw_ensemble_probabilities"]
                if calibration.get("status") == "ok":
                    calibrated = apply_temperature(calibrated, float(calibration["temperature"]))
                evaluation_rows["calibrated_ensemble"].append({**row, "probabilities_by_model": {"calibrated_ensemble": calibrated}})
        model_reports = {}
        for model in MODEL_KEYS:
            model_reports[model] = _metric_report(evaluation_rows[model], model)
            if model in {"gpt", "deepseek"} and not evaluation_rows[model]:
                model_reports[model]["reason"] = "historical model prediction unavailable"
        baseline_metrics = model_reports["baseline"]
        for model, report in model_reports.items():
            report["improvement"] = {
                metric: round(float(baseline_metrics[metric]) - float(report[metric]), 6)
                if baseline_metrics.get(metric) is not None and report.get(metric) is not None
                else None
                for metric in ("brier", "log_loss", "rps", "ece")
            }
        model_test_fixture_ids = {
            model: sorted({str(row.get("fixture_id") or "") for row in evaluation_rows[model]})
            for model in MODEL_KEYS
        }
        comparable_sets = [set(ids) for ids in model_test_fixture_ids.values() if ids]
        common_test_fixture_ids = sorted(set.intersection(*comparable_sets)) if comparable_sets else []
        feature_names = ("team_strength", "recent_form", "home_away", "squad", "schedule", "market_context")
        ablation = {
            "full_ensemble": {
                "feature_set": list(feature_names),
                "train_range": _time_range(train),
                "test_range": _time_range(test),
                "sample_count": model_reports["ensemble"]["sample_count"],
                **{key: model_reports["ensemble"].get(key) for key in ("brier", "log_loss", "rps", "ece")},
                "logloss": model_reports["ensemble"].get("log_loss"),
                "status": model_reports["ensemble"]["status"],
            }
        }
        for feature in feature_names:
            ablation[feature] = {
                "feature_set": [item for item in feature_names if item != feature],
                "train_range": _time_range(train),
                "test_range": _time_range(test),
                "sample_count": 0,
                "brier": None,
                "logloss": None,
                "rps": None,
                "ece": None,
                "status": "unavailable",
                "reason": "feature-specific historical forecasts were not persisted",
            }
        status, confidence = sample_confidence(len(test))
        partition_result = {
            "league": league,
            "sample_count": len(test),
            "confidence": confidence,
            "sample_size_warning": status,
            "train_range": _time_range(train),
            "validation_range": _time_range(validation),
            "test_range": _time_range(test),
            "test_prediction_range": test_prediction_range,
            "baseline_type": "poisson",
            "train_fixture_ids": [row["fixture_id"] for row in train],
            "validation_fixture_ids": [row["fixture_id"] for row in validation],
            "test_fixture_ids": [row["fixture_id"] for row in test],
            "weights": weights,
            "weights_fit_on": "train",
            "calibration": {**calibration, "fit_on": "validation", "fit_as_of": calibration_as_of},
            "models": model_reports,
            "model_versions": {
                key: sorted({str(row.get("versions", {}).get(key) or "") for row in fixtures if row.get("versions", {}).get(key)})
                for key in ("model_version", "feature_version", "ensemble_version", "calibration_version")
            },
            "model_test_fixture_ids": model_test_fixture_ids,
            "common_test_fixture_ids": common_test_fixture_ids,
            "ablation": ablation,
            "betting": {"status": "unavailable", "reason": "virtual execution chain not supplied"},
        }
        partition_result.update(model_reports)
        return partition_result


__all__ = [
    "CALIBRATION_VERSION",
    "ENSEMBLE_VERSION",
    "FEATURE_VERSION",
    "MODEL_KEYS",
    "ModelEvaluationService",
    "P6_VERSION",
    "audit_prediction_leakage",
    "chronological_split",
    "frozen_dataset_fingerprint",
    "leakage_audit",
    "sample_confidence",
]
