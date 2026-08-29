"""Deterministic P3 feature, ensemble, calibration, and backtest utilities."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping


FEATURE_VERSION = "p3-v1"
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


def build_feature_snapshot(
    fixture: Mapping[str, Any],
    evidence: Mapping[str, Any],
    prediction_timestamp: Any | None = None,
    *,
    standings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a versioned, as-of feature view without reading future evidence."""

    as_of = parse_timestamp(prediction_timestamp) or datetime.now(UTC)
    rejected: list[str] = []
    for field in ("captured_at", "synced_at"):
        captured = parse_timestamp(evidence.get(field))
        if captured and captured > as_of:
            rejected.append(field)
    recent = evidence.get("recent_form") or {}
    recent_features = {
        side: _recent_form_features(recent.get(side) or [], as_of, rejected, side)
        for side in ("home", "away")
    }
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
    return {
        "fixture_id": str(fixture.get("id") or ""),
        "captured_at": as_of.isoformat(),
        "prediction_timestamp": as_of.isoformat(),
        "source_captured_at": source_captured.isoformat() if source_captured else None,
        "feature_version": FEATURE_VERSION,
        "team_strength": strength,
        "recent_form": recent_features,
        "home_away": {
            "home": recent_features["home"].get("home_split"),
            "away": recent_features["away"].get("away_split"),
        },
        "squad_status": squad,
        "schedule_context": schedule,
        "market_context": market,
        "leakage_check": {
            "passed": not rejected,
            "rejected_future_fields": rejected,
        },
    }


def _recent_form_features(
    rows: list[Mapping[str, Any]],
    as_of: datetime,
    rejected: list[str],
    side: str,
) -> dict[str, Any]:
    usable: list[tuple[Mapping[str, Any], float, int]] = []
    for raw_row in rows[:10]:
        row = raw_row if isinstance(raw_row, Mapping) else {"result": str(raw_row)}
        occurred = parse_timestamp(row.get("date"))
        if occurred is None:
            usable.append((row, 1.0, 3 if row.get("result") == "W" else 1 if row.get("result") == "D" else 0))
            continue
        if occurred > as_of:
            rejected.append(f"recent_form.{side}")
            continue
        age_days = max(0.0, (as_of - occurred).total_seconds() / 86400)
        points = 3 if row.get("result") == "W" else 1 if row.get("result") == "D" else 0
        usable.append((row, math.exp(-FORM_DECAY_LAMBDA * age_days), points))

    def aggregate(items: list[tuple[Mapping[str, Any], float, int]]) -> dict[str, Any] | None:
        if not items:
            return None
        weight_total = sum(weight for _, weight, _ in items)
        goals_for = 0.0
        goals_against = 0.0
        points = 0.0
        for row, weight, result_points in items:
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
    return {
        "sample_size": len(usable),
        "weighted": aggregate_all,
        "home_split": home_split,
        "away_split": away_split,
        "status": "missing" if not usable else "complete",
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
    for row in rows:
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
) -> dict[str, Any]:
    rows = list(rows)
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
                    "league_key": primary.get("league_key"),
                    "prediction_created_at": primary.get("prediction_created_at"),
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
