"""Evaluation-only temporal backtest over persisted Round 5 probability audits."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from .leakage_audit import LeakageAuditService
from .market_prior import AUDIT_VERSION, MarketPriorConfig
from .prediction_intelligence import parse_timestamp
from .probability_evaluation import (
    METRICS_VERSION,
    MIN_SAMPLES,
    ProbabilityEvaluationService,
)
from .production_evidence import (
    PRODUCTION_EVIDENCE_KIND,
    ProductionEvidenceError,
    validate_production_evidence,
)


BACKTEST_VERSION = "round6-v1"
SOURCE_KIND = "historical_production_prediction"
EVALUATION_UNIT = "fixture_cutoff"
DEFAULT_CUTOFF_OFFSETS_HOURS = (24.0, 12.0, 6.0, 1.0, 0.5)
LAYERS = ("model", "market", "final")


class TemporalBacktestService:
    """Build a deterministic, read-only report from immutable historical inputs."""

    def __init__(
        self,
        repository: Any,
        *,
        min_samples: int = MIN_SAMPLES,
        cutoff_offsets_hours: Iterable[float] = DEFAULT_CUTOFF_OFFSETS_HOURS,
    ) -> None:
        self.repository = repository
        self.evaluator = ProbabilityEvaluationService(min_samples=min_samples)
        offsets = {float(value) for value in cutoff_offsets_hours if float(value) > 0}
        self.cutoff_offsets_hours = tuple(sorted(offsets, reverse=True))
        self.min_samples = int(min_samples)
        self.market_config = MarketPriorConfig()

    def run(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        league_key: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        fixtures = self._fixtures(start_date, end_date, league_key, limit)
        market_reader = getattr(self.repository, "market_snapshots", None)
        market_by_fixture: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for fixture in fixtures:
            fixture_id = str(fixture.get("id") or "")
            snapshots = market_reader(fixture_id) if fixture_id and callable(market_reader) else []
            market_by_fixture[fixture_id].extend(
                snapshot for snapshot in snapshots if isinstance(snapshot, Mapping)
            )
        feature_snapshot_ids = sorted(
            {
                str(record["audit"].get("feature_snapshot_id") or "")
                for snapshots in market_by_fixture.values()
                for snapshot in snapshots
                if (record := _round5_audit_record(snapshot)) is not None
                and record["audit"].get("feature_snapshot_id")
            }
        )
        audit_reader = getattr(self.repository, "leakage_audits", None)
        all_leakage_audits = (
            audit_reader(feature_snapshot_ids=feature_snapshot_ids)
            if feature_snapshot_ids and callable(audit_reader)
            else []
        )
        leakage_by_snapshot: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for audit in all_leakage_audits:
            if isinstance(audit, Mapping):
                snapshot_id = str(
                    audit.get("feature_snapshot_id") or audit.get("snapshot_id") or ""
                )
                if snapshot_id:
                    leakage_by_snapshot[snapshot_id].append(audit)
        exclusions: Counter[str] = Counter()
        observations: list[dict[str, Any]] = []
        probability_audit_count = 0

        for fixture in fixtures:
            fixture_observations, fixture_exclusions, audit_count = self._fixture_observations(
                fixture,
                market_by_fixture.get(str(fixture.get("id") or ""), []),
                leakage_by_snapshot,
            )
            observations.extend(fixture_observations)
            exclusions.update(fixture_exclusions)
            probability_audit_count += audit_count

        observations.sort(key=_observation_sort_key)

        report = self._build_report(
            fixtures=fixtures,
            observations=observations,
            exclusions=exclusions,
            probability_audit_count=probability_audit_count,
            filters={
                "start_date": start_date,
                "end_date": end_date,
                "league_key": league_key,
                "limit": limit,
            },
        )
        fingerprint_payload = {
            **report,
            "provenance": {
                **report["provenance"],
                "dataset_fingerprint": None,
            },
        }
        report["provenance"]["dataset_fingerprint"] = _fingerprint(fingerprint_payload)
        return report

    def _fixtures(
        self,
        start_date: str | None,
        end_date: str | None,
        league_key: str | None,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "list_fixtures", None)
        if not callable(reader):
            return []
        rows = reader(
            start_date=start_date,
            end_date=end_date,
            league_key=league_key,
            limit=limit,
        )
        ordered = sorted(
            (dict(row) for row in rows if isinstance(row, Mapping)),
            key=lambda row: (str(row.get("kickoff") or ""), str(row.get("id") or "")),
        )
        if limit is None:
            return ordered
        bounded_limit = max(0, int(limit))
        return ordered[-bounded_limit:] if bounded_limit else []

    def _fixture_observations(
        self,
        fixture: Mapping[str, Any],
        market_snapshots: Iterable[Mapping[str, Any]],
        leakage_by_snapshot: Mapping[str, list[Mapping[str, Any]]],
    ) -> tuple[list[dict[str, Any]], Counter[str], int]:
        excluded: Counter[str] = Counter()
        fixture_id = str(fixture.get("id") or "")
        if not fixture_id:
            excluded["missing_fixture_id"] += 1
            return [], excluded, 0
        kickoff = parse_timestamp(fixture.get("kickoff"))
        if kickoff is None:
            excluded["missing_kickoff"] += 1
            return [], excluded, 0
        outcome = _actual_outcome(fixture)
        if outcome is None:
            excluded["missing_result"] += 1
            return [], excluded, 0

        audits = [
            _round5_audit_record(item)
            for item in market_snapshots
            if isinstance(item, Mapping)
        ]
        audits = [item for item in audits if item is not None]
        if not audits:
            excluded["missing_historical_probability_audit"] += 1
            return [], excluded, 0

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in audits:
            cutoff_raw = item["audit"].get("prediction_cutoff_at")
            parsed_cutoff = parse_timestamp(cutoff_raw)
            key = parsed_cutoff.isoformat() if parsed_cutoff else str(cutoff_raw or "")
            groups[key].append(item)

        observations: list[dict[str, Any]] = []
        for cutoff_key in sorted(groups):
            candidates = groups[cutoff_key]
            if not cutoff_key:
                excluded["missing_cutoff"] += 1
                continue
            if len(candidates) != 1:
                excluded["ambiguous_probability_revision"] += 1
                continue
            item = candidates[0]
            audit = item["audit"]
            if not item["market_snapshot_id"]:
                excluded["insufficient_provenance"] += 1
                continue
            cutoff = parse_timestamp(cutoff_key)
            if cutoff is None:
                excluded["missing_cutoff"] += 1
                continue
            if cutoff >= kickoff:
                excluded["post_kickoff_prediction"] += 1
                continue
            required_provenance = (
                audit.get("fixture_id") == fixture_id
                and audit.get("audit_version") == AUDIT_VERSION
                and bool(audit.get("probability_model_version"))
                and bool(audit.get("probability_calculation_version"))
                and (
                    str(audit.get("market_status") or "") == "MODEL_ONLY"
                    or bool(audit.get("market_prior_id"))
                )
                and audit.get("market_model_version")
                == self.market_config.market_model_version
                and audit.get("market_calculation_version")
                == self.market_config.calculation_version
                and item["market_snapshot_identity_valid"] is True
                and audit.get("no_ml") is True
                and audit.get("no_llm_numeric_probability") is True
                and audit.get("reproducible") is True
            )
            if not required_provenance:
                excluded["insufficient_provenance"] += 1
                continue

            feature_snapshot_id = str(audit.get("feature_snapshot_id") or "")
            feature_reader = getattr(self.repository, "feature_snapshot", None)
            feature_snapshot = (
                feature_reader(feature_snapshot_id)
                if feature_snapshot_id and callable(feature_reader)
                else None
            )
            if not isinstance(feature_snapshot, Mapping):
                excluded["missing_feature_snapshot"] += 1
                continue
            if str(feature_snapshot.get("fixture_id") or "") != fixture_id:
                excluded["insufficient_provenance"] += 1
                continue
            if parse_timestamp(feature_snapshot.get("prediction_cutoff_at")) != cutoff:
                excluded["insufficient_provenance"] += 1
                continue

            persisted_audit = self._sticky_leakage_audit(
                leakage_by_snapshot.get(feature_snapshot_id, []),
                cutoff,
            )
            if persisted_audit is None:
                excluded["leakage_unknown"] += 1
                continue
            if persisted_audit["status"] != "PASS":
                excluded[
                    "leakage_failed"
                    if persisted_audit["status"] == "FAIL"
                    else "leakage_unknown"
                ] += 1
                continue
            canonical = LeakageAuditService(self.repository).audit_feature_snapshot(
                feature_snapshot,
                persist=False,
            )
            if str(canonical.get("status") or "").upper() != "PASS":
                excluded["leakage_failed"] += 1
                continue

            odds_ok, odds_reason = self._validate_odds_provenance(audit, fixture_id, cutoff)
            if not odds_ok:
                excluded[odds_reason] += 1
                continue

            production_evidence, evidence_reason = self._production_evidence(
                item=item,
                fixture_id=fixture_id,
                kickoff=kickoff,
                cutoff=cutoff,
                feature_snapshot=feature_snapshot,
                leakage_audits=persisted_audit["audits"],
            )
            if production_evidence is None:
                excluded[evidence_reason] += 1
                continue

            layers, layer_exclusions = self._probability_layers(audit)
            excluded.update(layer_exclusions)
            observation = {
                "fixture_id": fixture_id,
                "kickoff_at": kickoff.isoformat(),
                "league": str(fixture.get("league_key") or "unknown"),
                "season": _season(fixture),
                "prediction_cutoff_at": cutoff.isoformat(),
                "cutoff_segment": self._cutoff_segment(kickoff, cutoff),
                "actual_outcome": outcome,
                "source_kind": SOURCE_KIND,
                "replayed_prediction": False,
                "replay_status": "not_replayed",
                "round6_replay_performed": False,
                "historical_production_prediction": True,
                "model_probability": layers["model"],
                "market_probability": layers["market"],
                "final_probability": layers["final"],
                "market_status": str(audit.get("market_status") or ""),
                "provenance": {
                    "market_snapshot_id": item["market_snapshot_id"],
                    "prediction_revision_id": production_evidence[
                        "prediction_revision_id"
                    ],
                    "persisted_at": production_evidence["persisted_at"],
                    "feature_snapshot_id": feature_snapshot_id,
                    "leakage_audit_ids": persisted_audit["audit_ids"],
                    "market_prior_id": audit.get("market_prior_id"),
                    "source_odds_snapshot_ids": list(
                        audit.get("source_odds_snapshot_ids") or []
                    ),
                    "probability_model_version": audit.get("probability_model_version"),
                    "probability_calculation_version": audit.get(
                        "probability_calculation_version"
                    ),
                    "market_model_version": audit.get("market_model_version"),
                    "market_calculation_version": audit.get(
                        "market_calculation_version"
                    ),
                    "fusion_version": audit.get("fusion_version"),
                    "fusion_config_hash": audit.get("fusion_config_hash"),
                },
            }
            observations.append(observation)
        return observations, excluded, len(audits)

    def _sticky_leakage_audit(
        self,
        relevant: Iterable[Mapping[str, Any]],
        cutoff: datetime,
    ) -> dict[str, Any] | None:
        relevant = list(relevant)
        if not relevant:
            return None
        statuses = {str(row.get("status") or "").upper() for row in relevant}
        matching_pass = any(
            str(row.get("status") or "").upper() == "PASS"
            and parse_timestamp(row.get("prediction_cutoff_at")) == cutoff
            for row in relevant
        )
        status = (
            "FAIL"
            if "FAIL" in statuses
            else "PASS"
            if statuses == {"PASS"} and matching_pass
            else "UNKNOWN"
        )
        return {
            "status": status,
            "audit_ids": sorted(
                str(row.get("audit_id")) for row in relevant if row.get("audit_id")
            ),
            "audits": relevant,
        }

    def _production_evidence(
        self,
        *,
        item: Mapping[str, Any],
        fixture_id: str,
        kickoff: datetime,
        cutoff: datetime,
        feature_snapshot: Mapping[str, Any],
        leakage_audits: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, Any] | None, str]:
        audit = item["audit"]
        required_fields = (
            audit.get("production_evidence_valid"),
            audit.get("evidence_kind"),
            audit.get("prediction_revision_id"),
            audit.get("prediction_id"),
            audit.get("prediction_revision_number"),
            audit.get("model_key"),
            audit.get("serving_model_version"),
            audit.get("persisted_at"),
            audit.get("kickoff_at"),
            audit.get("leakage_audit_id"),
            item.get("persisted_at"),
            item.get("prediction_revision_id"),
        )
        if any(value in (None, "") for value in required_fields):
            return None, "missing_production_evidence"
        if (
            audit.get("production_evidence_valid") is not True
            or str(audit.get("evidence_kind")) != PRODUCTION_EVIDENCE_KIND
            or _replay_flag(item, audit)
        ):
            return None, "invalid_production_evidence"

        persisted_at = parse_timestamp(item.get("persisted_at"))
        audit_persisted_at = parse_timestamp(audit.get("persisted_at"))
        if (
            persisted_at is None
            or audit_persisted_at != persisted_at
            or parse_timestamp(audit.get("kickoff_at")) != kickoff
            or persisted_at < cutoff
            or persisted_at >= kickoff
        ):
            return None, "invalid_production_evidence"

        revision_id = str(audit.get("prediction_revision_id"))
        if str(item.get("prediction_revision_id")) != revision_id:
            return None, "prediction_revision_mismatch"
        prediction_id, separator, revision_number_raw = revision_id.rpartition(":")
        try:
            revision_number = int(revision_number_raw)
        except (TypeError, ValueError):
            return None, "invalid_prediction_revision"
        if not separator or not prediction_id or revision_number < 1:
            return None, "invalid_prediction_revision"

        revision_reader = getattr(self.repository, "prediction_revision", None)
        revision = (
            revision_reader(prediction_id, revision_number)
            if callable(revision_reader)
            else None
        )
        if not isinstance(revision, Mapping):
            return None, "missing_prediction_revision"
        revision_identity_matches = (
            str(revision.get("prediction_id") or "") == prediction_id
            and revision.get("revision_number") == revision_number
            and str(revision.get("fixture_id") or "") == fixture_id
            and parse_timestamp(revision.get("prediction_cutoff_at")) == cutoff
            and str(revision.get("feature_snapshot_id") or "")
            == str(audit.get("feature_snapshot_id") or "")
            and str(audit.get("prediction_id") or "") == prediction_id
            and audit.get("prediction_revision_number") == revision_number
            and str(audit.get("model_key") or "")
            == str(revision.get("model_key") or "")
            and str(audit.get("serving_model_version") or "")
            == str(revision.get("model_version") or "")
        )
        if not revision_identity_matches:
            return None, "prediction_revision_mismatch"
        model_probability = audit.get("model_probability")
        try:
            revision_probability = {
                "home": float(revision["probability_home"]),
                "draw": float(revision["probability_draw"]),
                "away": float(revision["probability_away"]),
            }
            audited_probability = {
                outcome: float(model_probability[outcome])
                for outcome in ("home", "draw", "away")
            }
        except (KeyError, TypeError, ValueError):
            return None, "prediction_revision_mismatch"
        probability_contract_matches = (
            all(
                math.isfinite(revision_probability[outcome])
                and math.isfinite(audited_probability[outcome])
                and math.isclose(
                    revision_probability[outcome],
                    audited_probability[outcome],
                    abs_tol=1e-9,
                )
                for outcome in ("home", "draw", "away")
            )
            and str(revision.get("probability_model_version") or "")
            == str(audit.get("probability_model_version") or "")
            and str(revision.get("probability_calculation_version") or "")
            == str(audit.get("probability_calculation_version") or "")
        )
        if not probability_contract_matches:
            return None, "prediction_revision_mismatch"

        leakage_audit_id = str(audit.get("leakage_audit_id") or "")
        leakage_audit = next(
            (
                row
                for row in leakage_audits
                if str(row.get("audit_id") or "") == leakage_audit_id
            ),
            None,
        )
        if leakage_audit is None:
            return None, "missing_leakage_audit"
        if str(leakage_audit.get("prediction_id") or "") != prediction_id:
            return None, "prediction_revision_mismatch"

        source_ids = [str(value) for value in audit.get("source_odds_snapshot_ids") or []]
        odds_reader = getattr(self.repository, "odds_snapshot", None)
        odds_snapshots = [
            snapshot
            for snapshot_id in source_ids
            if callable(odds_reader)
            and isinstance((snapshot := odds_reader(snapshot_id)), Mapping)
        ]
        try:
            normalized = validate_production_evidence(
                {**dict(item), "audit": audit},
                feature_snapshot=feature_snapshot,
                odds_snapshots=odds_snapshots,
                leakage_audit=leakage_audit,
                replay=_replay_flag(item, audit),
            )
        except (ProductionEvidenceError, TypeError, ValueError):
            return None, "invalid_production_evidence"
        return normalized, ""

    def _validate_odds_provenance(
        self,
        audit: Mapping[str, Any],
        fixture_id: str,
        cutoff: datetime,
    ) -> tuple[bool, str]:
        source_ids = [str(value) for value in audit.get("source_odds_snapshot_ids") or []]
        market_probability = audit.get("market_probability")
        market_status = str(audit.get("market_status") or "")
        if market_probability is None and market_status == "MODEL_ONLY":
            return (not source_ids, "insufficient_odds_provenance")
        if not source_ids:
            return False, "insufficient_odds_provenance"
        reader = getattr(self.repository, "odds_snapshot", None)
        if not callable(reader):
            return False, "missing_odds_snapshot"
        for snapshot_id in source_ids:
            snapshot = reader(snapshot_id)
            if not isinstance(snapshot, Mapping):
                return False, "missing_odds_snapshot"
            if str(snapshot.get("fixture_id") or "") != fixture_id:
                return False, "insufficient_odds_provenance"
            captured_at = parse_timestamp(snapshot.get("captured_at"))
            source_updated_at = parse_timestamp(snapshot.get("source_updated_at"))
            if captured_at is None or captured_at > cutoff:
                return False, "odds_after_prediction_cutoff"
            if snapshot.get("source_updated_at") not in (None, "") and (
                source_updated_at is None or source_updated_at > cutoff
            ):
                return False, "odds_after_prediction_cutoff"
        return True, ""

    def _probability_layers(
        self,
        audit: Mapping[str, Any],
    ) -> tuple[dict[str, dict[str, float] | None], Counter[str]]:
        excluded: Counter[str] = Counter()
        raw = {
            "model": audit.get("model_probability"),
            "market": audit.get("market_probability"),
            "final": audit.get("final_probability"),
        }
        layers: dict[str, dict[str, float] | None] = {}
        for layer, value in raw.items():
            if value is None:
                layers[layer] = None
                excluded[f"missing_{layer}_probability"] += 1
                continue
            try:
                layers[layer] = self.evaluator.normalize(value)
            except ValueError:
                layers[layer] = None
                excluded[f"invalid_{layer}_probability"] += 1

        market_status = str(audit.get("market_status") or "")
        fusion_count = audit.get("market_fusion_count")
        if market_status == "MODEL_PLUS_MARKET":
            weights = audit.get("fusion_weights") or {}
            frozen = (
                fusion_count == 1
                and audit.get("market_fusion_applied") is True
                and _close(weights.get("model"), self.market_config.model_weight)
                and _close(weights.get("market"), self.market_config.market_weight)
                and audit.get("fusion_version") == self.market_config.fusion_version
                and audit.get("fusion_config_hash") == self.market_config.config_hash
            )
            expected = None
            if layers.get("model") and layers.get("market"):
                expected = {
                    outcome: (
                        self.market_config.model_weight * layers["model"][outcome]
                        + self.market_config.market_weight * layers["market"][outcome]
                    )
                    for outcome in ("home", "draw", "away")
                }
            if not frozen or not expected or not layers.get("final") or any(
                not math.isclose(
                    expected[outcome],
                    layers["final"][outcome],
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                for outcome in expected
            ):
                if layers.get("final") is not None:
                    excluded["invalid_frozen_fusion"] += 1
                layers["final"] = None
        elif market_status == "MODEL_ONLY":
            if audit.get("market_fusion_applied") is not False or fusion_count != 0:
                if layers.get("final") is not None:
                    excluded["invalid_frozen_fusion"] += 1
                layers["final"] = None
            elif layers.get("model") and layers.get("final") and any(
                not math.isclose(
                    layers["model"][outcome],
                    layers["final"][outcome],
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                for outcome in layers["model"]
            ):
                excluded["invalid_frozen_fusion"] += 1
                layers["final"] = None
        else:
            if layers.get("final") is not None:
                excluded["invalid_frozen_fusion"] += 1
            layers["final"] = None
        return layers, excluded

    def _cutoff_segment(self, kickoff: datetime, cutoff: datetime) -> str:
        lead_hours = (kickoff - cutoff).total_seconds() / 3600
        for offset in sorted(self.cutoff_offsets_hours):
            if lead_hours <= offset:
                return _offset_label(offset)
        return "other"

    def _build_report(
        self,
        *,
        fixtures: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        exclusions: Counter[str],
        probability_audit_count: int,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        layer_rows = {
            layer: [
                (row[f"{layer}_probability"], row["actual_outcome"])
                for row in observations
                if row[f"{layer}_probability"] is not None
            ]
            for layer in LAYERS
        }
        metrics = {
            layer: self.evaluator.summarize(rows)
            for layer, rows in layer_rows.items()
        }
        denominator = len(observations)
        coverage = {
            layer: _coverage(len(rows), denominator)
            for layer, rows in layer_rows.items()
        }
        candidate_period_values = [
            kickoff.isoformat()
            for fixture in fixtures
            if _actual_outcome(fixture) is not None
            and (kickoff := parse_timestamp(fixture.get("kickoff"))) is not None
        ]
        evaluated_rows = [
            row
            for row in observations
            if any(row[f"{layer}_probability"] is not None for layer in LAYERS)
        ]
        evaluation_period_values = [row["kickoff_at"] for row in evaluated_rows]
        eligible_fixture_ids = {row["fixture_id"] for row in observations}
        evaluated_fixture_ids = {row["fixture_id"] for row in evaluated_rows}
        largest_layer_sample = max((len(rows) for rows in layer_rows.values()), default=0)
        report = {
            "status": (
                "ok" if largest_layer_sample >= self.min_samples else "insufficient_data"
            ),
            "backtest_version": BACKTEST_VERSION,
            "metrics_version": METRICS_VERSION,
            "evaluation_period": {
                "from": min(evaluation_period_values) if evaluation_period_values else None,
                "to": max(evaluation_period_values) if evaluation_period_values else None,
            },
            "candidate_period": {
                "from": min(candidate_period_values) if candidate_period_values else None,
                "to": max(candidate_period_values) if candidate_period_values else None,
            },
            "fixtures": {
                "discovered": len(fixtures),
                "eligible": len(eligible_fixture_ids),
                "evaluated": len(evaluated_fixture_ids),
                "excluded": max(0, len(fixtures) - len(eligible_fixture_ids)),
            },
            "probability_audit_count": probability_audit_count,
            "observation_count": len(observations),
            "evaluated_observation_count": len(evaluated_rows),
            "model": metrics["model"],
            "market": metrics["market"],
            "final": metrics["final"],
            "coverage": coverage,
            "calibration": {
                layer: metrics[layer]["calibration"] for layer in LAYERS
            },
            "segments": self._segments(observations),
            "exclusion_reasons": dict(sorted(exclusions.items())),
            "observations": observations,
            "filters": filters,
            "provenance": {
                "dataset_fingerprint": None,
                "evaluation_unit": EVALUATION_UNIT,
                "source_kind": SOURCE_KIND,
                "round6_replay_count": 0,
                "source_replay_status": "not_replayed",
                "frozen_weights": {
                    "model": self.market_config.model_weight,
                    "market": self.market_config.market_weight,
                },
                "fusion_version": self.market_config.fusion_version,
                "fusion_config_hash": self.market_config.config_hash,
                "minimum_display_samples": self.min_samples,
                "cutoff_offsets_hours": list(self.cutoff_offsets_hours),
                "generated_at": None,
            },
        }
        return report

    def _segments(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        cutoff_labels = [_offset_label(value) for value in self.cutoff_offsets_hours]
        cutoff_labels.append("other")
        cutoff = {
            label: self._segment_report(
                [row for row in observations if row["cutoff_segment"] == label]
            )
            for label in cutoff_labels
        }
        availability = {
            "model_only": self._segment_report(
                [row for row in observations if row["market_status"] == "MODEL_ONLY"]
            ),
            "model_plus_market": self._segment_report(
                [
                    row
                    for row in observations
                    if row["market_status"] == "MODEL_PLUS_MARKET"
                ]
            ),
            "model_available": self._segment_report(
                [row for row in observations if row["model_probability"] is not None]
            ),
            "market_available": self._segment_report(
                [row for row in observations if row["market_probability"] is not None]
            ),
            "final_available": self._segment_report(
                [row for row in observations if row["final_probability"] is not None]
            ),
        }
        return {
            "overall": self._segment_report(observations),
            "cutoff": cutoff,
            "availability": availability,
            "league": {
                key: self._segment_report(
                    [row for row in observations if row["league"] == key]
                )
                for key in sorted({row["league"] for row in observations})
            },
            "season": {
                key: self._segment_report(
                    [row for row in observations if row["season"] == key]
                )
                for key in sorted({row["season"] for row in observations})
            },
        }

    def _segment_report(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sample_count": len(rows),
            "status": "ok" if len(rows) >= self.min_samples else "insufficient_data",
        }
        for layer in LAYERS:
            values = [
                (row[f"{layer}_probability"], row["actual_outcome"])
                for row in rows
                if row[f"{layer}_probability"] is not None
            ]
            result[layer] = self.evaluator.summarize(values)
        return result


def build_round6_backtest_run(report: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap one deterministic report for the existing immutable run store."""

    fingerprint = str((report.get("provenance") or {}).get("dataset_fingerprint") or "")
    if not fingerprint:
        raise ValueError("Round 6 dataset fingerprint is required")
    run_id = f"round6:{fingerprint.removeprefix('sha256:')}"
    period = report.get("evaluation_period") or {}
    candidate_period = report.get("candidate_period") or {}
    logical_time = (
        period.get("to")
        or period.get("from")
        or candidate_period.get("to")
        or candidate_period.get("from")
        or "1970-01-01T00:00:00+00:00"
    )
    return {
        "run_id": run_id,
        "name": "round6-temporal-probability-evaluation",
        "started_at": logical_time,
        "finished_at": logical_time,
        "dataset_version": fingerprint,
        "config": {
            "backtest_version": report.get("backtest_version"),
            "metrics_version": report.get("metrics_version"),
            "filters": report.get("filters") or {},
            "source_kind": SOURCE_KIND,
        },
        "code_version": BACKTEST_VERSION,
        "model_version": None,
        "feature_version": "round3-feature-engine-v2",
        "ensemble_version": None,
        "calibration_version": "descriptive-only",
        "status": report.get("status") or "insufficient_data",
        "payload": dict(report),
    }


def _round5_audit_record(item: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = item.get("payload")
    if not isinstance(payload, Mapping) or payload.get("snapshot_type") != "round5_probability_audit":
        return None
    audit = payload.get("audit")
    if not isinstance(audit, Mapping):
        return None
    outer_snapshot_id = str(item.get("market_snapshot_id") or "")
    inner_snapshot_id = str(audit.get("market_snapshot_id") or "")
    return {
        "market_snapshot_id": outer_snapshot_id,
        "market_snapshot_identity_valid": bool(
            outer_snapshot_id and inner_snapshot_id == outer_snapshot_id
        ),
        "prediction_revision_id": item.get("prediction_revision_id"),
        "persisted_at": item.get("persisted_at"),
        "replayed_prediction": bool(
            item.get("replayed_prediction")
            or payload.get("replayed_prediction")
            or audit.get("replayed_prediction")
        ),
        "is_historical_replay": bool(
            item.get("is_historical_replay")
            or payload.get("is_historical_replay")
            or audit.get("is_historical_replay")
        ),
        "audit": dict(audit),
    }


def _replay_flag(item: Mapping[str, Any], audit: Mapping[str, Any]) -> bool:
    return bool(
        item.get("replayed_prediction")
        or item.get("is_historical_replay")
        or audit.get("replayed_prediction")
        or audit.get("is_historical_replay")
    )


def _actual_outcome(fixture: Mapping[str, Any]) -> str | None:
    if str(fixture.get("status") or "").casefold() != "finished":
        return None
    score = fixture.get("score")
    if not isinstance(score, Mapping):
        return None
    home = _finite_score(score.get("home"))
    away = _finite_score(score.get("away"))
    if home is None or away is None:
        return None
    return "home" if home > away else "draw" if home == away else "away"


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _season(fixture: Mapping[str, Any]) -> str:
    season = fixture.get("season")
    if isinstance(season, Mapping):
        return str(season.get("name") or season.get("year") or "unknown")
    return str(season or "unknown")


def _offset_label(value: float) -> str:
    minutes = round(value * 60)
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h"


def _observation_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    provenance = row.get("provenance") or {}
    return (
        str(row.get("kickoff_at") or ""),
        str(row.get("prediction_cutoff_at") or ""),
        str(row.get("fixture_id") or ""),
        str(provenance.get("market_snapshot_id") or ""),
    )


def _coverage(available: int, eligible: int) -> dict[str, Any]:
    return {
        "available": available,
        "eligible": eligible,
        "rate": available / eligible if eligible else None,
    }


def _close(value: Any, expected: float) -> bool:
    try:
        return math.isclose(float(value), expected, rel_tol=0.0, abs_tol=1e-12)
    except (TypeError, ValueError):
        return False


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
