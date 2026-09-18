"""Fail-closed validation for Round 6.5 production probability evidence."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .market_prior import OUTCOMES
from .prediction_intelligence import parse_timestamp


PRODUCTION_EVIDENCE_VERSION = "round6.5-production-evidence-v1"
PRODUCTION_EVIDENCE_KIND = "production_prediction"


class ProductionEvidenceError(ValueError):
    """Raised when a probability record cannot prove production provenance."""


def validate_production_evidence(
    evidence: Mapping[str, Any],
    *,
    feature_snapshot: Mapping[str, Any] | None = None,
    odds_snapshots: Iterable[Mapping[str, Any]] | None = None,
    leakage_audit: Mapping[str, Any] | None = None,
    replay: bool | None = None,
) -> dict[str, Any]:
    """Validate and normalize one complete pre-match production evidence row.

    The function deliberately accepts the already-built Round 5 payload rather
    than recalculating probabilities. It is therefore safe to use at a
    persistence boundary and during read-only audits.
    """

    if not isinstance(evidence, Mapping):
        raise ProductionEvidenceError("production evidence must be an object")
    audit = evidence.get("audit")
    if not isinstance(audit, Mapping):
        audit = evidence.get("round5_probability_audit")
    if not isinstance(audit, Mapping):
        audit = evidence

    replay_flag = replay if replay is not None else bool(
        evidence.get("replayed_prediction")
        or evidence.get("is_historical_replay")
        or audit.get("replayed_prediction")
    )
    if replay_flag:
        raise ProductionEvidenceError("historical replay cannot be production evidence")
    if audit.get("production_evidence_valid") is not True:
        raise ProductionEvidenceError("production evidence must be explicitly marked valid")
    if str(audit.get("evidence_kind") or "") != PRODUCTION_EVIDENCE_KIND:
        raise ProductionEvidenceError("evidence_kind must identify a production prediction")
    if str(
        audit.get("production_evidence_version")
        or evidence.get("production_evidence_version")
        or ""
    ) != PRODUCTION_EVIDENCE_VERSION:
        raise ProductionEvidenceError("production_evidence_version is unsupported")

    fixture_id = _required_text(
        audit.get("fixture_id") or evidence.get("fixture_id"), "fixture_id"
    )
    revision_id = _required_text(
        audit.get("prediction_revision_id")
        or evidence.get("prediction_revision_id")
        or evidence.get("revision_id"),
        "prediction_revision_id",
    )
    cutoff = _required_time(
        audit.get("prediction_cutoff_at") or evidence.get("prediction_cutoff_at"),
        "prediction_cutoff_at",
    )
    kickoff = _required_time(
        audit.get("kickoff_at") or evidence.get("kickoff_at"), "kickoff_at"
    )
    persisted = _required_time(
        audit.get("persisted_at")
        or audit.get("production_persisted_at")
        or evidence.get("persisted_at")
        or evidence.get("production_persisted_at"),
        "persisted_at",
    )
    if cutoff >= kickoff:
        raise ProductionEvidenceError("prediction_cutoff_at must be before kickoff_at")
    if persisted < cutoff:
        raise ProductionEvidenceError("persisted_at must be at or after prediction_cutoff_at")
    if persisted >= kickoff:
        raise ProductionEvidenceError("persisted_at must be before kickoff_at")

    model_probability = _probability_vector(
        audit.get("model_probability") or evidence.get("model_probability"),
        "model_probability",
    )
    final_probability = _probability_vector(
        audit.get("final_probability") or evidence.get("final_probability"),
        "final_probability",
    )
    market_status = str(
        audit.get("market_status") or evidence.get("market_status") or ""
    )
    source_ids = [
        str(value)
        for value in (audit.get("source_odds_snapshot_ids") or evidence.get("source_odds_snapshot_ids") or [])
        if value not in (None, "")
    ]
    market_probability_raw = audit.get("market_probability")
    if market_probability_raw is None and "market_probability" in evidence:
        market_probability_raw = evidence.get("market_probability")
    market_probability = None
    if market_status == "MODEL_PLUS_MARKET":
        if not source_ids:
            raise ProductionEvidenceError(
                "MODEL_PLUS_MARKET evidence requires source odds snapshots"
            )
        market_probability = _probability_vector(market_probability_raw, "market_probability")
    elif market_status == "MODEL_ONLY":
        if source_ids:
            raise ProductionEvidenceError("MODEL_ONLY evidence cannot reference market odds")
        if market_probability_raw is not None:
            raise ProductionEvidenceError("MODEL_ONLY evidence must have no market probability")
        if any(
            not math.isclose(model_probability[key], final_probability[key], abs_tol=1e-9)
            for key in OUTCOMES
        ):
            raise ProductionEvidenceError("MODEL_ONLY final probability must equal model probability")
    else:
        raise ProductionEvidenceError("market_status must be MODEL_ONLY or MODEL_PLUS_MARKET")

    feature = _unwrap_feature_snapshot(feature_snapshot or evidence.get("feature_snapshot"))
    feature_id = _required_text(
        audit.get("feature_snapshot_id")
        or evidence.get("feature_snapshot_id")
        or (feature or {}).get("snapshot_id"),
        "feature_snapshot_id",
    )
    if feature is None:
        raise ProductionEvidenceError("feature_snapshot is required")
    if str(feature.get("snapshot_id") or feature.get("feature_snapshot_id") or "") != feature_id:
        raise ProductionEvidenceError("feature_snapshot_id does not match feature snapshot")
    if str(feature.get("fixture_id") or feature.get("canonical_fixture_id") or "") != fixture_id:
        raise ProductionEvidenceError("feature snapshot fixture_id does not match evidence")
    feature_cutoff = _required_time(
        feature.get("prediction_cutoff_at"), "feature_snapshot.prediction_cutoff_at"
    )
    if feature_cutoff != cutoff:
        raise ProductionEvidenceError("feature snapshot cutoff does not match evidence")
    features = feature.get("features")
    if not isinstance(features, list) or not features:
        raise ProductionEvidenceError("feature snapshot has no feature values")
    for row in features:
        if not isinstance(row, Mapping):
            raise ProductionEvidenceError("feature snapshot contains an invalid feature row")
        available_raw = row.get("available_at")
        if available_raw in (None, ""):
            status = str(row.get("status") or "").casefold()
            if row.get("feature_value") is not None and status not in {"missing", "unavailable"}:
                raise ProductionEvidenceError("non-missing feature must have available_at")
            continue
        available = parse_timestamp(available_raw)
        if available is None:
            raise ProductionEvidenceError("feature available_at is invalid")
        if available > cutoff:
            raise ProductionEvidenceError("feature available_at is after prediction cutoff")

    audit_row = leakage_audit or evidence.get("leakage_audit")
    if not isinstance(audit_row, Mapping):
        raise ProductionEvidenceError("leakage audit is required")
    audit_id = _required_text(
        audit.get("leakage_audit_id") or evidence.get("leakage_audit_id"),
        "leakage_audit_id",
    )
    actual_audit_id = _required_text(
        audit_row.get("audit_id"), "leakage audit audit_id"
    )
    if actual_audit_id != audit_id:
        raise ProductionEvidenceError(
            "leakage_audit_id does not match leakage audit"
        )
    if str(audit_row.get("status") or "").upper() != "PASS":
        raise ProductionEvidenceError("production evidence requires a PASS leakage audit")
    if str(audit_row.get("feature_snapshot_id") or "") != feature_id:
        raise ProductionEvidenceError("leakage audit feature_snapshot_id does not match evidence")
    if parse_timestamp(audit_row.get("prediction_cutoff_at")) != cutoff:
        raise ProductionEvidenceError("leakage audit cutoff does not match evidence")

    odds_map: dict[str, Mapping[str, Any]] = {}
    for item in odds_snapshots or []:
        if not isinstance(item, Mapping):
            continue
        item_id = item.get("id") or item.get("snapshot_id")
        if item_id not in (None, ""):
            odds_map[str(item_id)] = item
    if market_status == "MODEL_PLUS_MARKET":
        if not odds_map:
            raise ProductionEvidenceError("odds snapshots are required for MODEL_PLUS_MARKET")
        for snapshot_id in source_ids:
            snapshot = odds_map.get(snapshot_id)
            if snapshot is None:
                raise ProductionEvidenceError(f"odds snapshot {snapshot_id} was not found")
            if str(snapshot.get("fixture_id") or "") != fixture_id:
                raise ProductionEvidenceError("odds snapshot fixture_id does not match evidence")
            captured = _required_time(snapshot.get("captured_at"), "odds captured_at")
            if captured > cutoff:
                raise ProductionEvidenceError("odds snapshot is after prediction cutoff")
            source_updated = snapshot.get("source_updated_at")
            if source_updated not in (None, ""):
                updated = _required_time(source_updated, "odds source_updated_at")
                if updated > cutoff:
                    raise ProductionEvidenceError("odds source_updated_at is after prediction cutoff")

    return {
        "production_evidence_version": PRODUCTION_EVIDENCE_VERSION,
        "evidence_kind": PRODUCTION_EVIDENCE_KIND,
        "production_evidence_valid": True,
        "prediction_revision_id": revision_id,
        "fixture_id": fixture_id,
        "prediction_cutoff_at": cutoff.isoformat(),
        "kickoff_at": kickoff.isoformat(),
        "persisted_at": persisted.isoformat(),
        "feature_snapshot_id": feature_id,
        "source_odds_snapshot_ids": source_ids,
        "leakage_audit_id": audit_id,
        "market_status": market_status,
        "model_probability": model_probability,
        "market_probability": market_probability,
        "final_probability": final_probability,
        "probability_model_version": _required_text(
            audit.get("probability_model_version") or evidence.get("probability_model_version"),
            "probability_model_version",
        ),
        "probability_calculation_version": _required_text(
            audit.get("probability_calculation_version")
            or evidence.get("probability_calculation_version")
            or evidence.get("calculation_version"),
            "probability_calculation_version",
        ),
    }


def is_production_evidence(
    evidence: Mapping[str, Any],
    **kwargs: Any,
) -> bool:
    """Return a boolean for read-only eligibility checks."""

    try:
        validate_production_evidence(evidence, **kwargs)
    except (ProductionEvidenceError, TypeError, ValueError):
        return False
    return True


def _unwrap_feature_snapshot(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    nested = value.get("feature_snapshot")
    return nested if isinstance(nested, Mapping) else value


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ProductionEvidenceError(f"{field} is required")
    return normalized


def _required_time(value: Any, field: str):
    parsed = parse_timestamp(value)
    if parsed is None:
        raise ProductionEvidenceError(f"{field} is required and must be a valid timestamp")
    return parsed


def _probability_vector(value: Any, field: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(OUTCOMES):
        raise ProductionEvidenceError(f"{field} must contain home, draw, and away")
    result: dict[str, float] = {}
    for outcome in OUTCOMES:
        raw = value.get(outcome)
        if isinstance(raw, bool):
            raise ProductionEvidenceError(f"{field}.{outcome} is invalid")
        try:
            number = float(raw)
        except (TypeError, ValueError) as error:
            raise ProductionEvidenceError(f"{field}.{outcome} is invalid") from error
        if not math.isfinite(number) or number < 0:
            raise ProductionEvidenceError(f"{field}.{outcome} is invalid")
        result[outcome] = number
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-8):
        raise ProductionEvidenceError(f"{field} must sum to one")
    return result
