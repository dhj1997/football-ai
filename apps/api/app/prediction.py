"""Deterministic, inspectable pre-match probability model."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Iterable


MODEL_VERSION = "poisson-pure-v0.2"
MAX_GOALS = 8
# Dixon-Coles low-score correlation. Negative rho shifts probability mass
# from 1-0/0-1 into 0-0/1-1 (independent Poisson underestimates draws).
POISSON_DC_RHO = -0.10
# 每联赛 xG 基线系数：历史赛果拟合值优先（model_fitting），无拟合时用内置常量。
DEFAULT_HOME_XG_BASELINE = 1.38
DEFAULT_AWAY_XG_BASELINE = 1.08

_FITTED_PARAMS_PROVIDER: Callable[[], dict | None] | None = None


def set_fitted_params_provider(provider: Callable[[], dict | None] | None) -> None:
    """Inject the fitted-parameter source (model registry) at startup."""

    global _FITTED_PARAMS_PROVIDER
    _FITTED_PARAMS_PROVIDER = provider


def _league_fitted_params(league_key: Any) -> dict | None:
    if _FITTED_PARAMS_PROVIDER is None:
        return None
    try:
        data = _FITTED_PARAMS_PROVIDER() or {}
        entry = (data.get("leagues") or {}).get(str(league_key or "").casefold())
        if not entry or entry.get("status") != "ok":
            # 不足样本的联赛没有可用参数：不注入、不挂拟合版本后缀。
            return None
        return {**entry, "fitted_version": data.get("fitted_version")}
    except Exception:
        return None


def _dixon_coles_tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float = POISSON_DC_RHO) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
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
    fitted = _league_fitted_params(fixture.get("league_key"))
    baseline_home = float(fitted.get("home_xg")) if fitted and fitted.get("home_xg") else DEFAULT_HOME_XG_BASELINE
    baseline_away = float(fitted.get("away_xg")) if fitted and fitted.get("away_xg") else DEFAULT_AWAY_XG_BASELINE
    rho = max(-0.2, min(0.0, float(fitted.get("rho")))) if fitted and fitted.get("rho") is not None else POISSON_DC_RHO
    home_xg = min(2.8, max(0.45, baseline_home * home_form * home_retention + 0.22))
    away_xg = min(2.5, max(0.35, baseline_away * away_form * away_retention + 0.12))
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
    matrix_total = sum(probability * max(0.0, _dixon_coles_tau(home, away, home_xg, away_xg, rho)) for home, away, probability in score_matrix)
    score_matrix = [
        (home, away, probability * max(0.0, _dixon_coles_tau(home, away, home_xg, away_xg, rho)) / matrix_total)
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

    top_scores = sorted(score_matrix, key=lambda item: item[2], reverse=True)[:6]
    over_probability = sum(probability for home, away, probability in score_matrix if home + away > 2.5)
    evidence_count = 4 + int(bool(odds)) + int(lineup["confirmed"])
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    # 进球数/双方进球/让球多线/半场维度：全部由同一比分矩阵确定性派生。
    totals_lines: dict[str, dict[str, float]] = {}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        over = sum(probability for home, away, probability in score_matrix if home + away > line)
        push = sum(probability for home, away, probability in score_matrix if home + away == line)
        totals_lines[str(line)] = {
            "over": round(over, 4),
            "push": round(push, 4),
            "under": round(1.0 - over - push, 4),
        }
    p_home_zero = sum(probability for home, _, probability in score_matrix if home == 0)
    p_away_zero = sum(probability for _, away, probability in score_matrix if away == 0)
    p_both_zero = sum(probability for home, away, probability in score_matrix if home == 0 and away == 0)
    btts_yes = max(0.0, 1.0 - p_home_zero - p_away_zero + p_both_zero)
    handicap_lines: dict[str, dict[str, float]] = {}
    for line in (-1.5, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
        line_result = {key: 0.0 for key in ("full_win", "half_win", "push", "half_loss", "full_loss")}
        for home, away, probability in score_matrix:
            settlement = settle_asian_handicap(home - away, line)
            for key, weight in settlement.items():
                line_result[key] += probability * weight
        # 让球胜率口径：赢半也算覆盖（三元恒和为 1）。
        handicap_lines[str(line)] = {
            "home_cover": round(line_result["full_win"] + line_result["half_win"], 4),
            "push": round(line_result["push"], 4),
            "away_cover": round(line_result["full_loss"] + line_result["half_loss"], 4),
        }

    # 半场近似：半场 xG 约为全场的 45%，独立泊松（明确标注估算口径）。
    ht_lambda_scale = 0.45
    ht_home_xg = home_xg * ht_lambda_scale
    ht_away_xg = away_xg * ht_lambda_scale
    ht_grid_total = sum(
        _poisson(ht_home_xg, h) * _poisson(ht_away_xg, a)
        for h in range(6)
        for a in range(6)
    )
    ht_home_win = sum(
        _poisson(ht_home_xg, h) * _poisson(ht_away_xg, a)
        for h in range(6)
        for a in range(6)
        if h > a
    ) / ht_grid_total
    ht_draw = sum(
        _poisson(ht_home_xg, h) * _poisson(ht_away_xg, a)
        for h in range(6)
        for a in range(6)
        if h == a
    ) / ht_grid_total
    half_time_market = {
        "home": round(ht_home_win, 4),
        "draw": round(ht_draw, 4),
        "away": round(max(0.0, 1.0 - ht_home_win - ht_draw), 4),
        "method": "independent_poisson_45pct_xg_estimate",
    }
    markets_detail = {
        "totals_lines": totals_lines,
        "btts": {"yes": round(btts_yes, 4), "no": round(1.0 - btts_yes, 4)},
        "handicap_lines": handicap_lines,
        "half_time": half_time_market,
        "score_matrix_top": [
            {"score": f"{home}-{away}", "probability": round(probability, 4)}
            for home, away, probability in top_scores
        ],
        "is_derived": True,
    }
    return {
        "id": str(uuid.uuid4()),
        "fixture_id": fixture["id"],
        "created_at": created_at,
        "phase": "confirmed_lineup" if lineup["confirmed"] else "preliminary",
        "model_version": f"{MODEL_VERSION}+{fitted['fitted_version']}" if fitted else MODEL_VERSION,
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
        "markets_detail": markets_detail,
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

