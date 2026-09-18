"""Point-in-time leakage audits for immutable prediction feature snapshots."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping

from .prediction_intelligence import parse_timestamp


class FutureDataLeakageError(ValueError):
    """Raised when a production prediction attempts to use future data."""


class LeakageAuditService:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def audit_feature_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        prediction_id: str | None = None,
        persist: bool = True,
        expected_prediction: Mapping[str, Any] | None = None,
        expected_revision: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        cutoff = parse_timestamp(
            snapshot.get("prediction_cutoff_at") or snapshot.get("prediction_timestamp")
        )
        snapshot_id = snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id")
        feature_version = snapshot.get("feature_version")
        snapshot_fixture_ids = _entity_ids(snapshot)
        features = [
            dict(item)
            for item in snapshot.get("features") or []
            if isinstance(item, Mapping)
        ]
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        failed_names: set[str] = set()

        def reject(name: str, reason: str, **details: Any) -> None:
            violations.append({"feature_name": name, **details, "reason": reason})
            failed_names.add(name)

        if cutoff is None:
            reject("snapshot", "prediction_cutoff_at_missing_or_invalid")
            failed_names.update(str(item.get("feature_name") or "unknown") for item in features)
        if not snapshot_id:
            reject("snapshot", "snapshot_id_missing")
        if not feature_version:
            reject("snapshot", "feature_version_missing")
        if not snapshot_fixture_ids:
            reject("snapshot", "fixture_id_missing")
        if not features:
            reject("snapshot", "feature_values_missing")

        for item in features:
            name = str(item.get("feature_name") or "unknown")
            required_fields = (
                "feature_name",
                "feature_value",
                "source",
                "source_record_id",
                "computed_at",
                "available_at",
                "prediction_cutoff_at",
                "feature_version",
                "snapshot_id",
            )
            missing_fields = [field for field in required_fields if field not in item]
            if missing_fields:
                reject(name, "required_feature_fields_missing", fields=missing_fields)
            for field in ("feature_name", "source", "source_record_id", "computed_at", "prediction_cutoff_at", "feature_version", "snapshot_id"):
                if item.get(field) in (None, ""):
                    reject(name, "required_feature_field_empty", field=field)
            feature_cutoff = parse_timestamp(item.get("prediction_cutoff_at"))
            available_at = parse_timestamp(item.get("available_at"))
            status = str(item.get("status") or "")
            if cutoff is not None and feature_cutoff != cutoff:
                reject(
                    name,
                    "feature_cutoff_mismatch",
                    available_at=item.get("available_at"),
                    prediction_cutoff_at=item.get("prediction_cutoff_at"),
                )
            if item.get("computed_at") and parse_timestamp(item.get("computed_at")) is None:
                reject(name, "computed_at_invalid", computed_at=item.get("computed_at"))
            if snapshot_id and item.get("snapshot_id") != snapshot_id:
                reject(name, "feature_snapshot_id_mismatch", snapshot_id=item.get("snapshot_id"))
            if feature_version and item.get("feature_version") != feature_version:
                reject(
                    name,
                    "feature_version_mismatch",
                    feature_version=item.get("feature_version"),
                )
            raw_available_at = item.get("available_at")
            has_value = not _missing_feature_value(item.get("feature_value"))
            if raw_available_at not in (None, "") and available_at is None:
                reject(name, "available_at_invalid", available_at=raw_available_at)
            if has_value and available_at is None:
                reject(name, "available_at_missing", available_at=raw_available_at)
            if cutoff is not None and available_at is not None and available_at > cutoff:
                reject(
                    name,
                    "available_after_prediction_cutoff",
                    available_at=available_at.isoformat(),
                    prediction_cutoff_at=cutoff.isoformat(),
                )
            if status in {"future", "unverifiable"}:
                reject(name, f"feature_status_{status}")
            if status == "available" and not has_value:
                reject(name, "available_feature_value_missing")
            if status == "missing" and has_value:
                reject(name, "missing_status_has_value")

        for raw in (snapshot.get("leakage_check") or {}).get("rejected_future_fields") or []:
            name = str(raw)
            if name in failed_names:
                continue
            reject(
                name,
                "source_rejected_by_snapshot",
                prediction_cutoff_at=cutoff.isoformat() if cutoff else None,
            )

        # A feature snapshot is only auditable when every referenced source
        # snapshot can be resolved and proves a capture at or before cutoff.
        # Lightweight test doubles may not expose read APIs; those are marked
        # WARN unless this is a persisted prediction/revision audit, where a
        # missing reader is an unresolvable audit-chain violation.
        for kind, reference_id in (
            ("evidence", snapshot.get("evidence_snapshot_id")),
            ("odds", snapshot.get("odds_snapshot_id")),
        ):
            if reference_id in (None, ""):
                continue
            reference = self._resolve_reference(kind, str(reference_id), snapshot)
            if reference is None:
                reader_available = callable(getattr(self.repository, f"{kind}_snapshot", None))
                if reader_available or expected_prediction or expected_revision:
                    reject(
                        "snapshot",
                        f"{kind}_snapshot_missing",
                        snapshot_id=str(reference_id),
                    )
                else:
                    warnings.append(
                        {
                            "feature_name": f"{kind}_snapshot",
                            "reason": "reference_reader_unavailable",
                            "snapshot_id": str(reference_id),
                        }
                    )
                continue
            self._audit_reference(
                kind,
                str(reference_id),
                reference,
                snapshot_fixture_ids,
                cutoff,
                reject,
            )

        for owner, expected in (
            ("prediction", expected_prediction or {}),
            ("revision", expected_revision or {}),
        ):
            expected_pairs = (
                ("feature_snapshot_id", snapshot_id, expected.get("feature_snapshot_id")),
                ("prediction_cutoff_at", snapshot.get("prediction_cutoff_at"), expected.get("prediction_cutoff_at") or expected.get("prediction_timestamp")),
                ("feature_version", feature_version, expected.get("feature_version")),
                ("evidence_snapshot_id", snapshot.get("evidence_snapshot_id"), expected.get("evidence_snapshot_id")),
                ("odds_snapshot_id", snapshot.get("odds_snapshot_id"), expected.get("odds_snapshot_id")),
            )
            for field, actual, wanted in expected_pairs:
                if wanted not in (None, "") and str(actual or "") != str(wanted):
                    reject(
                        "snapshot",
                        f"{owner}_{field}_mismatch",
                        actual=actual,
                        expected=wanted,
                    )
            expected_fixture_ids = _entity_ids(expected)
            if (
                expected_fixture_ids
                and snapshot_fixture_ids
                and not expected_fixture_ids.intersection(snapshot_fixture_ids)
            ):
                reject(
                    "snapshot",
                    f"{owner}_fixture_id_mismatch",
                    actual=sorted(snapshot_fixture_ids),
                    expected=sorted(expected_fixture_ids),
                )
        if bool(snapshot.get("leakage_detected")) and not violations:
            reject("snapshot", "snapshot_declared_leakage")

        status = "FAIL" if violations else "WARN" if warnings else "PASS"
        checked = len(features)
        failed_features = {name for name in failed_names if name != "snapshot"}
        audit = {
            "audit_id": f"leakage:{uuid.uuid4()}",
            "prediction_id": prediction_id,
            "feature_snapshot_id": snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id"),
            "status": status,
            "prediction_cutoff_at": cutoff.isoformat() if cutoff else None,
            "violations": violations,
            "warnings": warnings,
            "features_checked": checked,
            "features_passed": max(0, checked - len(failed_features)),
            "features_failed": len(failed_features),
            "created_at": datetime.now(UTC).isoformat(),
        }
        saver = getattr(self.repository, "save_leakage_audit", None)
        if persist and callable(saver):
            saver(deepcopy(audit))
        return audit

    def audit_prediction(self, prediction_id: str) -> dict[str, Any]:
        reader = getattr(self.repository, "prediction", None)
        prediction = reader(prediction_id) if callable(reader) else None
        if prediction is None:
            raise ValueError(f"Prediction was not found: {prediction_id}")
        snapshot = prediction.get("feature_snapshot")
        snapshot_id = prediction.get("feature_snapshot_id")
        snapshot_reader = getattr(self.repository, "feature_snapshot", None)
        if snapshot_id and callable(snapshot_reader):
            snapshot = snapshot_reader(str(snapshot_id)) or snapshot
        if not isinstance(snapshot, Mapping):
            missing = {
                "audit_id": f"leakage:{uuid.uuid4()}",
                "prediction_id": prediction_id,
                "feature_snapshot_id": snapshot_id,
                "status": "FAIL",
                "prediction_cutoff_at": prediction.get("prediction_cutoff_at")
                or prediction.get("prediction_timestamp")
                or prediction.get("created_at"),
                "violations": [{"feature_name": "snapshot", "reason": "feature_snapshot_missing"}],
                "warnings": [],
                "features_checked": 0,
                "features_passed": 0,
                "features_failed": 0,
                "created_at": datetime.now(UTC).isoformat(),
            }
            saver = getattr(self.repository, "save_leakage_audit", None)
            if callable(saver):
                saver(deepcopy(missing))
            return missing
        revision_reader = getattr(self.repository, "prediction_revision", None)
        revision = revision_reader(prediction_id) if callable(revision_reader) else None
        return self.audit_feature_snapshot(
            snapshot,
            prediction_id=prediction_id,
            expected_prediction=prediction,
            expected_revision=revision,
        )

    def _resolve_reference(
        self,
        kind: str,
        reference_id: str,
        snapshot: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        reader = getattr(self.repository, f"{kind}_snapshot", None)
        if callable(reader):
            resolved = reader(reference_id)
            return resolved if isinstance(resolved, Mapping) else None
        inline = snapshot.get(f"{kind}_snapshot")
        return inline if isinstance(inline, Mapping) else None

    @staticmethod
    def _audit_reference(
        kind: str,
        reference_id: str,
        reference: Mapping[str, Any],
        snapshot_fixture_ids: set[str],
        cutoff: datetime | None,
        reject: Any,
    ) -> None:
        actual_id = reference.get("id") or reference.get("snapshot_id")
        if actual_id not in (None, "") and str(actual_id) != reference_id:
            reject(
                "snapshot",
                f"{kind}_snapshot_id_mismatch",
                snapshot_id=reference_id,
                actual_snapshot_id=str(actual_id),
            )
        reference_fixture_ids = _entity_ids(reference)
        if (
            snapshot_fixture_ids
            and reference_fixture_ids
            and not snapshot_fixture_ids.intersection(reference_fixture_ids)
        ):
            reject(
                "snapshot",
                f"{kind}_snapshot_fixture_id_mismatch",
                snapshot_fixture_id=sorted(snapshot_fixture_ids),
                reference_fixture_id=sorted(reference_fixture_ids),
            )
        raw_captured_at = reference.get("captured_at")
        captured_at = parse_timestamp(raw_captured_at)
        if raw_captured_at not in (None, "") and captured_at is None:
            reject(
                "snapshot",
                f"{kind}_captured_at_invalid",
                captured_at=raw_captured_at,
            )
        elif captured_at is None:
            reject("snapshot", f"{kind}_captured_at_missing")
        elif cutoff is not None and captured_at > cutoff:
            reject(
                "snapshot",
                f"{kind}_captured_after_prediction_cutoff",
                captured_at=captured_at.isoformat(),
                prediction_cutoff_at=cutoff.isoformat(),
            )


def _missing_feature_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, Mapping):
        return not value or all(_missing_feature_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return not value or all(_missing_feature_value(item) for item in value)
    return False


def _entity_ids(value: Any) -> set[str]:
    """Collect provider/canonical fixture identifiers from a persisted record."""

    if not isinstance(value, Mapping):
        return set()
    identifiers: set[str] = set()
    for field in ("fixture_id", "match_id", "canonical_fixture_id"):
        item = value.get(field)
        if item not in (None, ""):
            identifiers.add(str(item))
    for nested in (
        value.get("fixture"),
        value.get("payload"),
    ):
        if isinstance(nested, Mapping):
            identifiers.update(_entity_ids(nested))
    return identifiers


__all__ = ["FutureDataLeakageError", "LeakageAuditService"]
