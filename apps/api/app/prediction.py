"""Deterministic, inspectable pre-match probability model."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Iterable


MODEL_VERSION = "poisson-pure-v0.2"
MAX_GOALS = 8


def _poisson(lam: float, goals: int) -> float:
    return math.exp(-lam) * lam**goals / math.factorial(goals)


def _normalize(values: Iterable[float]) -> list[float]:
    items = list(values)
    total = sum(items)
    return [value / total for value in items]


def settle_asian_handicap(goal_difference: int, handicap: float) -> dict[str, float]:
    """Return settlement weights for a home-team Asian handicap position."""

    quarter = round(handicap * 4)
    if not math.isclose(handicap * 4, quarter, abs_tol=1e-8):
        raise ValueError("Asian handicap must use quarter-goal increments")

    if abs(quarter) % 2 == 1:
        lower = math.floor(handicap * 2) / 2
        upper = math.ceil(handicap * 2) / 2
        legs = (lower, upper)
    else:
        legs = (handicap,)

    outcomes: dict[str, float] = {key: 0.0 for key in ("full_win", "half_win", "push", "half_loss", "full_loss")}
    leg_results = []
    for leg in legs:
        adjusted = goal_difference + leg
        leg_results.append("win" if adjusted > 0 else "loss" if adjusted < 0 else "push")

    if len(leg_results) == 1:
        outcomes[{"win": "full_win", "loss": "full_loss", "push": "push"}[leg_results[0]]] = 1.0
    elif leg_results == ["win", "push"] or leg_results == ["push", "win"]:
        outcomes["half_win"] = 1.0
    elif leg_results == ["loss", "push"] or leg_results == ["push", "loss"]:
        outcomes["half_loss"] = 1.0
    elif all(result == "win" for result in leg_results):
        outcomes["full_win"] = 1.0
    elif all(result == "loss" for result in leg_results):
        outcomes["full_loss"] = 1.0
    else:
        outcomes["push"] = 1.0
    return outcomes


def predict(fixture: dict, context: dict) -> dict:
    """Generate a timestamped 1X2 and Asian handicap analysis."""

    recent = context["recent_form"]
    lineup = context["lineup"]
    odds = context.get("odds")

    home_form = recent["home_points_per_game"] / 1.5
    away_form = recent["away_points_per_game"] / 1.5
    impact = context.get("player_impact") or {}
    home_retention = _attack_retention(impact.get("home"), lineup.get("home_strength"))
    away_retention = _attack_retention(impact.get("away"), lineup.get("away_strength"))
    home_xg = min(2.8, max(0.45, 1.38 * home_form * home_retention + 0.22))
    away_xg = min(2.5, max(0.35, 1.08 * away_form * away_retention + 0.12))

    score_matrix: list[tuple[int, int, float]] = []
    for home_goals in range(MAX_GOALS):
        for away_goals in range(MAX_GOALS):
            score_matrix.append(
                (home_goals, away_goals, _poisson(home_xg, home_goals) * _poisson(away_xg, away_goals))
            )
    matrix_total = sum(item[2] for item in score_matrix)
    score_matrix = [(home, away, probability / matrix_total) for home, away, probability in score_matrix]

    model_1x2 = [
        sum(probability for home, away, probability in score_matrix if home > away),
        sum(probability for home, away, probability in score_matrix if home == away),
        sum(probability for home, away, probability in score_matrix if home < away),
    ]
    # Market odds are intentionally excluded from the forecast. They are evaluated
    # later by market_decision.py as an independent assessment layer.
    forecast_probabilities = _normalize(model_1x2)

    handicap = odds.get("asian_handicap") if odds else None
    handicap_result = None
    if handicap is not None:
        handicap_result = {key: 0.0 for key in ("full_win", "half_win", "push", "half_loss", "full_loss")}
        for home, away, probability in score_matrix:
            settlement = settle_asian_handicap(home - away, handicap)
            for key, weight in settlement.items():
                handicap_result[key] += probability * weight
        handicap_result = {key: round(value, 4) for key, value in handicap_result.items()}

    top_scores = sorted(score_matrix, key=lambda item: item[2], reverse=True)[:3]
    evidence_count = 4 + int(bool(odds)) + int(lineup["confirmed"])
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "fixture_id": fixture["id"],
        "created_at": created_at,
        "phase": "confirmed_lineup" if lineup["confirmed"] else "preliminary",
        "model_version": MODEL_VERSION,
        "probabilities": {
            "home": round(forecast_probabilities[0], 4),
            "draw": round(forecast_probabilities[1], 4),
            "away": round(forecast_probabilities[2], 4),
        },
        "model_probabilities": {
            "home": round(forecast_probabilities[0], 4),
            "draw": round(forecast_probabilities[1], 4),
            "away": round(forecast_probabilities[2], 4),
        },
        "expected_goals": {"home": round(home_xg, 2), "away": round(away_xg, 2)},
        "top_scores": [
            {"score": f"{home}-{away}", "probability": round(probability, 4)}
            for home, away, probability in top_scores
        ],
        "asian_handicap": {
            "line": handicap,
            "home_settlement": handicap_result,
        }
        if handicap_result
        else None,
        "confidence": "较高" if evidence_count == 6 else "中等" if evidence_count >= 5 else "有限",
        "evidence": {
            "recent_form_at": recent["updated_at"],
            "availability_at": context["availability"]["updated_at"],
            "lineup_at": lineup["updated_at"],
            "odds_at": odds["updated_at"] if odds else None,
            "is_demo": fixture["is_demo"],
        },
    }


def _attack_retention(impact: dict | None, legacy_strength: object) -> float:
    if impact:
        if impact.get("data_status") == "insufficient":
            return 1.0
        try:
            return min(1.0, max(0.5, float(impact.get("attack_retention"))))
        except (TypeError, ValueError):
            return 1.0
    try:
        return min(1.0, max(0.5, float(legacy_strength)))
    except (TypeError, ValueError):
        return 1.0

