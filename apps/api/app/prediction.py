"""Deterministic, inspectable pre-match probability model."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Iterable


MODEL_VERSION = "poisson-pure-v0.2"
MAX_GOALS = 8
# Dixon-Coles low-score correlation. Negative rho shifts probability mass
# from 1-0/0-1 into 0-0/1-1 (independent Poisson underestimates draws).
POISSON_DC_RHO = -0.10


def _dixon_coles_tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * POISSON_DC_RHO
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * POISSON_DC_RHO
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * POISSON_DC_RHO
    if home_goals == 1 and away_goals == 1:
        return 1.0 - POISSON_DC_RHO
    return 1.0


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


def asian_handicap_from_expected_goals(
    home_xg: object,
    away_xg: object,
    handicap: object,
) -> dict[str, float] | None:
    """Derive a home-team Asian handicap settlement distribution from frozen xG."""

    try:
        home_rate = float(home_xg)
        away_rate = float(away_xg)
        line = float(handicap)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in (home_rate, away_rate)):
        return None
    try:
        quarter = round(line * 4)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(line) or not math.isclose(line * 4, quarter, abs_tol=1e-8):
        return None

    score_matrix = [
        (home_goals, away_goals, _poisson(home_rate, home_goals) * _poisson(away_rate, away_goals))
        for home_goals in range(MAX_GOALS)
        for away_goals in range(MAX_GOALS)
    ]
    matrix_total = sum(item[2] for item in score_matrix)
    if not math.isfinite(matrix_total) or matrix_total <= 0:
        return None
    result = {key: 0.0 for key in ("full_win", "half_win", "push", "half_loss", "full_loss")}
    for home_goals, away_goals, probability in score_matrix:
        settlement = settle_asian_handicap(home_goals - away_goals, line)
        for key, weight in settlement.items():
            result[key] += probability / matrix_total * weight
    return {key: round(value, 4) for key, value in result.items()}


def predict(fixture: dict, context: dict) -> dict:
    """Generate a timestamped 1X2 and Asian handicap analysis."""

    recent = context["recent_form"]
    lineup = context["lineup"]
    odds = context.get("odds")

    home_form = float(recent.get("home_points_per_game") or 0.0) / 1.5
    away_form = float(recent.get("away_points_per_game") or 0.0) / 1.5
    impact = context.get("player_impact") or {}
    home_retention = _attack_retention(impact.get("home"), lineup.get("home_strength"))
    away_retention = _attack_retention(impact.get("away"), lineup.get("away_strength"))
    home_xg = min(2.8, max(0.45, 1.38 * home_form * home_retention + 0.22))
    away_xg = min(2.5, max(0.35, 1.08 * away_form * away_retention + 0.12))
    # Elo 先验：历史交锋演化出的实力差微调预期进球（数据缺失时不生效）。
    elo = context.get("elo") or {}
    home_elo = elo.get(str((fixture.get("home_team") or {}).get("name") or ""))
    away_elo = elo.get(str((fixture.get("away_team") or {}).get("name") or ""))
    if isinstance(home_elo, (int, float)) and isinstance(away_elo, (int, float)):
        from .elo import expected_goal_shift

        home_shift, away_shift = expected_goal_shift(float(home_elo), float(away_elo))
        home_xg = min(3.2, max(0.35, home_xg + home_shift))
        away_xg = min(2.8, max(0.3, away_xg + away_shift))

    score_matrix: list[tuple[int, int, float]] = []
    for home_goals in range(MAX_GOALS):
        for away_goals in range(MAX_GOALS):
            score_matrix.append(
                (home_goals, away_goals, _poisson(home_xg, home_goals) * _poisson(away_xg, away_goals))
            )
    matrix_total = sum(item[2] for item in score_matrix)
    score_matrix = [(home, away, probability / matrix_total) for home, away, probability in score_matrix]

    # Dixon-Coles low-score correction: independent Poisson underestimates
    # 0-0/1-1 and overstates 1-0/0-1. Negative rho moves mass accordingly.
    matrix_total = sum(probability * max(0.0, _dixon_coles_tau(home, away, home_xg, away_xg)) for home, away, probability in score_matrix)
    score_matrix = [
        (home, away, probability * max(0.0, _dixon_coles_tau(home, away, home_xg, away_xg)) / matrix_total)
        for home, away, probability in score_matrix
    ]

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
    over_probability = sum(probability for home, away, probability in score_matrix if home + away > 2.5)
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
        "totals_forecast": {
            "line": 2.5,
            "over": round(over_probability, 4),
            "under": round(1.0 - over_probability, 4),
        },
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

