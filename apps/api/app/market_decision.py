"""Deterministic market math, no-bet reasons, and bounded risk sizing."""

from datetime import UTC, datetime, timedelta
from copy import deepcopy
from typing import Any

from .prompt_contract import EVIDENCE_CONTRACT_VERSION


MIN_EXPECTED_EDGE = 0.03
MIN_FORECAST_CONFIDENCE = 0.60
MIN_STAKE_FRACTION = 0.10
MAX_STAKE_FRACTION = 0.25
ODDS_MAX_AGE = timedelta(hours=3)
REASON_TEXT = {
    "ai_no_bet": "AI基于当前证据不建议下注",
    "negative_edge": "模型概率未超过当前赔率所需的最低优势",
    "low_confidence": "预测置信度不足",
    "lineup_unconfirmed": "首发阵容尚未确认",
    "stale_odds": "赔率已过期或缺少可靠更新时间",
    "missing_player_data": "关键球员数据不足",
    "no_matching_market": "没有与预测匹配的可用赔率市场",
    "risk_limit": "模拟账户风险额度不足",
    "model_disagreement": "模型间概率分歧过大",
}

WARNING_TEXT = {
    "low_confidence": "预测置信度偏低，已由AI明确选择进入后端校验",
    "lineup_unconfirmed": "首发阵容尚未确认，公布后将重新分析",
}


def apply_market_decision(
    prediction: dict[str, Any],
    context: dict[str, Any],
    model_disagreement: float | None = None,
    risk_limited: bool = False,
) -> dict[str, Any]:
    """Attach forecast, market assessment, and execution decision layers."""

    # Decisions are derived views. Never mutate the persisted forecast object.
    prediction = deepcopy(prediction)
    probabilities = prediction.get("model_probabilities") or prediction.get("probabilities") or {}
    predicted_outcome = max(probabilities, key=probabilities.get) if probabilities else None
    assessment = assess_markets(prediction, context.get("odds"))
    assessment["odds_snapshot_id"] = prediction.get("odds_snapshot_id")
    model_recommendation = prediction.get("model_recommendation") or {}
    candidate = max(assessment["markets"], key=lambda item: item["expected_edge"], default=None)
    confidence = _forecast_confidence(prediction)
    reason_codes: list[str] = []
    ai_completed = (prediction.get("ai") or {}).get("status") == "completed"
    forecast_evidence_current = (prediction.get("ai") or {}).get("evidence_version") == EVIDENCE_CONTRACT_VERSION
    lineup_confirmed = bool((context.get("lineup") or {}).get("confirmed")) and prediction.get("phase") != "preliminary"
    impact = context.get("player_impact") or {}
    player_data_missing = not forecast_evidence_current or not impact or any(
        (impact.get(side) or {}).get("data_status") == "insufficient"
        for side in ("home", "away")
    )
    warning_codes = [] if lineup_confirmed else ["lineup_unconfirmed"]

    if not assessment["markets"]:
        reason_codes.append("no_matching_market")
    if assessment["odds_status"] != "fresh":
        reason_codes.append("stale_odds")
    if player_data_missing:
        reason_codes.append("missing_player_data")
    if not ai_completed:
        reason_codes.append("low_confidence")
    elif confidence < MIN_FORECAST_CONFIDENCE:
        warning_codes.append("low_confidence")
    if candidate and candidate["expected_edge"] < MIN_EXPECTED_EDGE:
        reason_codes.append("negative_edge")
    if risk_limited:
        reason_codes.append("risk_limit")
    reason_codes = list(dict.fromkeys(reason_codes))
    warning_codes = list(dict.fromkeys(warning_codes))

    insufficient = "no_matching_market" in reason_codes
    status = "insufficient_data" if insufficient else "no_bet" if reason_codes else "bet"
    stake_fraction = _stake_fraction(candidate) if ai_completed and candidate else 0.0
    uncertainty = _uncertainty(
        confidence,
        lineup_confirmed,
        impact,
    )
    prediction["forecast_confidence"] = round(confidence, 4)
    decision = {
        "status": status,
        "market": candidate["market"] if status == "bet" and candidate else "no_bet",
        "selection": candidate["selection"] if status == "bet" and candidate else "none",
        "considered_market": candidate["market"] if candidate else None,
        "considered_selection": candidate["selection"] if candidate else None,
        "price": candidate["price"] if candidate else None,
        "edge": (
            candidate.get("edge")
            if candidate
            else None
        ),
        "ev": candidate.get("ev") if candidate else None,
        "expected_edge": candidate["expected_edge"] if candidate else None,
        "model_confidence": round(confidence, 4),
        "uncertainty": uncertainty,
        "stake_fraction": stake_fraction,
        "reason_codes": reason_codes,
        "reason": "；".join(REASON_TEXT[code] for code in reason_codes) if reason_codes else "赔率优势和证据质量达到模拟执行标准",
        "warning_codes": warning_codes,
        "warning": "；".join(WARNING_TEXT[code] for code in warning_codes) if warning_codes else None,
        "model_recommendation_status": model_recommendation.get("status") or "no_bet",
        "is_deterministic": True,
        "real_money_execution": False,
    }
    prediction["forecast"] = {
        "predicted_outcome": predicted_outcome,
        "probabilities": deepcopy(probabilities),
        "model_probabilities": deepcopy(probabilities),
        "asian_handicap": prediction.get("asian_handicap_forecast") or _handicap_forecast(assessment["markets"]),
    }
    prediction["predicted_outcome"] = predicted_outcome
    prediction["market_assessment"] = assessment
    prediction["decision"] = decision
    prediction["risk_gate"] = {
        "status": "allowed" if status == "bet" else "blocked",
        "reason_codes": list(reason_codes),
        "confidence": decision["model_confidence"],
        "data_completeness": prediction.get("data_completeness"),
        "odds_status": assessment.get("odds_status"),
        "lineup_confirmed": lineup_confirmed,
        "risk_limits": {"min_stake_fraction": MIN_STAKE_FRACTION, "max_stake_fraction": MAX_STAKE_FRACTION},
        "drawdown": None,
    }
    prediction["portfolio_selection"] = {
        "status": "candidate" if status == "bet" else "not_selected",
        "market": decision["market"],
        "selection": decision["selection"],
        "expected_edge": decision["expected_edge"],
    }
    prediction["recommendation"] = {
        "market": decision["market"],
        "selection": decision["selection"],
        "confidence": decision["model_confidence"],
        "recommended_stake_fraction": decision["stake_fraction"],
        "reason": decision["reason"],
        "reason_codes": decision["reason_codes"],
        "decision_status": decision["status"],
        "is_deterministic": True,
    }
    return prediction


def _recommended_market(
    markets: list[dict[str, Any]],
    recommendation: dict[str, Any],
) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in markets
            if row["market"] == recommendation.get("market")
            and row["selection"] == recommendation.get("selection")
        ),
        None,
    )


def assess_markets(prediction: dict[str, Any], odds: Any) -> dict[str, Any]:
    """Calculate inspectable 1X2 and Asian-handicap values for every priced side."""

    if not isinstance(odds, dict):
        return {"odds_status": "missing", "odds_updated_at": None, "markets": []}
    rows: list[dict[str, Any]] = []
    probabilities = prediction.get("model_probabilities") or prediction.get("probabilities") or {}
    one_x_two_prices = {key: _positive_price(odds.get(key)) for key in ("home", "draw", "away")}
    if all(one_x_two_prices.values()):
        implied = {key: 1 / price for key, price in one_x_two_prices.items() if price}
        overround = sum(implied.values())
        for selection, price in one_x_two_prices.items():
            model_probability = _probability(probabilities.get(selection))
            if price and model_probability is not None:
                rows.append(
                    _market_row(
                        "1x2",
                        selection,
                        price,
                        model_probability,
                        implied[selection] / overround,
                        model_probability * price - 1,
                        odds.get("bookmaker"),
                    )
                )

    handicap = prediction.get("asian_handicap") or {}
    settlement = handicap.get("home_settlement") or {}
    home_price = _positive_price(odds.get("asian_handicap_home_odd"))
    away_price = _positive_price(odds.get("asian_handicap_away_odd"))
    line = odds.get("asian_handicap")
    forecast_line = handicap.get("line")
    matching_line = (
        forecast_line is not None
        and line is not None
        and abs(float(forecast_line) - float(line)) <= 1e-8
    )
    if settlement and matching_line and home_price and away_price:
        home_weights, cover_probabilities, probability_source = _handicap_market_weights(
            prediction,
            settlement,
            float(line),
        )
        asian_implied = {"home_handicap": 1 / home_price, "away_handicap": 1 / away_price}
        asian_overround = sum(asian_implied.values())
        for selection, price in (("home_handicap", home_price), ("away_handicap", away_price)):
            weights = _settlement_weights(home_weights, selection)
            coverage = cover_probabilities[selection]
            edge = _settlement_edge(weights, price)
            rows.append(
                {
                    **_market_row(
                        "asian_handicap",
                        selection,
                        price,
                        coverage,
                        asian_implied[selection] / asian_overround,
                        edge,
                        odds.get("bookmaker"),
                    ),
                    "line": float(line),
                    "settlement": {key: round(value, 4) for key, value in weights.items()},
                    "probability_source": probability_source,
                }
            )
    return {
        "odds_status": "stale" if _odds_stale(odds.get("updated_at")) else "fresh",
        "odds_updated_at": odds.get("updated_at"),
        "bookmaker": odds.get("bookmaker"),
        "markets": rows,
    }


def _market_row(
    market: str,
    selection: str,
    price: float,
    model_probability: float,
    de_vig_probability: float,
    expected_edge: float,
    bookmaker: Any,
) -> dict[str, Any]:
    return {
        "market": market,
        "selection": selection,
        "line": None,
        "bookmaker": bookmaker,
        "price": round(price, 4),
        "break_even_probability": round(1 / price, 4),
        "de_vig_probability": round(de_vig_probability, 4),
        "market_probability": round(de_vig_probability, 4),
        "model_probability": round(model_probability, 4),
        "edge": round(model_probability - de_vig_probability, 4),
        "ev": round(expected_edge, 4),
        "expected_edge": round(expected_edge, 4),
    }


def _settlement_weights(home: dict[str, Any], selection: str) -> dict[str, float]:
    if selection == "away_handicap":
        return {
            "full_win": float(home.get("full_loss") or 0),
            "half_win": float(home.get("half_loss") or 0),
            "push": float(home.get("push") or 0),
            "half_loss": float(home.get("half_win") or 0),
            "full_loss": float(home.get("full_win") or 0),
        }
    return {key: float(home.get(key) or 0) for key in ("full_win", "half_win", "push", "half_loss", "full_loss")}


def _handicap_market_weights(
    prediction: dict[str, Any],
    baseline: dict[str, Any],
    line: float,
) -> tuple[dict[str, float], dict[str, float], str]:
    baseline_weights = _settlement_weights(baseline, "home_handicap")
    forecast = prediction.get("asian_handicap_forecast") or {}
    forecast_line = forecast.get("line")
    home_cover = _probability(forecast.get("home_cover_probability"))
    away_cover = _probability(forecast.get("away_cover_probability"))
    forecast_matches = (
        bool(forecast.get("available"))
        and forecast_line is not None
        and abs(float(forecast_line) - line) <= 1e-8
        and home_cover is not None
        and away_cover is not None
        and home_cover + away_cover > 0
    )
    if not forecast_matches:
        return (
            baseline_weights,
            {
                "home_handicap": baseline_weights["full_win"] + baseline_weights["half_win"],
                "away_handicap": baseline_weights["full_loss"] + baseline_weights["half_loss"],
            },
            "poisson_baseline",
        )

    total = home_cover + away_cover
    home_probability = home_cover / total
    away_probability = away_cover / total
    adjusted = _reweight_settlement_direction(
        baseline_weights,
        home_probability,
        away_probability,
    )
    return (
        adjusted,
        {"home_handicap": home_probability, "away_handicap": away_probability},
        "model_asian_handicap_forecast",
    )


def _reweight_settlement_direction(
    baseline: dict[str, float],
    home_cover_probability: float,
    away_cover_probability: float,
) -> dict[str, float]:
    push = min(1.0, max(0.0, float(baseline.get("push") or 0)))
    directional_mass = 1 - push
    positive_target = directional_mass * home_cover_probability
    negative_target = directional_mass * away_cover_probability
    positive = _split_mass(
        positive_target,
        float(baseline.get("full_win") or 0),
        float(baseline.get("half_win") or 0),
    )
    negative = _split_mass(
        negative_target,
        float(baseline.get("half_loss") or 0),
        float(baseline.get("full_loss") or 0),
    )
    return {
        "full_win": positive[0],
        "half_win": positive[1],
        "push": push,
        "half_loss": negative[0],
        "full_loss": negative[1],
    }


def _split_mass(target: float, first: float, second: float) -> tuple[float, float]:
    source = first + second
    if source <= 0:
        return target, 0.0
    return target * first / source, target * second / source


def _settlement_edge(weights: dict[str, float], price: float) -> float:
    expected_return = (
        weights["full_win"] * price
        + weights["half_win"] * (price + 1) / 2
        + weights["push"]
        + weights["half_loss"] * 0.5
    )
    return expected_return - 1


def _stake_fraction(candidate: dict[str, Any]) -> float:
    edge = float(candidate["expected_edge"])
    if edge < MIN_EXPECTED_EDGE:
        return 0.0
    proportional = MIN_STAKE_FRACTION + max(edge - MIN_EXPECTED_EDGE, 0.0)
    return round(min(MAX_STAKE_FRACTION, proportional), 4)


def _forecast_confidence(prediction: dict[str, Any]) -> float:
    direct = _probability(prediction.get("forecast_confidence"))
    if direct is not None:
        return direct
    legacy = _probability((prediction.get("model_recommendation") or prediction.get("recommendation") or {}).get("confidence"))
    return legacy if legacy is not None else 0.0


def _uncertainty(
    confidence: float,
    lineup_confirmed: bool,
    impact: dict[str, Any],
) -> float:
    value = 1 - confidence
    if not lineup_confirmed:
        value += 0.1
    if any((impact.get(side) or {}).get("data_status") != "complete" for side in ("home", "away")):
        value += 0.1
    return round(min(1.0, max(0.0, value)), 4)


def _handicap_forecast(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    handicap = [row for row in rows if row["market"] == "asian_handicap"]
    if not handicap:
        return None
    return {
        "line": handicap[0].get("line"),
        "home_cover_probability": next((row["model_probability"] for row in handicap if row["selection"] == "home_handicap"), None),
        "away_cover_probability": next((row["model_probability"] for row in handicap if row["selection"] == "away_handicap"), None),
    }


def _odds_stale(value: Any) -> bool:
    if not value:
        return True
    try:
        updated_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        updated_at = updated_at.replace(tzinfo=UTC) if updated_at.tzinfo is None else updated_at.astimezone(UTC)
    except ValueError:
        return True
    age = datetime.now(UTC) - updated_at
    return age < timedelta(0) or age > ODDS_MAX_AGE


def _positive_price(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 1 else None


def _probability(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 1 else None
