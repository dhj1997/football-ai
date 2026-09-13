"""P10 Model Registry: versioned, immutable model artifacts with gates.

Every model artifact records its full provenance (feature/dataset/
calibration versions, training cutoff, artifact hash). Lifecycle is
``draft → candidate → champion/active → retired``. Promotion from
candidate to a production state requires metric, calibration, stability
and leakage gates to pass on one fixed dataset — never a silent swap.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

MODEL_STATUSES: tuple[str, ...] = ("draft", "candidate", "champion", "active", "retired")
PRODUCTION_STATUSES: frozenset[str] = frozenset({"champion", "active"})
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"candidate", "retired"}),
    "candidate": frozenset({"champion", "active", "retired"}),
    "champion": frozenset({"active", "retired"}),
    "active": frozenset({"champion", "retired"}),
    "retired": frozenset(),
}
IMMUTABLE_FIELDS: tuple[str, ...] = (
    "competition_scope",
    "feature_version",
    "dataset_fingerprint",
    "training_cutoff",
    "calibration_version",
    "artifact_hash",
    "created_at",
)

DEFAULT_PROMOTION_GATES: dict[str, float] = {
    "metric_tolerance": 0.0,
    "max_ece": 0.2,
    "max_stability_spread": 0.1,
    "min_samples": 30,
}


class ModelRegistryError(ValueError):
    """Raised for invalid lifecycle or provenance operations."""


def artifact_hash(definition: Mapping[str, Any]) -> str:
    """Hash the model definition so identical artifacts share one identity."""

    canonical = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def dataset_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
    """Fingerprint the evaluation dataset (fixtures, timestamps, outcomes)."""

    stable = sorted(
        (
            str(row.get("fixture_id") or ""),
            str(row.get("prediction_created_at") or ""),
            str(row.get("actual_outcome") or ""),
        )
        for row in rows
    )
    encoded = json.dumps(stable, ensure_ascii=False, separators=(",", ":"))
    return f"dataset:{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


@dataclass
class ModelRecord:
    """One immutable model artifact plus its lifecycle status."""

    model_key: str
    model_version: str
    artifact_hash: str
    status: str = "draft"
    competition_scope: str | None = None
    feature_version: str | None = None
    dataset_fingerprint: str | None = None
    training_cutoff: str | None = None
    calibration_version: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_key or not self.model_version or not self.artifact_hash:
            raise ModelRegistryError("model_key, model_version and artifact_hash are required")
        if self.status not in MODEL_STATUSES:
            raise ModelRegistryError(f"Invalid model status: {self.status}")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def provenance(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in ("model_key", "model_version", "competition_scope", "feature_version", "dataset_fingerprint", "training_cutoff", "calibration_version", "artifact_hash", "created_at")
        }


def evaluate_promotion(
    challenger_metrics: Mapping[str, Any],
    champion_metrics: Mapping[str, Any] | None,
    *,
    gates: Mapping[str, float] = DEFAULT_PROMOTION_GATES,
    leakage_violations: int = 0,
) -> dict[str, Any]:
    """Judge a challenger against the champion on one fixed dataset.

    Gates: metric (Brier must not be worse), calibration (ECE bound and a
    validation-only fit), stability (windowed Brier spread), leakage
    (zero violations). All must pass for promotion.
    """

    policy = {**DEFAULT_PROMOTION_GATES, **dict(gates or {})}
    samples = int(challenger_metrics.get("samples") or 0)
    metric_gate = "fail"
    if challenger_metrics.get("brier") is not None and samples >= int(policy["min_samples"]):
        if champion_metrics is None or champion_metrics.get("brier") is None:
            metric_gate = "pass"
        elif float(challenger_metrics["brier"]) <= float(champion_metrics["brier"]) + float(policy["metric_tolerance"]):
            metric_gate = "pass"
    calibration_gate = "fail"
    if (
        challenger_metrics.get("ece") is not None
        and float(challenger_metrics["ece"]) <= float(policy["max_ece"])
        and challenger_metrics.get("calibration_status") in {"ok", "not_applicable"}
    ):
        calibration_gate = "pass"
    stability_gate = "fail"
    window_briers = [float(value) for value in challenger_metrics.get("window_briers") or []]
    if len(window_briers) >= 2 and max(window_briers) - min(window_briers) <= float(policy["max_stability_spread"]):
        stability_gate = "pass"
    leakage_gate = "pass" if int(leakage_violations) == 0 else "fail"
    return {
        "metric_gate": metric_gate,
        "calibration_gate": calibration_gate,
        "stability_gate": stability_gate,
        "leakage_gate": leakage_gate,
        "samples": samples,
        "promoted": all(
            value == "pass"
            for value in (metric_gate, calibration_gate, stability_gate, leakage_gate)
        ),
    }


class ModelRegistry:
    """Persist and govern model artifacts through the repository layer."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def register(self, record: ModelRecord) -> ModelRecord:
        saver = getattr(self.repository, "save_model_registry", None)
        if not callable(saver):
            raise ModelRegistryError("repository does not support model registry persistence")
        existing = self.get(record.model_key, record.model_version)
        if existing is not None:
            if existing.artifact_hash != record.artifact_hash:
                raise ModelRegistryError(
                    f"Model {record.model_key}:{record.model_version} is already registered with a different artifact"
                )
            # Re-registering an identical artifact is idempotent.
            return existing
        saver(record.as_dict())
        return record

    def get(self, model_key: str, model_version: str | None = None) -> ModelRecord | None:
        reader = getattr(self.repository, "model_registry", None)
        if not callable(reader):
            return None
        rows = reader(model_key=model_key)
        if model_version is not None:
            rows = [row for row in rows if row["model_version"] == model_version]
        if not rows:
            return None
        row = rows[0]
        return ModelRecord(**{key: row.get(key) for key in ModelRecord.__dataclass_fields__})

    def list(self, model_key: str | None = None, status: str | None = None) -> list[ModelRecord]:
        reader = getattr(self.repository, "model_registry", None)
        rows = reader(model_key=model_key) if callable(reader) else []
        if status:
            rows = [row for row in rows if row["status"] == status]
        return [
            ModelRecord(**{key: row.get(key) for key in ModelRecord.__dataclass_fields__})
            for row in rows
        ]

    def transition(
        self,
        model_key: str,
        model_version: str,
        target_status: str,
        *,
        promotion_evidence: Mapping[str, Any] | None = None,
    ) -> ModelRecord:
        if target_status not in MODEL_STATUSES:
            raise ModelRegistryError(f"Invalid target status: {target_status}")
        record = self.get(model_key, model_version)
        if record is None:
            raise ModelRegistryError(f"Unknown model {model_key}:{model_version}")
        if target_status not in STATUS_TRANSITIONS[record.status]:
            raise ModelRegistryError(
                f"Invalid transition {record.model_key}:{record.model_version} {record.status} -> {target_status}"
            )
        if target_status in PRODUCTION_STATUSES and record.status == "candidate":
            if not promotion_evidence or not promotion_evidence.get("promoted"):
                raise ModelRegistryError(
                    "Promotion to a production status requires passing metric/calibration/stability/leakage gates"
                )
        record.status = target_status
        saver = getattr(self.repository, "save_model_registry", None)
        if callable(saver):
            saver(record.as_dict())
        return record

    def champion(self, model_key: str) -> ModelRecord | None:
        production = [row for row in self.list(model_key=model_key) if row.status in PRODUCTION_STATUSES]
        if not production:
            return None
        return max(production, key=lambda row: row.created_at)
