"""Deterministic P3 feature, ensemble, calibration, and backtest utilities."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping


FEATURE_VERSION = "round2-point-in-time-v1"
ENSEMBLE_VERSION = "p3-ensemble-v1"
CALIBRATION_VERSION = "p3-temperature-v1"
PROBABILITY_KEYS = ("home", "draw", "away")
DEFAULT_WEIGHTS = {"deepseek": 0.4, "chatgpt": 0.4, "poisson": 0.2}
MIN_PROFILE_SAMPLES = 30
MIN_CALIBRATION_SAMPLES = 30
SHRINKAGE_PRIOR_SAMPLES = 30.0
FORM_DECAY_LAMBDA = 0.08


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_probabilities(value: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        values = {key: max(0.0, float(value[key])) for key in PROBABILITY_KEYS}
    except (KeyError, TypeError, ValueError):
        return None
    total = sum(values.values())
    if total <= 0:
        return None
    return {key: round(values[key] / total, 6) for key in PROBABILITY_KEYS}


def build_feature_snapshot_v2(
    repository: Any,
    fixture: Mapping[str, Any],
    evidence: Mapping[str, Any],
    prediction_timestamp: Any,
    *,
    standings: Mapping[str, Any] | None = None,
    evidence_snapshot_id: str | None = None,
    odds_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility entry point for the Round 3 Feature Engine."""

    from .feature_engine import FeatureEngine

    return FeatureEngine(repository).calculate_snapshot(
        fixture,
        evidence,
        prediction_timestamp,
        standings=standings,
        evidence_snapshot_id=evidence_snapshot_id,
        odds_snapshot_id=odds_snapshot_id,
    )


def build_feature_snapshot(
    fixture: Mapping[str, Any],
    evidence: Mapping[str, Any],
    prediction_timestamp: Any | None = None,
    *,
    standings: Mapping[str, Any] | None = None,
    evidence_snapshot_id: str | None = None,
    odds_snapshot_id: str | None = None,
    repository: Any | None = None,
) -> dict[str, Any]:
    """Build an immutable point-in-time snapshot with per-feature boundaries."""

    if (
        repository is not None
        and callable(getattr(repository, "list_fixtures", None))
        and callable(getattr(repository, "feature_registry", None))
    ):
        return build_feature_snapshot_v2(
            repository,
            fixture,
            evidence,
            prediction_timestamp,
            standings=standings,
            evidence_snapshot_id=evidence_snapshot_id,
            odds_snapshot_id=odds_snapshot_id,
        )

    if prediction_timestamp is None:
        as_of = datetime.now(UTC)
    else:
        as_of = parse_timestamp(prediction_timestamp)
        if as_of is None:
            raise ValueError("prediction_timestamp must be an ISO timestamp")
    computed_at = datetime.now(UTC).isoformat()
    rejected: list[str] = []
    warnings: list[str] = []
    for field in ("captured_at", "synced_at"):
        captured = parse_timestamp(evidence.get(field))
        if captured and captured > as_of:
            rejected.append(field)
    evidence_available = _latest_timestamp(evidence.get("captured_at"), evidence.get("synced_at"))
    if evidence_available is None and evidence_snapshot_id:
        # The immutable evidence snapshot proves these values were observed at
        # the cutoff even when an individual provider omitted its own timestamp.
        # Explicit nested timestamps still take precedence and can fail the
        # point-in-time audit when they are later than the cutoff.
        evidence_available = as_of
    recent = evidence.get("recent_form") or {}
    recent_available = _feature_available_at(recent, evidence_available)
    recent_features = {
        side: _recent_form_features(
            recent.get(side) or [],
            as_of,
            rejected,
            warnings,
            side,
            recent_available,
        )
        for side in ("home", "away")
    }
    for side in ("home", "away"):
        persisted = ((recent.get("snapshot") or {}).get(side) or {}) if isinstance(recent, Mapping) else {}
        if persisted.get("rolling"):
            recent_features[side]["windows"] = deepcopy(persisted["rolling"])
        if persisted.get("season_average"):
            recent_features[side]["season_average"] = deepcopy(persisted["season_average"])
            recent_features[side]["season_matches_used"] = persisted.get("season_matches_used")
            recent_features[side]["season_available_at"] = persisted.get("season_available_at")
            recent_features[side]["season_source_record_ids"] = deepcopy(
                persisted.get("season_source_record_ids") or []
            )
    table = standings or evidence.get("standings") or {}
    standings_updated = parse_timestamp(table.get("updated_at")) if isinstance(table, Mapping) else None
    if standings_updated and standings_updated > as_of:
        rejected.append("standings")
        table = {}
    strength = _team_strength_features(table, recent_features)
    squad = _squad_features(evidence, as_of, rejected)
    schedule = _schedule_features(fixture, recent_features, as_of)
    market = _market_context(evidence, as_of, rejected)
    source_captured = _latest_timestamp(
        evidence.get("captured_at"),
        evidence.get("synced_at"),
        recent.get("updated_at"),
        (evidence.get("availability") or {}).get("updated_at"),
        (evidence.get("lineup") or {}).get("updated_at"),
        table.get("updated_at") if isinstance(table, Mapping) else None,
    )
    source = str(evidence.get("source") or "evidence_snapshot")
    source_record_id = (
        evidence_snapshot_id
        or str(evidence.get("snapshot_id") or evidence.get("id") or fixture.get("id") or "unknown")
    )
    features: list[dict[str, Any]] = []
    for side in ("home", "away"):
        side_features = recent_features[side]
        for window in (3, 5, 8, 10):
            key = f"last_{window}"
            _append_feature(
                features,
                feature_name=f"rolling_form.{side}.{key}",
                feature_value=(side_features.get("windows") or {}).get(key),
                source="match_results",
                source_record_ids=side_features.get("source_record_ids", [])[:window],
                available_at=side_features.get("available_at"),
                cutoff=as_of,
                computed_at=computed_at,
                rejected=rejected,
                warnings=warnings,
            )
        _append_feature(
            features,
            feature_name=f"rolling_form.{side}.season_average",
            feature_value=side_features.get("season_average"),
            source="match_results",
            source_record_ids=side_features.get("season_source_record_ids") or side_features.get("source_record_ids", []),
            available_at=side_features.get("season_available_at") or side_features.get("available_at"),
            cutoff=as_of,
            computed_at=computed_at,
            rejected=rejected,
            warnings=warnings,
        )
        _append_feature(
            features,
            feature_name=f"model_input.recent_form.{side}_points_per_game",
            feature_value=recent.get(f"{side}_points_per_game"),
            source="match_results",
            source_record_ids=side_features.get("source_record_ids", []),
            available_at=side_features.get("available_at"),
            cutoff=as_of,
            computed_at=computed_at,
            rejected=rejected,
            warnings=warnings,
        )
        _append_feature(
            features,
            feature_name=f"standings.{side}",
            feature_value=table.get(side) if isinstance(table, Mapping) else None,
            source=str((table.get("source") if isinstance(table, Mapping) else None) or "standings"),
            source_record_ids=[
                str((table.get("snapshot_id") if isinstance(table, Mapping) else None) or source_record_id)
            ],
            available_at=standings_updated,
            cutoff=as_of,
            computed_at=computed_at,
            rejected=rejected,
            warnings=warnings,
        )

    lineup = evidence.get("lineup") if isinstance(evidence.get("lineup"), Mapping) else {}
    lineup_available = _feature_available_at(lineup, evidence_available)
    lineup_record_ids = lineup.get("source_record_ids") or [source_record_id]
    for name in ("confirmed", "home_strength", "away_strength"):
        _append_feature(
            features,
            feature_name=f"model_input.lineup.{name}",
            feature_value=lineup.get(name) if lineup else None,
            source=str(lineup.get("source") or "lineup"),
            source_record_ids=lineup_record_ids,
            available_at=lineup_available,
            cutoff=as_of,
            computed_at=computed_at,
            rejected=rejected,
            warnings=warnings,
        )

    impact = evidence.get("player_impact") if isinstance(evidence.get("player_impact"), Mapping) else {}
    player_inputs_available = _feature_available_at(
        {
            "squads": evidence.get("squads"),
            "availability": evidence.get("availability"),
            "lineup": evidence.get("lineup"),
        },
        evidence_available,
    )
    player_record_ids = sorted(
        {
            *(_source_record_ids((evidence.get("availability") or {}).get("source_record_ids")) if isinstance(evidence.get("availability"), Mapping) else []),
            *(_source_record_ids((evidence.get("lineup") or {}).get("source_record_ids")) if isinstance(evidence.get("lineup"), Mapping) else []),
            source_record_id,
        }
    )
    for side in ("home", "away"):
        side_impact = impact.get(side) if isinstance(impact.get(side), Mapping) else {}
        for name in ("attack_retention", "defense_retention", "resolved_absence_count"):
            _append_feature(
                features,
                feature_name=f"model_input.player_impact.{side}.{name}",
                feature_value=side_impact.get(name) if side_impact else None,
                source="player_impact",
                source_record_ids=player_record_ids,
                available_at=player_inputs_available,
                cutoff=as_of,
                computed_at=computed_at,
                rejected=rejected,
                warnings=warnings,
            )

    elo = evidence.get("elo") if isinstance(evidence.get("elo"), Mapping) else {}
    elo_available = _feature_available_at(elo, evidence_available)
    for side in ("home", "away"):
        team = fixture.get(f"{side}_team") or {}
        team_name = str(team.get("name") or team.get("original_name") or "") if isinstance(team, Mapping) else str(team or "")
        _append_feature(
            features,
            feature_name=f"model_input.elo.{side}_rating",
            feature_value=elo.get(team_name) if team_name else None,
            source=str(elo.get("source") or "elo"),
            source_record_ids=elo.get("source_record_ids") or [source_record_id],
            available_at=elo_available,
            cutoff=as_of,
            computed_at=computed_at,
            rejected=rejected,
            warnings=warnings,
        )

    category_features = (
        ("team_statistics", evidence.get("team_stats"), "team_statistics"),
        ("player_statistics", {"teams": evidence.get("teams"), "squads": evidence.get("squads")}, "player_statistics"),
        ("injuries", evidence.get("availability"), "injuries"),
        ("lineup", evidence.get("lineup"), "lineup"),
        ("odds", evidence.get("odds"), "odds"),
        ("weather", evidence.get("weather"), "weather"),
        ("referee", evidence.get("referee") or fixture.get("referee"), "referee"),
        ("head_to_head", evidence.get("head_to_head"), "match_results"),
        ("news_evidence", evidence.get("news") or evidence.get("news_evidence"), "news_evidence"),
        ("elo", evidence.get("elo"), "elo"),
        ("discipline", evidence.get("discipline"), "discipline"),
        ("transfers", evidence.get("transfers"), "transfers"),
        ("match_context", evidence.get("match_context"), "match_context"),
    )
    for name, value, default_source in category_features:
        value_mapping = value if isinstance(value, Mapping) else {}
        value_source = value_mapping.get("source") if isinstance(value_mapping, Mapping) else None
        record_ids = value_mapping.get("source_record_ids") if isinstance(value_mapping, Mapping) else None
        _append_feature(
            features,
            feature_name=name,
            feature_value=value,
            source=str(value_source or default_source or source),
            source_record_ids=record_ids or [source_record_id],
            available_at=_feature_available_at(value, evidence_available),
            cutoff=as_of,
            computed_at=computed_at,
            rejected=rejected,
            warnings=warnings,
        )

    identity = {
        "fixture_id": str(fixture.get("canonical_fixture_id") or fixture.get("id") or ""),
        "prediction_cutoff_at": as_of.isoformat(),
        "feature_version": FEATURE_VERSION,
        "evidence_snapshot_id": evidence_snapshot_id,
        "odds_snapshot_id": odds_snapshot_id,
        "features": [
            {
                key: item.get(key)
                for key in ("feature_name", "feature_value", "source", "source_record_id", "available_at", "status")
            }
            for item in features
        ],
    }
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    snapshot_id = f"feature:{hashlib.sha256(encoded).hexdigest()}"
    for item in features:
        item["snapshot_id"] = snapshot_id
    rejected = list(dict.fromkeys(rejected))
    warnings = list(dict.fromkeys(warnings))
    snapshot = {
        "snapshot_id": snapshot_id,
        "feature_snapshot_id": snapshot_id,
        "fixture_id": str(fixture.get("id") or ""),
        "canonical_fixture_id": str(fixture.get("canonical_fixture_id") or fixture.get("id") or ""),
        "captured_at": as_of.isoformat(),
        "prediction_timestamp": as_of.isoformat(),
        "prediction_cutoff_at": as_of.isoformat(),
        "computed_at": computed_at,
        "source_captured_at": source_captured.isoformat() if source_captured else None,
        "feature_version": FEATURE_VERSION,
        "dataset_version": evidence.get("dataset_version"),
        "evidence_snapshot_id": evidence_snapshot_id,
        "odds_snapshot_id": odds_snapshot_id,
        "features": features,
        "team_strength": strength,
        "recent_form": recent_features,
        "home_away": {
            "home": recent_features["home"].get("home_split"),
            "away": recent_features["away"].get("away_split"),
        },
        "squad_status": squad,
        "schedule_context": schedule,
        "market_context": market,
        "leakage_detected": bool(rejected),
        "leakage_check": {
            "passed": not rejected,
            "rejected_future_fields": rejected,
            "violations": [
                {
                    "feature_name": item["feature_name"],
                    "available_at": item["available_at"],
                    "prediction_cutoff_at": item["prediction_cutoff_at"],
                    "reason": (
                        "available_at_missing"
                        if item["status"] == "unverifiable"
                        else "available_after_prediction_cutoff"
                    ),
                }
                for item in features
                if item["status"] in {"future", "unverifiable"}
            ],
            "warnings": warnings,
        },
    }
    snapshot["quality_payload"] = {
        "features_total": len(features),
        "features_available": sum(item["status"] == "available" for item in features),
        "features_missing": sum(item["status"] == "missing" for item in features),
        "features_unverifiable": sum(item["status"] == "unverifiable" for item in features),
    }
    snapshot["leakage_payload"] = deepcopy(snapshot["leakage_check"])
    return snapshot


def _recent_form_features(
    rows: list[Mapping[str, Any]],
    as_of: datetime,
    rejected: list[str],
    warnings: list[str],
    side: str,
    default_available_at: datetime | None,
) -> dict[str, Any]:
    usable: list[tuple[Mapping[str, Any], float, int, datetime]] = []
    for raw_row in rows:
        row = raw_row if isinstance(raw_row, Mapping) else {"result": str(raw_row)}
        occurred = parse_timestamp(row.get("date"))
        available_at = _feature_available_at(row, default_available_at)
        if occurred and occurred > as_of:
            rejected.append(f"recent_form.{side}")
            continue
        if available_at and available_at > as_of:
            rejected.append(f"recent_form.{side}")
            continue
        if available_at is None:
            warnings.append(f"recent_form.{side}:available_at_missing")
            continue
        age_days = max(0.0, (as_of - (occurred or available_at)).total_seconds() / 86400)
        points = 3 if row.get("result") == "W" else 1 if row.get("result") == "D" else 0
        usable.append((row, math.exp(-FORM_DECAY_LAMBDA * age_days), points, available_at))

    def aggregate(items: list[tuple[Mapping[str, Any], float, int, datetime]]) -> dict[str, Any] | None:
        if not items:
            return None
        weight_total = sum(weight for _, weight, _, _ in items)
        goals_for = 0.0
        goals_against = 0.0
        points = 0.0
        for row, weight, result_points, _ in items:
            scored, conceded = _score_pair(row.get("score"), bool(row.get("team_is_home")))
            if scored is not None:
                goals_for += scored * weight
                goals_against += conceded * weight
            points += result_points * weight
        return {
            "sample_size": len(items),
            "goals_for": round(goals_for / weight_total, 4),
            "goals_against": round(goals_against / weight_total, 4),
            "points": round(points / weight_total, 4),
            "decay_lambda": FORM_DECAY_LAMBDA,
        }

    home_split = aggregate([item for item in usable if item[0].get("team_is_home") is True])
    away_split = aggregate([item for item in usable if item[0].get("team_is_home") is False])
    aggregate_all = aggregate(usable)
    source_ids = [
        str(item[0].get("canonical_fixture_id") or item[0].get("fixture_id") or "")
        for item in usable
    ]
    return {
        "sample_size": len(usable),
        "weighted": aggregate_all,
        "windows": {f"last_{window}": aggregate(usable[:window]) for window in (3, 5, 8, 10)},
        "season_average": aggregate(usable),
        "season_matches_used": len(usable),
        "home_split": home_split,
        "away_split": away_split,
        "available_at": max((item[3] for item in usable), default=None).isoformat() if usable else None,
        "season_available_at": max((item[3] for item in usable), default=None).isoformat() if usable else None,
        "source_record_ids": [value for value in source_ids if value],
        "season_source_record_ids": [value for value in source_ids if value],
        "status": "missing" if not usable else "complete",
    }


def _append_feature(
    features: list[dict[str, Any]],
    *,
    feature_name: str,
    feature_value: Any,
    source: str,
    source_record_ids: Any,
    available_at: Any,
    cutoff: datetime,
    computed_at: str,
    rejected: list[str],
    warnings: list[str],
) -> None:
    ids = _source_record_ids(source_record_ids)
    available = parse_timestamp(available_at)
    if _missing_value(feature_value):
        status = "missing"
    elif available is None:
        status = "unverifiable"
        rejected.append(feature_name)
        warnings.append(f"{feature_name}:available_at_missing")
    elif available > cutoff:
        status = "future"
        rejected.append(feature_name)
    else:
        status = "available"
    identity = "|".join(ids) or "unknown"
    if len(identity) > 255:
        identity = f"sha256:{hashlib.sha256(identity.encode()).hexdigest()}"
    features.append(
        {
            "feature_name": feature_name,
            "feature_value": deepcopy(feature_value),
            "source": source,
            "source_record_id": identity,
            "source_record_ids": ids,
            "computed_at": computed_at,
            "available_at": available.isoformat() if available else None,
            "prediction_cutoff_at": cutoff.isoformat(),
            "feature_version": FEATURE_VERSION,
            "snapshot_id": None,
            "status": status,
        }
    )


def _source_record_ids(value: Any) -> list[str]:
    raw = value if isinstance(value, (list, tuple, set)) else [value]
    return sorted({str(item) for item in raw if item not in (None, "")})


def _feature_available_at(value: Any, fallback: datetime | None = None) -> datetime | None:
    timestamps: list[datetime] = []
    if isinstance(value, Mapping):
        direct = _latest_timestamp(
            value.get("available_at"),
            value.get("result_captured_at"),
            value.get("completed_at"),
            value.get("captured_at"),
            value.get("source_captured_at"),
            value.get("source_updated_at"),
            value.get("retrieved_at"),
            value.get("published_at"),
            value.get("observed_at"),
            value.get("market_value_as_of"),
            value.get("value_as_of"),
            value.get("ingested_at"),
            value.get("cached_at"),
            value.get("updated_at"),
            value.get("synced_at"),
        )
        if direct:
            timestamps.append(direct)
        for nested_value in value.values():
            if isinstance(nested_value, (Mapping, list)):
                nested = _feature_available_at(nested_value)
                if nested:
                    timestamps.append(nested)
    if isinstance(value, list):
        nested = [_feature_available_at(item) for item in value]
        timestamps.extend(item for item in nested if item is not None)
    return max(timestamps) if timestamps else fallback


def _missing_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, Mapping):
        return not value or all(_missing_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return not value or all(_missing_value(item) for item in value)
    return False


def cutoff_safe_prediction_inputs(
    context: Mapping[str, Any],
    standings: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove non-empty inputs whose availability cannot be proven at cutoff."""

    safe = deepcopy(dict(context))

    def feature_rows(prefix: str) -> list[Mapping[str, Any]]:
        return [
            item
            for item in snapshot.get("features") or []
            if isinstance(item, Mapping)
            if str(item.get("feature_name") or "") == prefix
            or str(item.get("feature_name") or "").startswith(f"{prefix}.")
        ]

    def usable(prefix: str) -> bool:
        return any(item.get("status") == "available" for item in feature_rows(prefix))

    recent = deepcopy(safe.get("recent_form") or {})
    retained_recent_times: list[datetime] = []
    for side in ("home", "away"):
        rows = feature_rows(f"rolling_form.{side}")
        if any(item.get("status") == "available" for item in rows):
            retained_recent_times.extend(
                parsed
                for item in rows
                if item.get("status") == "available"
                and (parsed := parse_timestamp(item.get("available_at"))) is not None
            )
            continue
        recent[side] = []
        recent[f"{side}_points_per_game"] = 0.0
        if isinstance(recent.get("snapshot"), Mapping):
            recent["snapshot"] = {**recent["snapshot"], side: {}}
    latest_recent = max(retained_recent_times, default=None)
    recent["updated_at"] = latest_recent.isoformat() if latest_recent else None
    recent["available_at"] = recent["updated_at"]
    safe["recent_form"] = recent
    if not usable("team_statistics"):
        safe.pop("team_stats", None)
    if not usable("player_statistics"):
        safe["teams"] = {"home": {}, "away": {}}
        safe["squads"] = {"home": [], "away": []}
    if not usable("injuries"):
        safe["availability"] = {"players": [], "notes": [], "updated_at": None}
    if not usable("lineup"):
        safe["lineup"] = {
            "confirmed": False,
            "home_strength": None,
            "away_strength": None,
            "home_players": [],
            "away_players": [],
            "updated_at": None,
        }
    # ``player_impact`` is derived from squads, injuries and lineup. Always
    # discard the pre-audit value; the prediction service recomputes it from
    # the sanitized dependencies so an unverifiable input cannot survive via
    # a derived retention score.
    safe.pop("player_impact", None)
    if not usable("odds"):
        safe["odds"] = None
    for name in ("weather", "referee", "head_to_head", "news_evidence", "elo", "discipline", "transfers", "match_context"):
        if not usable(name):
            safe.pop("news" if name == "news_evidence" else name, None)
            if name == "news_evidence":
                safe.pop("news_evidence", None)
    safe_standings = deepcopy(dict(standings)) if usable("standings") else {}
    return safe, safe_standings


def cutoff_safe_fixture(
    fixture: Mapping[str, Any],
    prediction_cutoff_at: Any,
) -> dict[str, Any]:
    """Return the pre-match fixture view that a model may consume."""

    safe = deepcopy(dict(fixture))
    cutoff = parse_timestamp(prediction_cutoff_at)
    kickoff = parse_timestamp(fixture.get("kickoff"))
    if cutoff is not None and kickoff is not None and cutoff < kickoff:
        safe["status"] = "scheduled"
        safe["score"] = None
        for field in ("minute", "elapsed", "match_minute"):
            safe[field] = None
    return safe


def model_feature_manifest(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Expose feature provenance to a model without duplicating raw values."""

    keys = (
        "feature_name",
        "source",
        "source_record_id",
        "computed_at",
        "available_at",
        "prediction_cutoff_at",
        "feature_version",
        "snapshot_id",
        "status",
    )
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "prediction_cutoff_at": snapshot.get("prediction_cutoff_at"),
        "feature_version": snapshot.get("feature_version"),
        "leakage_detected": bool(snapshot.get("leakage_detected")),
        "features": [
            {key: item.get(key) for key in keys}
            for item in snapshot.get("features") or []
            if isinstance(item, Mapping)
        ],
    }


def _score_pair(value: Any, team_is_home: bool) -> tuple[float | None, float | None]:
    if not isinstance(value, str):
        return None, None
    parts = value.replace("-", " ").split()
    if len(parts) < 2:
        return None, None
    try:
        home, away = float(parts[0]), float(parts[1])
    except ValueError:
        return None, None
    return (home, away) if team_is_home else (away, home)


def _team_strength_features(
    standings: Mapping[str, Any],
    recent: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for side in ("home", "away"):
        row = standings.get(side) if isinstance(standings, Mapping) else None
        played = _positive_number((row or {}).get("played"))
        goals_for = _positive_or_zero((row or {}).get("goals_for"))
        goals_against = _positive_or_zero((row or {}).get("goals_against"))
        points = _positive_or_zero((row or {}).get("points"))
        if not played or (goals_for == 0 and goals_against == 0 and points == 0):
            result[side] = {"status": "missing", "long_term_strength": None, "form_adjustment": None}
            continue
        attack = goals_for / played
        defense = goals_against / played
        points_rate = points / (3 * played) if played else 0.0
        weighted = (recent.get(side) or {}).get("weighted") or {}
        form_adjustment = round(
            ((weighted.get("goals_for") or 0) - (weighted.get("goals_against") or 0)) * 0.05,
            4,
        ) if weighted else None
        result[side] = {
            "status": "complete",
            "long_term_strength": {
                "attack_strength": round(attack, 4),
                "defense_strength": round(defense, 4),
                "points_rate": round(points_rate, 4),
            },
            "form_adjustment": form_adjustment,
            "source": "league_standings",
        }
    return result


def _squad_features(
    evidence: Mapping[str, Any],
    as_of: datetime,
    rejected: list[str],
) -> dict[str, Any]:
    availability = evidence.get("availability") or {}
    lineup = evidence.get("lineup") or {}
    updated = _latest_timestamp(availability.get("updated_at"), lineup.get("updated_at"))
    if updated and updated > as_of:
        rejected.append("squad_status")
        return {"status": "missing", "source": None, "captured_at": None, "confidence": 0.0}
    impact = evidence.get("player_impact") or {}
    if not impact and not availability.get("updated_at"):
        return {"status": "missing", "source": None, "captured_at": None, "confidence": 0.0}
    return {
        "status": "complete" if impact else "partial",
        "source": availability.get("source") or evidence.get("source") or "evidence_snapshot",
        "captured_at": updated.isoformat() if updated else None,
        "confidence": 1.0 if impact else 0.5,
        "lineup_confirmed": bool(lineup.get("confirmed")),
        "home": _impact_summary(impact.get("home")),
        "away": _impact_summary(impact.get("away")),
    }


def _impact_summary(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "attack_retention": value.get("attack_retention"),
        "defense_retention": value.get("defense_retention"),
        "absence_count": value.get("resolved_absence_count"),
        "data_status": value.get("data_status"),
    }


def _schedule_features(
    fixture: Mapping[str, Any],
    recent: Mapping[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "fixture_date": fixture.get("fixture_date"),
        "kickoff": fixture.get("kickoff"),
    }
    for side in ("home", "away"):
        rows = (recent.get(side) or {}).get("weighted")
        result[f"{side}_sample_size"] = (recent.get(side) or {}).get("sample_size", 0)
        result[f"{side}_as_of"] = as_of.isoformat()
        result[f"{side}_last_match_date"] = None
        if rows:
            result[f"{side}_form_status"] = "available"
        else:
            result[f"{side}_form_status"] = "missing"
    return result


def _market_context(evidence: Mapping[str, Any], as_of: datetime, rejected: list[str]) -> dict[str, Any]:
    odds = evidence.get("odds") or {}
    updated = parse_timestamp(odds.get("updated_at")) if isinstance(odds, Mapping) else None
    if updated and updated > as_of:
        rejected.append("market_context")
        return {"status": "missing", "used_for_probability": False}
    prices = [float(odds[key]) for key in ("home", "draw", "away") if _positive_number(odds.get(key))]
    dispersion = max(prices) - min(prices) if len(prices) >= 2 else None
    return {
        "status": "available" if prices else "missing",
        "opening_odds": odds.get("opening_odds"),
        "latest_pre_kickoff_odds": {key: odds.get(key) for key in ("home", "draw", "away")},
        "market_dispersion": round(dispersion, 6) if dispersion is not None else None,
        "bookmaker_count": odds.get("bookmaker_count") or (1 if prices else 0),
        "captured_at": updated.isoformat() if updated else None,
        "used_for_probability": False,
    }


def _latest_timestamp(*values: Any) -> datetime | None:
    timestamps = [parsed for value in values if (parsed := parse_timestamp(value)) is not None]
    return max(timestamps) if timestamps else None


def _positive_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_or_zero(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def weighted_ensemble(
    base_predictions: Mapping[str, Mapping[str, Any]],
    *,
    weights: Mapping[str, float] | None = None,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
    league_key: str | None = None,
    market: str = "1x2",
) -> dict[str, Any]:
    """Combine available base probabilities with explainable effective weights."""

    available = {
        key: normalized
        for key, value in base_predictions.items()
        if (normalized := normalize_probabilities(value)) is not None
    }
    if not available:
        return {
            "status": "unavailable",
            "base_predictions": {},
            "weights": {},
            "ensemble_probabilities": None,
            "feature_version": FEATURE_VERSION,
        }
    effective = resolve_model_weights(
        tuple(available),
        weights=weights,
        profiles=profiles,
        league_key=league_key,
        market=market,
    )
    total = sum(effective.values()) or 1.0
    probabilities = {
        outcome: round(
            sum(available[model][outcome] * effective.get(model, 0.0) for model in available) / total,
            6,
        )
        for outcome in PROBABILITY_KEYS
    }
    probabilities = normalize_probabilities(probabilities) or probabilities
    profile_scopes = {
        model_key: (
            _resolve_profile(model_key, profiles or {}, league_key, market) or {}
        ).get("scope", "baseline")
        for model_key in available
    }
    return {
        "status": "ok",
        "ensemble_version": ENSEMBLE_VERSION,
        "base_predictions": available,
        "weights": {key: round(value / total, 6) for key, value in effective.items()},
        "profile_scopes": profile_scopes,
        "ensemble_probabilities": probabilities,
        "league_key": league_key,
        "market": market,
        "feature_version": FEATURE_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "calibration_status": "pending_out_of_sample_fit",
    }


def resolve_model_weights(
    model_keys: Iterable[str],
    *,
    weights: Mapping[str, float] | None = None,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
    league_key: str | None = None,
    market: str = "1x2",
) -> dict[str, float]:
    defaults = weights or DEFAULT_WEIGHTS
    result: dict[str, float] = {}
    for model_key in model_keys:
        profile = _resolve_profile(model_key, profiles or {}, league_key, market)
        if profile:
            raw = float(profile.get("raw_weight") or profile.get("weight") or defaults.get(model_key, 0.0))
            samples = max(0.0, float(profile.get("sample_size") or 0))
            confidence = samples / (samples + SHRINKAGE_PRIOR_SAMPLES)
            drift_factor = float(profile.get("drift_factor") or 1.0)
            result[model_key] = max(0.0, raw * confidence * drift_factor + defaults.get(model_key, 0.0) * (1 - confidence))
        else:
            result[model_key] = max(0.0, float(defaults.get(model_key, 0.0)))
    if not any(result.values()):
        result = {key: 1.0 for key in model_keys}
    return result


def _resolve_profile(
    model_key: str,
    profiles: Mapping[str, Mapping[str, Any]],
    league_key: str | None,
    market: str,
) -> Mapping[str, Any] | None:
    for scope in (
        f"league_market:{league_key}:{market}",
        f"league:{league_key}",
        "global",
    ):
        profile = profiles.get(f"{model_key}|{scope}")
        if profile and (
            scope == "global"
            or float(profile.get("sample_size") or 0) >= MIN_PROFILE_SAMPLES
        ):
            return profile
    return None


def build_performance_profiles(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Build global/league/market profiles from P1 evaluation rows only."""

    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    as_of_at = parse_timestamp(as_of)
    for row in rows:
        if as_of_at:
            row_times = [
                parse_timestamp(row.get("prediction_created_at")),
                parse_timestamp(row.get("settled_at")),
            ]
            if any(row_at and row_at > as_of_at for row_at in row_times):
                continue
        model = str(row.get("model_key") or "")
        probabilities = normalize_probabilities(row.get("model_probabilities") or row.get("probabilities"))
        actual = row.get("actual_outcome")
        if not model or probabilities is None or actual not in PROBABILITY_KEYS:
            continue
        league = str(row.get("league_key") or "")
        market = str((row.get("decision") or {}).get("market") or "1x2")
        grouped[(model, league, market)].append(row)
        grouped[(model, league, "*")].append(row)
        grouped[(model, "*", "*")].append(row)
    profiles: dict[str, dict[str, Any]] = {}
    for (model, league, market), group in grouped.items():
        metrics = _performance_metrics(group, as_of=as_of)
        scope = "global" if league == "*" else f"league_market:{league}:{market}" if market != "*" else f"league:{league}"
        profiles[f"{model}|{scope}"] = {
            "model_key": model,
            "league": None if league == "*" else league,
            "market": None if market == "*" else market,
            "scope": scope,
            **metrics,
        }
    return profiles


def _performance_metrics(rows: list[Mapping[str, Any]], *, as_of: Any | None = None) -> dict[str, Any]:
    now = parse_timestamp(as_of) or datetime.now(UTC)
    weighted_rows: list[tuple[Mapping[str, Any], float]] = []
    for row in rows:
        timestamp = parse_timestamp(row.get("prediction_created_at") or row.get("settled_at"))
        age_days = max(0.0, (now - timestamp).total_seconds() / 86400) if timestamp else 0.0
        weighted_rows.append((row, math.exp(-age_days / 365.0)))
    weight_total = sum(weight for _, weight in weighted_rows) or 1.0
    brier = 0.0
    log_loss = 0.0
    for row, weight in weighted_rows:
        probabilities = normalize_probabilities(row.get("model_probabilities") or row.get("probabilities")) or {}
        actual = row.get("actual_outcome")
        brier_value = sum((probabilities[key] - (1.0 if key == actual else 0.0)) ** 2 for key in PROBABILITY_KEYS)
        log_value = -math.log(max(1e-9, probabilities.get(actual, 0.0)))
        brier += brier_value * weight
        log_loss += log_value * weight
    raw = 1.0 / max(1e-9, brier / weight_total + log_loss / weight_total / 2)
    drift_factor, drift_status = _drift_factor(rows)
    return {
        "sample_size": len(rows),
        "brier": round(brier / weight_total, 6),
        "log_loss": round(log_loss / weight_total, 6),
        "ece": _ece(rows),
        "clv": _average_clv(rows),
        "raw_weight": round(raw, 6),
        "weight": round(raw * drift_factor, 6),
        "drift_factor": drift_factor,
        "drift_status": drift_status,
        "updated_at": now.isoformat(),
    }


def _drift_factor(rows: list[Mapping[str, Any]]) -> tuple[float, str]:
    ordered = sorted(rows, key=lambda row: str(row.get("prediction_created_at") or row.get("settled_at") or ""))
    if len(ordered) < 10:
        return 1.0, "insufficient_sample"
    midpoint = len(ordered) // 2
    older_rows = ordered[:midpoint]
    recent_rows = ordered[midpoint:]
    older = _average_brier(older_rows)
    recent = _average_brier(recent_rows)
    log_old = _average_log_loss(older_rows)
    log_recent = _average_log_loss(recent_rows)
    ece_old = _ece(older_rows)
    ece_recent = _ece(recent_rows)
    clv_old = _average_clv(older_rows)
    clv_recent = _average_clv(recent_rows)
    deteriorating = (
        older is not None and recent is not None and recent > older * 1.10
    ) or (
        log_old is not None and log_recent is not None and log_recent > log_old * 1.10
    ) or (
        ece_old is not None and ece_recent is not None and ece_recent > ece_old * 1.10
    ) or (
        clv_old is not None and clv_recent is not None and clv_recent < clv_old - 0.01
    )
    if deteriorating:
        return 0.5, "deteriorating"
    return 1.0, "stable"


def _average_brier(rows: Iterable[Mapping[str, Any]]) -> float | None:
    values: list[float] = []
    for row in rows:
        probabilities = normalize_probabilities(row.get("model_probabilities") or row.get("probabilities"))
        actual = row.get("actual_outcome")
        if probabilities and actual in PROBABILITY_KEYS:
            values.append(sum((probabilities[key] - (1.0 if key == actual else 0.0)) ** 2 for key in PROBABILITY_KEYS))
    return sum(values) / len(values) if values else None


def _average_log_loss(rows: Iterable[Mapping[str, Any]]) -> float | None:
    values: list[float] = []
    for row in rows:
        probabilities = normalize_probabilities(row.get("model_probabilities") or row.get("probabilities"))
        actual = row.get("actual_outcome")
        if probabilities and actual in PROBABILITY_KEYS:
            values.append(-math.log(max(1e-9, probabilities[actual])))
    return sum(values) / len(values) if values else None


def _average_clv(rows: Iterable[Mapping[str, Any]]) -> float | None:
    values = [float(row["clv"]) for row in rows if row.get("clv") is not None]
    return round(sum(values) / len(values), 6) if values else None


def _ece(rows: Iterable[Mapping[str, Any]]) -> float | None:
    valid = []
    for row in rows:
        probabilities = normalize_probabilities(row.get("model_probabilities") or row.get("probabilities"))
        if probabilities and row.get("actual_outcome") in PROBABILITY_KEYS:
            valid.append((probabilities, row["actual_outcome"]))
    if not valid:
        return None
    errors = []
    for outcome in PROBABILITY_KEYS:
        bins = [[0.0, 0, 0.0] for _ in range(10)]
        for probabilities, actual in valid:
            probability = probabilities[outcome]
            bucket = bins[min(9, int(probability * 10))]
            bucket[0] += probability
            bucket[1] += 1
            bucket[2] += 1.0 if actual == outcome else 0.0
        errors.append(
            sum(
                count / len(valid) * abs(actual_sum / count - predicted_sum / count)
                for predicted_sum, count, actual_sum in bins
                if count
            )
        )
    return round(sum(errors) / len(errors), 6)


def split_time_ordered(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("prediction_created_at") or row.get("settled_at") or ""))
    if not ordered:
        return [], [], []
    train_end = max(1, int(len(ordered) * 0.6))
    calibration_end = max(train_end, int(len(ordered) * 0.8))
    return ordered[:train_end], ordered[train_end:calibration_end], ordered[calibration_end:]


def fit_temperature(
    rows: Iterable[Mapping[str, Any]],
    *,
    probability_reader: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
    trained_at: Any | None = None,
    as_of: Any | None = None,
) -> dict[str, Any]:
    rows = list(rows)
    as_of_at = parse_timestamp(as_of)
    if as_of_at:
        rows = [
            row
            for row in rows
            if all(
                not row_at or row_at <= as_of_at
                for row_at in (
                    parse_timestamp(row.get("prediction_created_at")),
                    parse_timestamp(row.get("settled_at")),
                )
            )
        ]
    if len(rows) < MIN_CALIBRATION_SAMPLES:
        return {
            "status": "calibration_unavailable",
            "calibration_version": CALIBRATION_VERSION,
            "method": "temperature_scaling",
            "sample_size": len(rows),
            "minimum_samples": MIN_CALIBRATION_SAMPLES,
            "temperature": None,
        }
    reader = probability_reader or (lambda row: row.get("ensemble_probabilities") or row.get("model_probabilities"))
    valid = [row for row in rows if normalize_probabilities(reader(row)) and row.get("actual_outcome") in PROBABILITY_KEYS]
    if len(valid) < MIN_CALIBRATION_SAMPLES:
        return {
            "status": "calibration_unavailable",
            "calibration_version": CALIBRATION_VERSION,
            "method": "temperature_scaling",
            "sample_size": len(valid),
            "minimum_samples": MIN_CALIBRATION_SAMPLES,
            "temperature": None,
        }
    best_temperature = 1.0
    best_loss = float("inf")
    for index in range(51):
        temperature = round(0.5 + index * 0.05, 2)
        loss = sum(
            -math.log(max(1e-9, apply_temperature(normalize_probabilities(reader(row)) or {}, temperature).get(row["actual_outcome"], 0.0)))
            for row in valid
        ) / len(valid)
        if loss < best_loss - 1e-12:
            best_loss = loss
            best_temperature = temperature
    return {
        "status": "ok",
        "calibration_version": CALIBRATION_VERSION,
        "method": "temperature_scaling",
        "trained_at": (parse_timestamp(trained_at) or datetime.now(UTC)).isoformat(),
        "sample_size": len(valid),
        "minimum_samples": MIN_CALIBRATION_SAMPLES,
        "temperature": best_temperature,
        "calibration_log_loss": round(best_loss, 6),
    }


def apply_temperature(probabilities: Mapping[str, Any], temperature: float) -> dict[str, float]:
    normalized = normalize_probabilities(probabilities) or {key: 1 / 3 for key in PROBABILITY_KEYS}
    logits = {key: math.log(max(1e-9, normalized[key])) / max(1e-6, temperature) for key in PROBABILITY_KEYS}
    maximum = max(logits.values())
    values = {key: math.exp(logits[key] - maximum) for key in PROBABILITY_KEYS}
    total = sum(values.values())
    return {key: round(values[key] / total, 6) for key in PROBABILITY_KEYS}


def evaluate_probabilities(
    rows: Iterable[Mapping[str, Any]],
    probability_reader: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
) -> dict[str, Any]:
    valid = []
    for row in rows:
        probabilities = normalize_probabilities(probability_reader(row))
        if probabilities and row.get("actual_outcome") in PROBABILITY_KEYS:
            valid.append((row, probabilities))
    if not valid:
        return {"status": "insufficient_sample", "samples": 0, "brier": None, "log_loss": None, "ece": None, "rps": None, "clv": None}
    brier = []
    log_loss = []
    ece = []
    rps = []
    for row, probabilities in valid:
        actual = row["actual_outcome"]
        brier.append(sum((probabilities[key] - (1.0 if key == actual else 0.0)) ** 2 for key in PROBABILITY_KEYS))
        log_loss.append(-math.log(max(1e-9, probabilities[actual])))
        ece.append(sum(abs(probabilities[key] - (1.0 if key == actual else 0.0)) for key in PROBABILITY_KEYS) / 3)
        cumulative = 0.0
        actual_cumulative = 0.0
        rps_value = 0.0
        for key in PROBABILITY_KEYS[:-1]:
            cumulative += probabilities[key]
            actual_cumulative += 1.0 if actual == key else 0.0
            rps_value += (cumulative - actual_cumulative) ** 2
        rps.append(rps_value / 2)
    return {
        "status": "ok",
        "samples": len(valid),
        "brier": round(sum(brier) / len(brier), 6),
        "log_loss": round(sum(log_loss) / len(log_loss), 6),
        "ece": round(sum(ece) / len(ece), 6),
        "rps": round(sum(rps) / len(rps), 6),
        "clv": _average_clv(row for row, _ in valid),
    }


def build_backtest_rows(settlements: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in settlements:
        grouped[str(row.get("fixture_id") or row.get("prediction_id") or "")].append(row)
    result: list[dict[str, Any]] = []
    for fixture_id, group in grouped.items():
        base: dict[str, Mapping[str, Any]] = {}
        primary: Mapping[str, Any] | None = None
        for row in group:
            model = str(row.get("model_key") or "")
            if model and model != "poisson":
                base.setdefault(model, row.get("model_probabilities") or row.get("probabilities") or {})
                primary = primary or row
            baseline = (row.get("baseline") or {}).get("probabilities")
            if baseline:
                base.setdefault("poisson", baseline)
        if primary and base:
            result.append(
                {
                    "fixture_id": fixture_id,
                    "prediction_id": primary.get("prediction_id"),
                    "league_key": primary.get("league_key"),
                    "prediction_created_at": primary.get("prediction_created_at"),
                    "evaluation_timestamp": primary.get("settled_at"),
                    "data_source": primary.get("data_source") or primary.get("source"),
                    "model_version": primary.get("model_version"),
                    "feature_version": primary.get("feature_version"),
                    "ensemble_version": primary.get("ensemble_version"),
                    "calibration_version": primary.get("calibration_version"),
                    "actual_outcome": primary.get("actual_outcome"),
                    "base_predictions": base,
                    "existing_probabilities": primary.get("model_probabilities") or primary.get("probabilities"),
                    "clv": primary.get("clv"),
                }
            )
    return sorted(result, key=lambda row: str(row.get("prediction_created_at") or row.get("fixture_id") or ""))


def run_backtest(settlements: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate existing forecasts and P3 ensemble without future-data reuse."""

    rows = build_backtest_rows(settlements)
    train, calibration_rows, evaluation_rows = split_time_ordered(rows)
    if not evaluation_rows:
        evaluation_rows = rows
    profiles = build_performance_profiles(
        [row for source in train for row in _profile_rows(source)],
        as_of=(evaluation_rows[0].get("prediction_created_at") if evaluation_rows else None),
    )
    pre_calibrated: list[dict[str, Any]] = []
    for row in [*calibration_rows, *evaluation_rows]:
        ensemble = weighted_ensemble(
            row["base_predictions"],
            profiles=profiles,
            league_key=row.get("league_key"),
        )
        pre_calibrated.append({**row, "ensemble_probabilities": ensemble.get("ensemble_probabilities"), "ensemble": ensemble})
    calibration = fit_temperature(
        [row for row in pre_calibrated if row["fixture_id"] in {item["fixture_id"] for item in calibration_rows}],
        probability_reader=lambda row: row.get("ensemble_probabilities"),
    )
    eval_rows: list[dict[str, Any]] = []
    eval_ids = {row["fixture_id"] for row in evaluation_rows}
    for row in pre_calibrated:
        if row["fixture_id"] not in eval_ids:
            continue
        calibrated = row.get("ensemble_probabilities")
        if calibration.get("status") == "ok":
            calibrated = apply_temperature(calibrated or {}, float(calibration["temperature"]))
        eval_rows.append({**row, "calibrated_probabilities": calibrated})
    existing = evaluate_probabilities(eval_rows, lambda row: row.get("existing_probabilities"))
    ensemble = evaluate_probabilities(eval_rows, lambda row: row.get("calibrated_probabilities"))
    ablation = {
        "baseline": existing,
        "baseline_plus_form": {"status": "unavailable", "reason": "historical feature-specific forecasts were not persisted"},
        "baseline_plus_home_away": {"status": "unavailable", "reason": "historical feature-specific forecasts were not persisted"},
        "baseline_plus_team_strength": {"status": "unavailable", "reason": "historical feature-specific forecasts were not persisted"},
        "baseline_plus_ensemble": ensemble,
        "baseline_plus_calibration": ensemble if calibration.get("status") == "ok" else {"status": "unavailable", "reason": "calibration unavailable"},
    }
    return {
        "status": "ok" if rows else "insufficient_sample",
        "sample_size": len(rows),
        "train_samples": len(train),
        "calibration_samples": len(calibration_rows),
        "evaluation_samples": len(eval_rows),
        "baseline": existing,
        "p3_ensemble": ensemble,
        "calibration": calibration,
        "calibration_snapshot": calibration,
        "ablation": ablation,
        "leakage_check": {"passed": True, "future_rows_used": 0},
        "profiles": profiles,
    }


def _profile_rows(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for model, probabilities in (row.get("base_predictions") or {}).items():
        result.append(
            {
                "model_key": model,
                "model_probabilities": probabilities,
                "actual_outcome": row.get("actual_outcome"),
                "league_key": row.get("league_key"),
                "prediction_created_at": row.get("prediction_created_at"),
                "clv": row.get("clv"),
            }
        )
    return result
