"""Pure deterministic portfolio, candidate, and risk calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping


ACTIVE_STATUSES = {"placed", "pending", "executed", "selected"}


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _probability(value: Any) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and 0 <= parsed <= 1 else None


def _odds(value: Any) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 1 else None


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def calculate_edge(model_probability: Any, market_probability: Any) -> float | None:
    """Return model probability minus fair market probability."""

    model = _probability(model_probability)
    market = _probability(market_probability)
    if model is None or market is None:
        return None
    return round(model - market, 6)


def calculate_ev(model_probability: Any, odds: Any) -> float | None:
    """Return decimal-odds expected value, ``P * O - 1``."""

    probability = _probability(model_probability)
    price = _odds(odds)
    if probability is None or price is None:
        return None
    return round(probability * price - 1, 6)


def odds_age_minutes(updated_at: Any, now: datetime | None = None) -> float | None:
    captured = _timestamp(updated_at)
    if captured is None:
        return None
    reference = now.astimezone(UTC) if now and now.tzinfo else (now.replace(tzinfo=UTC) if now else datetime.now(UTC))
    age = (reference - captured).total_seconds() / 60
    return round(age, 4) if age >= 0 else None


@dataclass(frozen=True)
class PortfolioConfig:
    """Configurable P2 policy; values are fractions of bankroll unless noted."""

    min_edge: float = 0.05
    min_ev: float = 0.05
    max_odds_age_minutes: float = 180.0
    stake_fraction: float = 0.01
    max_single_bet_fraction: float = 0.01
    max_daily_exposure: float = 0.05
    max_league_exposure: float = 0.02
    max_total_exposure: float = 0.10
    max_drawdown: float = 0.30
    min_data_completeness: float = 0.70
    max_league_candidates: int | None = 2
    ev_weight: float = 1.0
    edge_weight: float = 1.0
    confidence_weight: float = 0.25
    data_quality_weight: float = 0.25
    clv_weight: float = 0.10
    freshness_weight: float = 0.10
    risk_weight: float = 0.25

    @classmethod
    def from_settings(cls, settings: Any) -> "PortfolioConfig":
        defaults = cls()
        values = {
            field: getattr(settings, f"portfolio_{field}", getattr(settings, field, getattr(defaults, field)))
            for field in defaults.__dict__
        }
        return cls(**values)


@dataclass(frozen=True)
class BetCandidate:
    fixture_id: str
    fixture_date: str | None
    league_key: str | None
    prediction_id: str
    model_key: str
    market: str
    selection: str
    line: Any
    odds: float
    model_probability: float
    market_probability: float
    edge: float
    ev: float
    risk_score: float
    data_quality: float
    odds_age_minutes: float | None
    confidence: float = 0.0
    historical_clv: float | None = None
    correlation_group: str | None = None
    candidate_score: float = 0.0
    bookmaker: str | None = None
    odds_snapshot_id: str | None = None

    @property
    def expected_edge(self) -> float:
        """Compatibility alias for the legacy market decision field."""

        return self.ev

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_edge"] = self.ev
        payload["price"] = self.odds
        payload["correlation_group"] = self.correlation_group or self.fixture_id
        return payload


def candidate_from_market_row(
    prediction: Mapping[str, Any],
    fixture: Mapping[str, Any],
    market_row: Mapping[str, Any],
    config: PortfolioConfig | None = None,
    *,
    now: datetime | None = None,
    historical_clv: float | None = None,
) -> BetCandidate | None:
    config = config or PortfolioConfig()
    historical_clv = (
        historical_clv
        if historical_clv is not None
        else _number(prediction.get("historical_clv"))
    )
    model_probability = _probability(market_row.get("model_probability"))
    market_probability = _probability(market_row.get("market_probability"))
    if market_probability is None:
        market_probability = _probability(market_row.get("de_vig_probability"))
    price = _odds(market_row.get("price", market_row.get("odds")))
    if model_probability is None or market_probability is None or price is None:
        return None
    age = odds_age_minutes(
        market_row.get("odds_updated_at")
        or (prediction.get("market_assessment") or {}).get("odds_updated_at"),
        now,
    )
    quality = max(0.0, min(1.0, _number(prediction.get("data_completeness"), 0.0) or 0.0))
    confidence = max(
        0.0,
        min(
            1.0,
            _number(
                (prediction.get("decision") or {}).get("model_confidence"),
                _number(prediction.get("forecast_confidence"), 0.0),
            )
            or 0.0,
        ),
    )
    edge = calculate_edge(model_probability, market_probability)
    ev = calculate_ev(model_probability, price)
    if edge is None or ev is None:
        return None
    freshness = 0.0 if age is None else max(0.0, min(1.0, 1 - age / config.max_odds_age_minutes))
    risk_score = round(max(0.0, min(1.0, (1 - quality) * 0.7 + (1 - freshness) * 0.3)), 6)
    score = score_candidate_values(
        ev,
        edge,
        confidence,
        quality,
        historical_clv,
        freshness,
        risk_score,
        config,
    )
    return BetCandidate(
        fixture_id=str(fixture.get("id") or ""),
        fixture_date=str(fixture.get("fixture_date")) if fixture.get("fixture_date") is not None else None,
        league_key=str(fixture.get("league_key")) if fixture.get("league_key") is not None else None,
        prediction_id=str(prediction.get("id") or ""),
        model_key=str(prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek"),
        market=str(market_row.get("market") or ""),
        selection=str(market_row.get("selection") or ""),
        line=market_row.get("line"),
        odds=round(price, 6),
        model_probability=round(model_probability, 6),
        market_probability=round(market_probability, 6),
        edge=edge,
        ev=ev,
        risk_score=risk_score,
        data_quality=round(quality, 6),
        odds_age_minutes=age,
        confidence=round(confidence, 6),
        historical_clv=historical_clv,
        correlation_group=str(fixture.get("id") or ""),
        candidate_score=score,
        bookmaker=market_row.get("bookmaker"),
        odds_snapshot_id=prediction.get("odds_snapshot_id"),
    )


def build_candidates(
    prediction: Mapping[str, Any],
    fixture: Mapping[str, Any],
    config: PortfolioConfig | None = None,
    *,
    now: datetime | None = None,
    historical_clv: float | None = None,
) -> list[BetCandidate]:
    config = config or PortfolioConfig()
    assessment = prediction.get("market_assessment") or {}
    if assessment.get("odds_status") != "fresh":
        return []
    if (prediction.get("ai") or {}).get("status") != "completed":
        return []
    candidates = [
        candidate
        for row in assessment.get("markets") or []
        if (candidate := candidate_from_market_row(prediction, fixture, row, config, now=now, historical_clv=historical_clv))
        and is_candidate_eligible(candidate, config)
    ]
    return sorted(candidates, key=candidate_sort_key)


def is_candidate_eligible(candidate: BetCandidate | Mapping[str, Any], config: PortfolioConfig | None = None) -> bool:
    config = config or PortfolioConfig()
    edge = _number(_value(candidate, "edge"), -1) or -1
    ev = _number(_value(candidate, "ev"), -1) or -1
    quality = _number(_value(candidate, "data_quality"), 0) or 0
    age = _number(_value(candidate, "odds_age_minutes"))
    odds = _odds(_value(candidate, "odds"))
    return bool(
        edge >= config.min_edge
        and ev >= config.min_ev
        and quality >= config.min_data_completeness
        and odds is not None
        and age is not None
        and age <= config.max_odds_age_minutes
    )


def score_candidate(candidate: BetCandidate | Mapping[str, Any], config: PortfolioConfig | None = None) -> float:
    config = config or PortfolioConfig()
    return score_candidate_values(
        _number(_value(candidate, "ev"), 0) or 0,
        _number(_value(candidate, "edge"), 0) or 0,
        _number(_value(candidate, "confidence"), 0) or 0,
        _number(_value(candidate, "data_quality"), 0) or 0,
        _number(_value(candidate, "historical_clv")),
        _freshness_score(_number(_value(candidate, "odds_age_minutes")), config),
        _number(_value(candidate, "risk_score"), 1) or 1,
        config,
    )


def score_candidate_values(
    ev: float,
    edge: float,
    confidence: float,
    data_quality: float,
    historical_clv: float | None,
    freshness: float,
    risk_score: float,
    config: PortfolioConfig,
) -> float:
    score = (
        config.ev_weight * ev
        + config.edge_weight * edge
        + config.confidence_weight * confidence
        + config.data_quality_weight * data_quality
        + config.clv_weight * (historical_clv or 0.0)
        + config.freshness_weight * freshness
        - config.risk_weight * risk_score
    )
    return round(score, 6)


def candidate_sort_key(candidate: BetCandidate | Mapping[str, Any]) -> tuple[float, float, float, str, str]:
    return (
        -(_number(_value(candidate, "candidate_score"), 0) or 0),
        -(_number(_value(candidate, "ev"), 0) or 0),
        -(_number(_value(candidate, "edge"), 0) or 0),
        str(_value(candidate, "fixture_id") or ""),
        str(_value(candidate, "prediction_id") or ""),
    )


def calculate_drawdown(equity_curve: Iterable[Any], initial_bankroll: float = 0.0) -> float:
    peak = float(initial_bankroll)
    maximum = 0.0
    for point in equity_curve:
        balance = _number(point.get("balance") if isinstance(point, Mapping) else point)
        if balance is None:
            continue
        peak = max(peak, balance)
        if peak > 0:
            maximum = max(maximum, (peak - balance) / peak)
    return round(maximum, 6)


def exposure_totals(
    bets: Iterable[Mapping[str, Any]],
    *,
    fixture_date: str | None = None,
    league_key: str | None = None,
) -> dict[str, float]:
    all_rows = list(bets)
    rows = [
        bet
        for bet in all_rows
        if str(bet.get("status") or "").lower() in ACTIVE_STATUSES
        and (fixture_date is None or bet.get("fixture_date") == fixture_date)
    ]
    league_rows = [bet for bet in rows if league_key is None or bet.get("league_key") == league_key]
    return {
        "daily": round(sum(_number(bet.get("stake"), 0) or 0 for bet in rows), 2),
        "league": round(sum(_number(bet.get("stake"), 0) or 0 for bet in league_rows), 2),
        "total": round(sum(_number(bet.get("stake"), 0) or 0 for bet in all_rows if str(bet.get("status") or "").lower() in ACTIVE_STATUSES), 2),
    }


def risk_gate(
    candidate: BetCandidate | Mapping[str, Any],
    bankroll: float,
    *,
    daily_exposure: float = 0.0,
    league_exposure: float = 0.0,
    total_exposure: float = 0.0,
    drawdown: float = 0.0,
    config: PortfolioConfig | None = None,
    requested_stake: float | None = None,
) -> dict[str, Any]:
    config = config or PortfolioConfig()
    base = max(0.0, float(bankroll))
    requested = max(0.0, float(requested_stake if requested_stake is not None else base * config.stake_fraction))
    reasons: list[str] = []
    if not is_candidate_eligible(candidate, config):
        reasons.append("candidate_ineligible")
    if drawdown >= config.max_drawdown:
        reasons.append("max_drawdown")
    single_limit = base * config.max_single_bet_fraction
    daily_limit = base * config.max_daily_exposure
    league_limit = base * config.max_league_exposure
    total_limit = base * config.max_total_exposure
    allowed = min(
        requested,
        single_limit,
        max(0.0, daily_limit - float(daily_exposure)),
        max(0.0, league_limit - float(league_exposure)),
        max(0.0, total_limit - float(total_exposure)),
    )
    allowed = round(max(0.0, allowed), 2)
    if allowed <= 0:
        reasons.append("exposure_limit")
    status = "FAIL" if reasons else "PASS"
    return {
        "status": status,
        "passed": status == "PASS",
        "reason_codes": list(dict.fromkeys(reasons)),
        "requested_stake": round(requested, 2),
        "allowed_stake": allowed if status == "PASS" else 0.0,
        "drawdown": round(float(drawdown), 6),
        "limits": {
            "single": round(single_limit, 2),
            "daily": round(daily_limit, 2),
            "league": round(league_limit, 2),
            "total": round(total_limit, 2),
        },
        "exposure": {
            "daily": round(float(daily_exposure), 2),
            "league": round(float(league_exposure), 2),
            "total": round(float(total_exposure), 2),
        },
    }


def allocate_stake(
    candidate: BetCandidate | Mapping[str, Any],
    bankroll: float,
    *,
    daily_exposure: float = 0.0,
    league_exposure: float = 0.0,
    total_exposure: float = 0.0,
    drawdown: float = 0.0,
    config: PortfolioConfig | None = None,
    requested_stake: float | None = None,
) -> float:
    """Return the allowed fixed-fraction stake after the Risk Gate."""

    return float(
        risk_gate(
            candidate,
            bankroll,
            daily_exposure=daily_exposure,
            league_exposure=league_exposure,
            total_exposure=total_exposure,
            drawdown=drawdown,
            config=config,
            requested_stake=requested_stake,
        )["allowed_stake"]
    )


def select_portfolio(
    candidates: Iterable[BetCandidate | Mapping[str, Any]],
    bankroll: float,
    *,
    existing_bets: Iterable[Mapping[str, Any]] = (),
    config: PortfolioConfig | None = None,
    drawdown: float = 0.0,
) -> list[dict[str, Any]]:
    config = config or PortfolioConfig()
    existing = list(existing_bets)
    active = [bet for bet in existing if str(bet.get("status") or "").lower() in ACTIVE_STATUSES]
    selected: list[dict[str, Any]] = []
    groups: set[str] = {
        str(bet.get("correlation_group") or bet.get("fixture_id") or "")
        for bet in active
    }
    league_counts: dict[tuple[str, str | None], int] = {}
    total = sum(_number(bet.get("stake"), 0) or 0 for bet in active)
    for candidate in sorted(candidates, key=candidate_sort_key):
        group = str(_value(candidate, "correlation_group") or _value(candidate, "fixture_id") or "")
        league = str(_value(candidate, "league_key") or "")
        fixture_date = _value(candidate, "fixture_date")
        if group in groups:
            continue
        league_count_key = (league, fixture_date)
        if config.max_league_candidates is not None and league_counts.get(league_count_key, 0) >= config.max_league_candidates:
            continue
        league_exposure = sum(
            _number(bet.get("stake"), 0) or 0
            for bet in active
            if str(bet.get("league_key") or "") == league
            and (fixture_date is None or bet.get("fixture_date") == fixture_date)
        ) + sum(
            item["stake"]
            for item in selected
            if str(item.get("league_key") or "") == league
            and (fixture_date is None or item.get("fixture_date") == fixture_date)
        )
        daily_exposure = sum(
            _number(bet.get("stake"), 0) or 0
            for bet in active
            if fixture_date is None or bet.get("fixture_date") == fixture_date
        ) + sum(
            item["stake"]
            for item in selected
            if fixture_date is None or item.get("fixture_date") == fixture_date
        )
        selected_total = sum(item["stake"] for item in selected)
        gate = risk_gate(
            candidate,
            bankroll,
            daily_exposure=daily_exposure,
            league_exposure=league_exposure,
            total_exposure=total + selected_total,
            drawdown=drawdown,
            config=config,
        )
        if gate["status"] != "PASS" or gate["allowed_stake"] <= 0:
            continue
        payload = candidate.to_dict() if isinstance(candidate, BetCandidate) else dict(candidate)
        payload.update(
            {
                "stake": gate["allowed_stake"],
                "risk_gate": gate,
                "league_key": league or payload.get("league_key"),
                "correlation_group": group,
            }
        )
        selected.append(payload)
        groups.add(group)
        league_counts[league_count_key] = league_counts.get(league_count_key, 0) + 1
    return selected


def _value(candidate: BetCandidate | Mapping[str, Any], key: str) -> Any:
    return getattr(candidate, key, None) if isinstance(candidate, BetCandidate) else candidate.get(key)


def _freshness_score(age: float | None, config: PortfolioConfig) -> float:
    if age is None:
        return 0.0
    return max(0.0, min(1.0, 1 - age / config.max_odds_age_minutes))


# Naming aliases keep callers expressive without duplicating implementation.
calculate_bet_edge = calculate_edge
calculate_bet_ev = calculate_ev
build_bet_candidates = build_candidates
portfolio_selection = select_portfolio
drawdown = calculate_drawdown
