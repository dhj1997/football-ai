"""Strict no-ML, point-in-time Feature Engine v2."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .elo import compute_elo_feature_state
from .feature_registry import FeatureRegistry, builtin_feature_definitions
from .prediction_intelligence import parse_timestamp
from .recent_form import result_available_at, source_metric_pair
from .no_ml_guard import assert_v2_numeric_path_allowed


FEATURE_ENGINE_VERSION = "round3-feature-engine-v2"
SUPPORTED_RESULT_STATUSES = frozenset({"finished", "ft", "aet", "pen"})
MISSING_SOURCE_ID = "feature-engine-source"


class FeatureEngineError(ValueError):
    """Raised when a v2 feature snapshot cannot be safely constructed."""


@dataclass(frozen=True)
class FeatureResult:
    feature_name: str
    value: Any
    value_type: str
    entity_type: str
    entity_id: str
    available_at: str | None
    source: str
    source_record_ids: tuple[str, ...]
    quality_score: float
    calculation_version: str
    prediction_cutoff_at: str
    status: str = "available"
    missing_reason: str | None = None
    feature_group: str | None = None
    side: str | None = None
    registry_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_record_ids"] = list(self.source_record_ids)
        value["feature_value"] = value.pop("value")
        value["source_record_id"] = self.source_record_ids[0] if self.source_record_ids else MISSING_SOURCE_ID
        value["feature_version"] = FEATURE_ENGINE_VERSION
        value["computed_at"] = self.prediction_cutoff_at
        return value


class BaseFeatureCalculator:
    """Common interface for deterministic, cutoff-aware calculators."""

    calculation_version = FEATURE_ENGINE_VERSION

    def __init__(self, engine: "FeatureEngine") -> None:
        self.engine = engine

    def calculate(self, entity_id: str, prediction_cutoff_at: Any) -> Sequence[FeatureResult]:
        raise NotImplementedError


class FeatureEngine:
    """Build one immutable feature snapshot from cutoff-safe fixture evidence."""

    def __init__(self, repository: Any, *, registry: FeatureRegistry | None = None) -> None:
        self.repository = repository
        self.registry = registry or FeatureRegistry(repository)

    @staticmethod
    def assert_numeric_path_allowed(payload: Mapping[str, Any], *, source: str | None = None) -> None:
        """Expose the v2 production deny gate at the engine boundary."""

        assert_v2_numeric_path_allowed(payload, source=source)

    def calculate(
        self,
        entity_id: str,
        prediction_cutoff_at: Any,
        *,
        fixture: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        standings: Mapping[str, Any] | None = None,
    ) -> Sequence[FeatureResult]:
        """Calculate team features for one side or both fixture teams."""

        cutoff = _cutoff(prediction_cutoff_at)
        fixture = fixture or {}
        evidence = evidence or {}
        home_id = _team_id(fixture.get("home_team"))
        away_id = _team_id(fixture.get("away_team"))
        team_ids = [entity_id] if entity_id else [value for value in (home_id, away_id) if value]
        return self._calculate_for_fixture(cutoff, fixture, evidence, standings, team_ids)

    def calculate_snapshot(
        self,
        fixture: Mapping[str, Any],
        evidence: Mapping[str, Any],
        prediction_cutoff_at: Any,
        *,
        standings: Mapping[str, Any] | None = None,
        evidence_snapshot_id: str | None = None,
        odds_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        cutoff = _cutoff(prediction_cutoff_at)
        self.assert_numeric_path_allowed(evidence, source=str(evidence.get("source") or ""))
        fixture_id = str(fixture.get("canonical_fixture_id") or fixture.get("id") or "")
        if not fixture_id:
            raise FeatureEngineError("fixture id is required")
        home_id = _team_id(fixture.get("home_team"))
        away_id = _team_id(fixture.get("away_team"))
        features = list(
            self._calculate_for_fixture(
                cutoff,
                fixture,
                evidence,
                standings,
                [value for value in (home_id, away_id) if value],
            )
        )
        serialized = []
        for result in features:
            row = asdict(result)
            row["source_record_ids"] = list(result.source_record_ids)
            row["feature_value"] = row.pop("value")
            row["source_record_id"] = result.source_record_ids[0] if result.source_record_ids else MISSING_SOURCE_ID
            row["feature_version"] = FEATURE_ENGINE_VERSION
            row["computed_at"] = cutoff.isoformat()
            row["prediction_cutoff_at"] = cutoff.isoformat()
            row["snapshot_id"] = None
            serialized.append(row)
        serialized.sort(
            key=lambda item: (
                str(item.get("entity_id") or ""),
                str(item.get("feature_name") or ""),
                str(item.get("side") or ""),
            )
        )
        identity = {
            "fixture_id": fixture_id,
            "canonical_fixture_id": str(fixture.get("canonical_fixture_id") or fixture_id),
            "prediction_cutoff_at": cutoff.isoformat(),
            "feature_version": FEATURE_ENGINE_VERSION,
            "evidence_snapshot_id": evidence_snapshot_id,
            "odds_snapshot_id": odds_snapshot_id,
            "features": [
                {
                    key: row.get(key)
                    for key in (
                        "feature_name", "feature_value", "value_type", "entity_type", "entity_id",
                        "available_at", "source", "source_record_ids", "quality_score",
                        "calculation_version", "status", "missing_reason", "side", "registry_id",
                    )
                }
                for row in serialized
            ],
        }
        encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        snapshot_id = f"feature:{hashlib.sha256(encoded).hexdigest()}"
        for row in serialized:
            row["snapshot_id"] = snapshot_id
        violations = [
            {
                "feature_name": row["feature_name"],
                "available_at": row.get("available_at"),
                "prediction_cutoff_at": cutoff.isoformat(),
                "reason": "available_after_prediction_cutoff",
            }
            for row in serialized
            if row.get("status") == "future"
        ]
        source_captured = _max_time(
            evidence.get("captured_at"), evidence.get("synced_at"),
            *(row.get("available_at") for row in serialized),
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in serialized:
            grouped.setdefault(str(row.get("feature_group") or "unknown"), []).append(row)
        quality_scores = [float(row["quality_score"]) for row in serialized]
        snapshot = {
            "snapshot_id": snapshot_id,
            "feature_snapshot_id": snapshot_id,
            "fixture_id": str(fixture.get("id") or fixture_id),
            "canonical_fixture_id": str(fixture.get("canonical_fixture_id") or fixture_id),
            "competition": _league(fixture),
            "season": _season(fixture, _league(fixture)),
            "prediction_timestamp": cutoff.isoformat(),
            "prediction_cutoff_at": cutoff.isoformat(),
            "computed_at": datetime.now(UTC).isoformat(),
            "source_captured_at": source_captured.isoformat() if source_captured else None,
            "feature_version": FEATURE_ENGINE_VERSION,
            "dataset_version": evidence.get("dataset_version"),
            "evidence_snapshot_id": evidence_snapshot_id,
            "odds_snapshot_id": odds_snapshot_id,
            "features": serialized,
            "feature_groups": grouped,
            "quality_payload": {
                "features_total": len(serialized),
                "features_available": sum(row.get("status") in {"available", "insufficient_sample"} for row in serialized),
                "features_missing": sum(row.get("status") == "missing" for row in serialized),
                "features_failed": sum(row.get("status") in {"future", "calculation_failed", "unverifiable"} for row in serialized),
                "overall_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.0,
            },
            "leakage_detected": bool(violations),
            "leakage_check": {
                "passed": not violations,
                "rejected_future_fields": [item["feature_name"] for item in violations],
                "violations": violations,
                "warnings": [],
            },
        }
        return snapshot

    def _calculate_for_fixture(
        self,
        cutoff: datetime,
        fixture: Mapping[str, Any],
        evidence: Mapping[str, Any],
        standings: Mapping[str, Any] | None,
        team_ids: Sequence[str],
    ) -> list[FeatureResult]:
        rows = self._fixtures()
        league = _league(fixture)
        season = _season(fixture, league)
        histories = {
            team_id: _eligible_team_rows(team_id, rows, cutoff, league=league, season=season)
            for team_id in team_ids
        }
        competition_team_ids = sorted(
            {
                team_id
                for row in rows
                if (not league or _league(row) == league)
                and (not season or _season(row, _league(row)) == season)
                for team in (row.get("home_team"), row.get("away_team"))
                if (team_id := _team_id(team))
            }
        )
        competition_history = [
            history_row
            for competition_team_id in competition_team_ids
            for history_row in _eligible_team_rows(
                competition_team_id,
                rows,
                cutoff,
                league=league,
                season=season,
            )
        ]
        fatigue_histories = {
            team_id: _eligible_team_rows(team_id, rows, cutoff)
            for team_id in team_ids
        }
        elo_state = compute_elo_feature_state(rows, as_of=cutoff, league=league)
        results: list[FeatureResult] = []
        for team_id in team_ids:
            side = "home" if team_id == _team_id(fixture.get("home_team")) else "away"
            history = histories[team_id]
            results.extend(self._elo(team_id, side, elo_state, cutoff))
            results.extend(self._form(team_id, side, history, cutoff))
            results.extend(self._goals(team_id, side, history, cutoff))
            results.extend(self._xg(team_id, side, history, cutoff))
            results.extend(self._home_away(team_id, side, history, cutoff))
            results.extend(self._strength(team_id, side, history, competition_history, elo_state, cutoff))
            results.extend(self._fatigue(team_id, side, fatigue_histories[team_id], cutoff))
            results.append(self._player_impact(team_id, side, evidence, cutoff))
        return results

    def _elo(self, team_id: str, side: str, state: Mapping[str, Any], cutoff: datetime) -> list[FeatureResult]:
        row = (state.get("teams") or {}).get(team_id)
        common = {"entity_id": team_id, "side": side, "source": "completed_match_results", "calculation_version": "elo-feature-v1", "feature_group": "elo"}
        if not row:
            return [
                self._result("team_elo", None, common, cutoff, missing_reason="no_prior_finished_matches"),
                self._result(f"{side}_elo", None, common, cutoff, missing_reason="no_prior_finished_matches"),
            ]
        return [
            self._result("team_elo", row["team_elo"], common, cutoff, source_ids=row.get("source_record_ids"), available_at=row.get("available_at")),
            self._result(f"{side}_elo", row[f"{side}_elo"], common, cutoff, source_ids=row.get("source_record_ids"), available_at=row.get("available_at")),
        ]

    def _form(self, team_id: str, side: str, history: list[dict[str, Any]], cutoff: datetime) -> list[FeatureResult]:
        results: list[FeatureResult] = []
        for window in (3, 5, 8, 10):
            selected = history[:window]
            source_ids = _source_ids(selected)
            available = _max_time(*(row.get("available_at") for row in selected))
            sample_status = "missing" if not selected else "available" if len(selected) >= window else "insufficient_sample"
            if not selected:
                for metric in ("points", "win_rate", "draw_rate", "loss_rate", "goals_for", "goals_against"):
                    results.append(self._result(f"{metric}_last_{window}", None, {"entity_id": team_id, "side": side, "source": "completed_match_results", "calculation_version": "form-feature-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=available, missing_reason="no_prior_finished_matches", status="missing"))
                for metric in ("xpoints_delta", "performance_vs_expectation"):
                    results.append(self._result(f"{metric}_last_{window}", None, {"entity_id": team_id, "side": side, "source": "provider_source_xpoints", "calculation_version": "performance-expectation-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=available, missing_reason="no_prior_finished_matches", status="missing", value_type="string" if metric.startswith("performance") else "number"))
                continue
            wins = sum(row["result"] == "W" for row in selected)
            draws = sum(row["result"] == "D" for row in selected)
            losses = len(selected) - wins - draws
            goals_for = sum(int(row.get("goals_for") or 0) for row in selected)
            goals_against = sum(int(row.get("goals_against") or 0) for row in selected)
            values = {
                "points": wins * 3 + draws,
                "win_rate": wins / len(selected),
                "draw_rate": draws / len(selected),
                "loss_rate": losses / len(selected),
                "goals_for": goals_for,
                "goals_against": goals_against,
            }
            for metric, value in values.items():
                results.append(self._result(f"{metric}_last_{window}", value, {"entity_id": team_id, "side": side, "source": "completed_match_results", "calculation_version": "form-feature-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=available, status=sample_status))
            xpoints = _series(selected, "xpoints", cutoff)
            if xpoints["future"]:
                results.append(self._result(f"xpoints_delta_last_{window}", None, {"entity_id": team_id, "side": side, "source": "provider_source_xpoints", "calculation_version": "performance-expectation-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=xpoints["future_at"], status="future", missing_reason="xpoints_available_after_cutoff"))
                results.append(self._result(f"performance_vs_expectation_last_{window}", None, {"entity_id": team_id, "side": side, "source": "provider_source_xpoints", "calculation_version": "performance-expectation-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=xpoints["future_at"], status="future", missing_reason="xpoints_available_after_cutoff", value_type="string"))
            elif len(xpoints["values"]) != len(selected):
                for name in (f"xpoints_delta_last_{window}", f"performance_vs_expectation_last_{window}"):
                    results.append(self._result(name, None, {"entity_id": team_id, "side": side, "source": "provider_source_xpoints", "calculation_version": "performance-expectation-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=None, status="missing", missing_reason="source_xpoints_unavailable", value_type="string" if name.startswith("performance") else "number"))
            else:
                delta = values["points"] - sum(xpoints["values"])
                label = "positive_overperformance" if delta > 0.5 else "negative_overperformance" if delta < -0.5 else "as_expected"
                results.append(self._result(f"xpoints_delta_last_{window}", round(delta, 6), {"entity_id": team_id, "side": side, "source": "provider_source_xpoints", "calculation_version": "performance-expectation-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=xpoints["available_at"], status=sample_status))
                results.append(self._result(f"performance_vs_expectation_last_{window}", label, {"entity_id": team_id, "side": side, "source": "provider_source_xpoints", "calculation_version": "performance-expectation-v1", "feature_group": "form"}, cutoff, source_ids=source_ids, available_at=xpoints["available_at"], status=sample_status, value_type="string"))
        return results

    def _goals(self, team_id: str, side: str, history: list[dict[str, Any]], cutoff: datetime) -> list[FeatureResult]:
        selected = history[:5]
        ids = _source_ids(selected)
        common = {"entity_id": team_id, "side": side, "source": "completed_match_results", "calculation_version": "goal-form-v1", "feature_group": "attack"}
        available = _max_time(*(row.get("available_at") for row in selected))
        if not selected:
            return [self._result(name, None, common, cutoff, source_ids=ids, available_at=available, status="missing", missing_reason="no_prior_finished_matches") for name in ("goals_for_last5", "goals_against_last5", "goal_difference_last5")]
        goals_for = sum(int(row.get("goals_for") or 0) for row in selected)
        goals_against = sum(int(row.get("goals_against") or 0) for row in selected)
        return [
            self._result("goals_for_last5", goals_for, common, cutoff, source_ids=ids, available_at=available, status="available" if len(selected) >= 5 else "insufficient_sample"),
            self._result("goals_against_last5", goals_against, {**common, "feature_group": "defense"}, cutoff, source_ids=ids, available_at=available, status="available" if len(selected) >= 5 else "insufficient_sample"),
            self._result("goal_difference_last5", goals_for - goals_against, {**common, "feature_group": "strength"}, cutoff, source_ids=ids, available_at=available, status="available" if len(selected) >= 5 else "insufficient_sample"),
        ]

    def _xg(self, team_id: str, side: str, history: list[dict[str, Any]], cutoff: datetime) -> list[FeatureResult]:
        results: list[FeatureResult] = []
        for window in (3, 5, 8):
            selected = history[:window]
            for metric, name in (("xg_for", f"rolling_xg_{window}"), ("xg_against", f"rolling_xga_{window}")):
                series = _metric_series(selected, metric, cutoff)
                common = {"entity_id": team_id, "side": side, "source": "provider_real_xg", "calculation_version": "xg-rolling-v1", "feature_group": "xg"}
                if not selected:
                    results.append(self._result(name, None, common, cutoff, source_ids=(), status="missing", missing_reason="no_prior_finished_matches"))
                elif series["future"]:
                    results.append(self._result(name, None, common, cutoff, source_ids=_source_ids(selected), available_at=series["future_at"], status="future", missing_reason="xg_available_after_cutoff"))
                elif len(series["values"]) != len(selected):
                    results.append(self._result(name, None, common, cutoff, source_ids=_source_ids(selected), available_at=None, status="missing", missing_reason="source_xg_unavailable"))
                else:
                    results.append(self._result(name, sum(series["values"]) / len(series["values"]), common, cutoff, source_ids=_source_ids(selected), available_at=series["available_at"], status="available" if len(selected) >= window else "insufficient_sample"))
        return results

    def _home_away(self, team_id: str, side: str, history: list[dict[str, Any]], cutoff: datetime) -> list[FeatureResult]:
        split = [row for row in history if row.get("team_is_home") == (side == "home")]
        prefix = "home" if side == "home" else "away"
        common = {"entity_id": team_id, "side": side, "source": "completed_match_results", "calculation_version": "home-away-v1", "feature_group": "home_away"}
        ids = _source_ids(split)
        available = _max_time(*(row.get("available_at") for row in split))
        if not split:
            return [self._result(f"{prefix}_{metric}", None, common, cutoff, source_ids=ids, available_at=available, status="missing", missing_reason="no_prior_split_matches") for metric in ("win_rate", "xg", "xga", "goals_for", "goals_against")]
        wins = sum(row["result"] == "W" for row in split)
        results = [self._result(f"{prefix}_win_rate", wins / len(split), common, cutoff, source_ids=ids, available_at=available, status="available")]
        for metric, source_metric in (("xg", "xg_for"), ("xga", "xg_against")):
            series = _metric_series(split, source_metric, cutoff)
            if series["future"]:
                results.append(self._result(f"{prefix}_{metric}", None, {**common, "source": "provider_real_xg"}, cutoff, source_ids=ids, available_at=series["future_at"], status="future", missing_reason="xg_available_after_cutoff"))
            else:
                complete = len(series["values"]) == len(split)
                results.append(self._result(f"{prefix}_{metric}", sum(series["values"]) / len(series["values"]) if complete else None, {**common, "source": "provider_real_xg"}, cutoff, source_ids=ids, available_at=series["available_at"], status="available" if complete else "missing", missing_reason=None if complete else "source_xg_unavailable"))
        results.extend(
            self._result(f"{prefix}_{metric}", sum(float(row[metric]) for row in split) / len(split), common, cutoff, source_ids=ids, available_at=available, status="available")
            for metric in ("goals_for", "goals_against")
        )
        return results

    def _strength(self, team_id: str, side: str, history: list[dict[str, Any]], competition_history: list[dict[str, Any]], elo_state: Mapping[str, Any], cutoff: datetime) -> list[FeatureResult]:
        common = {"entity_id": team_id, "side": side, "source": "real_xg_or_goals_or_shots", "calculation_version": "strength-feature-v1", "feature_group": "attack"}
        ids = _source_ids(history)
        if not history:
            return [self._result("attack_strength", None, common, cutoff, source_ids=ids, status="missing", missing_reason="no_prior_finished_matches"), self._result("defense_strength", None, {**common, "feature_group": "defense"}, cutoff, source_ids=ids, status="missing", missing_reason="no_prior_finished_matches")]
        attack, attack_source = _primary_rate(history, "for")
        defense_against, defense_source = _primary_rate(history, "against")
        baseline_attack, _ = _primary_rate(competition_history, "for")
        baseline_defense, _ = _primary_rate(competition_history, "against")
        factor = _opponent_factor(history, elo_state)
        if attack is None or baseline_attack in (None, 0):
            attack_result = self._result("attack_strength", None, {**common, "source": attack_source or common["source"]}, cutoff, source_ids=ids, available_at=_max_time(*(row.get("available_at") for row in history)), status="missing", missing_reason="primary_strength_source_unavailable")
        else:
            attack_result = self._result("attack_strength", attack / baseline_attack * factor, {**common, "source": attack_source or common["source"]}, cutoff, source_ids=ids, available_at=_max_time(*(row.get("available_at") for row in history)), status="available")
        if defense_against is None or baseline_defense in (None, 0):
            defense_result = self._result("defense_strength", None, {**common, "feature_group": "defense", "source": defense_source or common["source"]}, cutoff, source_ids=ids, available_at=_max_time(*(row.get("available_at") for row in history)), status="missing", missing_reason="primary_strength_source_unavailable")
        else:
            defense_result = self._result("defense_strength", baseline_defense / max(defense_against, 1e-9) * factor, {**common, "feature_group": "defense", "source": defense_source or common["source"]}, cutoff, source_ids=ids, available_at=_max_time(*(row.get("available_at") for row in history)), status="available")
        return [attack_result, defense_result]

    def _fatigue(self, team_id: str, side: str, history: list[dict[str, Any]], cutoff: datetime) -> list[FeatureResult]:
        common = {"entity_id": team_id, "side": side, "source": "completed_match_results", "calculation_version": "fatigue-v1", "feature_group": "fatigue"}
        if not history:
            return [self._result(name, None, common, cutoff, status="missing", missing_reason="no_prior_finished_matches") for name in ("days_since_last_match", "matches_last_7_days", "matches_last_14_days", "matches_last_30_days", "fatigue_score")]
        last_kickoff = parse_timestamp(history[0].get("date"))
        rest_days = max(0.0, (cutoff - last_kickoff).total_seconds() / 86400) if last_kickoff else None
        counts = {days: sum(1 for row in history if (date := parse_timestamp(row.get("date"))) and cutoff - timedelta(days=days) <= date < cutoff) for days in (7, 14, 30)}
        penalties = (
            _clamp((5 - (rest_days or 0)) / 5, 0, 1),
            _clamp((counts[7] - 1) / 3, 0, 1),
            _clamp((counts[14] - 3) / 4, 0, 1),
            _clamp((counts[30] - 6) / 6, 0, 1),
        )
        available = _max_time(*(row.get("available_at") for row in history))
        ids = _source_ids(history)
        return [
            self._result("days_since_last_match", round(rest_days, 6) if rest_days is not None else None, common, cutoff, source_ids=ids, available_at=available),
            *[self._result(f"matches_last_{days}_days", counts[days], common, cutoff, source_ids=ids, available_at=available) for days in (7, 14, 30)],
            self._result("fatigue_score", round(sum(penalties) / len(penalties), 6), common, cutoff, source_ids=ids, available_at=available),
        ]

    def _player_impact(self, team_id: str, side: str, evidence: Mapping[str, Any], cutoff: datetime) -> FeatureResult:
        player_ids = _player_ids(evidence, side)
        rules = []
        reader = getattr(self.repository, "player_impact_rules", None)
        if callable(reader) and player_ids:
            rules = reader(player_ids=player_ids, available_at_lte=cutoff.isoformat(), status="active")
        if rules:
            value = sum(float(rule.get("impact_value") or 0) for rule in rules)
            return self._result("player_impact", value, {"entity_id": team_id, "side": side, "source": "player_impact_rules", "calculation_version": "player-impact-rule-v1", "feature_group": "player"}, cutoff, source_ids=[str(rule.get("id")) for rule in rules], available_at=_max_time(*(rule.get("available_at") for rule in rules)))
        return self._result("player_impact", None, {"entity_id": team_id, "side": side, "source": "player_impact_rules", "calculation_version": "player-impact-rule-v1", "feature_group": "player"}, cutoff, source_ids=player_ids, status="missing", missing_reason="player_impact_rule_or_evidence_unavailable")

    def _result(self, name: str, value: Any, common: Mapping[str, Any], cutoff: datetime, *, source_ids: Iterable[str] | None = None, available_at: Any | None = None, status: str = "available", missing_reason: str | None = None, value_type: str | None = None) -> FeatureResult:
        definition = self.registry.get(name, str(common.get("calculation_version") or ""))
        if definition is None:
            definition = next((item.as_dict() for item in builtin_feature_definitions() if item.feature_name == name and item.calculation_version == common.get("calculation_version")), None)
        if definition is None:
            raise FeatureEngineError(
                f"unregistered feature or calculation version: {name}@{common.get('calculation_version')}"
            )
        source_ids_tuple = tuple(sorted({str(value) for value in source_ids or [] if value not in (None, "")}))
        parsed_available = parse_timestamp(available_at)
        if status == "available" and value is None:
            status = "missing"
            missing_reason = missing_reason or "calculation_value_missing"
        quality = 0.0 if status in {"missing", "future", "unverifiable", "calculation_failed"} else _quality_score(parsed_available, cutoff, len(source_ids_tuple), status, definition)
        return FeatureResult(
            feature_name=name,
            value=_round_value(value),
            value_type=value_type or _value_type(value),
            entity_type="team",
            entity_id=str(common.get("entity_id") or ""),
            available_at=parsed_available.isoformat() if parsed_available else None,
            source=str(common.get("source") or MISSING_SOURCE_ID),
            source_record_ids=source_ids_tuple or (MISSING_SOURCE_ID,),
            quality_score=quality,
            calculation_version=str(common.get("calculation_version") or FEATURE_ENGINE_VERSION),
            prediction_cutoff_at=cutoff.isoformat(),
            status=status,
            missing_reason=missing_reason,
            feature_group=str(common.get("feature_group") or "unknown"),
            side=str(common.get("side") or "") or None,
            registry_id=(definition or {}).get("id") if isinstance(definition, Mapping) else None,
        )

    def _fixtures(self) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "list_fixtures", None)
        if not callable(reader):
            return []
        try:
            return [dict(row) for row in reader() if isinstance(row, Mapping)]
        except TypeError:
            return []


def _eligible_team_rows(team_id: str, fixtures: Iterable[Mapping[str, Any]], cutoff: datetime, *, league: str | None = None, season: str | None = None) -> list[dict[str, Any]]:
    result = []
    for fixture in fixtures:
        if league and _league(fixture) != league:
            continue
        if season and _season(fixture, _league(fixture)) != season:
            continue
        status = str(fixture.get("status") or fixture.get("provider_status") or "").casefold()
        available = result_available_at(fixture)
        kickoff = parse_timestamp(fixture.get("kickoff"))
        if status not in SUPPORTED_RESULT_STATUSES or available is None or available > cutoff or kickoff is None:
            continue
        score = fixture.get("score") if isinstance(fixture.get("score"), Mapping) else {}
        if score.get("home") is None or score.get("away") is None:
            continue
        home = fixture.get("home_team") or {}
        away = fixture.get("away_team") or {}
        home_match = team_id in _team_ids(home)
        away_match = team_id in _team_ids(away)
        if home_match == away_match:
            continue
        is_home = home_match
        own_score = int(score["home"] if is_home else score["away"])
        opp_score = int(score["away"] if is_home else score["home"])
        result.append({
            "fixture_id": str(fixture.get("canonical_fixture_id") or fixture.get("id") or ""),
            "date": kickoff.isoformat(),
            "available_at": available.isoformat(),
            "team_is_home": is_home,
            "goals_for": own_score,
            "goals_against": opp_score,
            "result": "W" if own_score > opp_score else "D" if own_score == opp_score else "L",
            "opponent_id": _team_id(away if is_home else home),
            **_source_metrics(fixture, is_home),
        })
    return sorted(result, key=lambda row: (row["date"], row["fixture_id"]), reverse=True)


def _source_metrics(fixture: Mapping[str, Any], is_home: bool) -> dict[str, Any]:
    xg_home, xg_away = source_metric_pair(fixture, "xg")
    xp_home, xp_away = source_metric_pair(fixture, "xpoints")
    shots_home, shots_away = source_metric_pair(fixture, "shots")
    shots_on_target_home, shots_on_target_away = source_metric_pair(fixture, "shots_on_target")
    xg_available_at = fixture.get("xg_available_at") or ((fixture.get("xg") or {}).get("available_at") if isinstance(fixture.get("xg"), Mapping) else None)
    return {
        "xg_for": xg_home if is_home else xg_away,
        "xg_against": xg_away if is_home else xg_home,
        "xg_for_available_at": xg_available_at,
        "xg_against_available_at": xg_available_at,
        "xpoints": xp_home if is_home else xp_away,
        "xpoints_available_at": fixture.get("xpoints_available_at") or ((fixture.get("xpoints") or {}).get("available_at") if isinstance(fixture.get("xpoints"), Mapping) else None),
        "shots_for": shots_home if is_home else shots_away,
        "shots_against": shots_away if is_home else shots_home,
        "shots_on_target_for": shots_on_target_home if is_home else shots_on_target_away,
        "shots_on_target_against": shots_on_target_away if is_home else shots_on_target_home,
    }


def _series(rows: Sequence[Mapping[str, Any]], metric: str, cutoff: datetime | None = None) -> dict[str, Any]:
    values: list[float] = []
    times: list[datetime] = []
    future_at: datetime | None = None
    for row in rows:
        value = row.get(metric)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
        available = parse_timestamp(row.get(f"{metric}_available_at")) or parse_timestamp(row.get("available_at"))
        if available and cutoff is not None and available > cutoff:
            future_at = max(future_at, available) if future_at else available
        if available and (cutoff is None or available <= cutoff):
            times.append(available)
    if future_at is not None:
        return {"values": values, "available_at": max(times) if times else None, "future": True, "future_at": future_at}
    return {"values": values, "available_at": max(times) if times else None, "future": False, "future_at": None}


def _metric_series(rows: Sequence[Mapping[str, Any]], metric: str, cutoff: datetime | None = None) -> dict[str, Any]:
    return _series(rows, metric, cutoff)


def _primary_rate(rows: Sequence[Mapping[str, Any]], side: str) -> tuple[float | None, str | None]:
    mapping = (("xg_for", "provider_real_xg"), ("goals_for", "completed_match_results"), ("shots_on_target_for", "match_shots_on_target"), ("shots_for", "match_shots")) if side == "for" else (("xg_against", "provider_real_xg"), ("goals_against", "completed_match_results"), ("shots_on_target_against", "match_shots_on_target"), ("shots_against", "match_shots"))
    for field, source in mapping:
        values = [float(row[field]) for row in rows if row.get(field) is not None]
        if values and len(values) == len(rows):
            return sum(values) / len(values), source
    return None, None


def _opponent_factor(rows: Sequence[Mapping[str, Any]], elo_state: Mapping[str, Any]) -> float:
    ratings = []
    pre_match = elo_state.get("pre_match") or {}
    for row in rows:
        fixture_ratings = pre_match.get(row.get("fixture_id")) or {}
        opponent_side = "away" if row.get("team_is_home") else "home"
        if fixture_ratings.get(opponent_side) is not None:
            ratings.append(float(fixture_ratings[opponent_side]))
    return _clamp((sum(ratings) / len(ratings)) / 1500 if ratings else 1.0, 0.75, 1.25)


def _quality_score(available_at: datetime | None, cutoff: datetime, source_count: int, status: str, definition: Mapping[str, Any] | None) -> float:
    if not definition:
        reliability, ttl_hours = 1.0, 720.0
    else:
        payload = definition.get("payload") if isinstance(definition.get("payload"), Mapping) else definition
        reliability = float(payload.get("source_reliability") or 1.0)
        ttl_hours = float(payload.get("freshness_ttl_hours") or 720.0)
    age_hours = max(0.0, (cutoff - available_at).total_seconds() / 3600) if available_at else ttl_hours
    freshness = _clamp(1.0 - age_hours / ttl_hours, 0.0, 1.0)
    completeness = 1.0 if status == "available" else 0.6 if status == "insufficient_sample" else 0.0
    provider = 1.0 if source_count else 0.0
    success = 1.0 if status in {"available", "insufficient_sample"} else 0.0
    return round((reliability + freshness + completeness + provider + success) / 5, 4)


def _cutoff(value: Any) -> datetime:
    result = parse_timestamp(value)
    if result is None:
        raise FeatureEngineError("prediction_cutoff_at must be an ISO timestamp")
    return result


def _team_ids(team: Any) -> set[str]:
    if not isinstance(team, Mapping):
        return set()
    return {str(team[key]) for key in ("canonical_team_id", "provider_id", "id", "source_team_id", "team_id", "code") if team.get(key) not in (None, "")}


def _team_id(team: Any) -> str | None:
    if not isinstance(team, Mapping):
        return None
    for key in ("canonical_team_id", "provider_id", "id", "source_team_id", "team_id", "code"):
        if team.get(key) not in (None, ""):
            return str(team[key])
    return None


def _player_ids(evidence: Mapping[str, Any], side: str) -> list[str]:
    """Return player IDs backed by explicit absence/unavailability evidence."""

    rows: list[Any] = []
    availability = evidence.get("availability")
    if isinstance(availability, Mapping):
        rows.extend(
            row
            for row in availability.get("players") or []
            if isinstance(row, Mapping) and str(row.get("team") or "") == side
        )
    lineup = evidence.get("lineup")
    if isinstance(lineup, Mapping):
        rows.extend(
            row
            for row in lineup.get(f"{side}_players") or []
            if isinstance(row, Mapping)
            and (
                row.get("available") is False
                or str(row.get("status") or "").casefold()
                in {"absent", "injured", "missing", "out", "suspended", "unavailable"}
            )
        )
    return sorted(
        {
            str(value)
            for row in rows
            for value in (
                row.get("canonical_player_id"),
                row.get("provider_player_id"),
                row.get("player_id"),
                row.get("id"),
            )
            if value not in (None, "")
        }
    )


def _league(fixture: Mapping[str, Any]) -> str | None:
    value = fixture.get("canonical_league") or fixture.get("league_key")
    return str(value).upper() if value not in (None, "") else None


def _season(fixture: Mapping[str, Any], league: str | None) -> str | None:
    value = fixture.get("season_id") or fixture.get("season")
    if isinstance(value, Mapping):
        value = value.get("id") or value.get("year") or value.get("name")
    if value not in (None, ""):
        return str(value)
    kickoff = parse_timestamp(fixture.get("kickoff"))
    if kickoff is None or not league:
        return None
    return str(kickoff.year if league == "CSL" or kickoff.month >= 7 else kickoff.year - 1)


def _source_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(row.get("fixture_id")) for row in rows if row.get("fixture_id")]


def _max_time(*values: Any) -> datetime | None:
    parsed = [value for item in values if (value := parse_timestamp(item)) is not None]
    return max(parsed) if parsed else None


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "object"


def _round_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
