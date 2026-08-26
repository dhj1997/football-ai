"""Simulated bankroll placement rules and aggregate reporting."""

import math
import uuid
from datetime import UTC, datetime
from typing import Any


INITIAL_BANKROLL = 1000.0
MAX_FIXTURE_EXPOSURE = 0.02
MAX_DAILY_EXPOSURE = 0.10
MIN_DATA_COMPLETENESS = 0.70
MIN_MODEL_CONFIDENCE = 0.60
MIN_EXPECTED_EDGE = 0.03


class BankrollService:
    """Place bounded simulated bets from validated model recommendations."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.model_key = "deepseek"
        self.competition_id = "legacy"
        self.uncapped = False

    def configure(self, model_key: str, competition_id: str, uncapped: bool = False) -> "BankrollService":
        self.model_key = model_key
        self.competition_id = competition_id
        self.uncapped = uncapped
        return self

    def place_for_prediction(
        self,
        prediction: dict[str, Any],
        fixture: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if fixture.get("status") != "scheduled" or (prediction.get("ai") or {}).get("status") != "completed":
            return None
        existing = self.repository.bet_for_prediction(prediction["id"])
        if existing:
            return existing
        recommendation = prediction.get("recommendation") or {}
        market = recommendation.get("market")
        selection = recommendation.get("selection")
        if market == "no_bet" or selection == "none":
            return None
        if float(prediction.get("data_completeness") or 0) < MIN_DATA_COMPLETENESS:
            return None
        if float(recommendation.get("confidence") or 0) < MIN_MODEL_CONFIDENCE:
            return None
        if any(
            item.get("fixture_id") == fixture["id"]
            for item in self.repository.bets(status="placed", model_key=self.model_key, competition_id=self.competition_id)
        ):
            return None
        odds = context.get("odds")
        price = _matching_price(market, selection, odds)
        if price is None or price <= 1:
            return None
        if not self.uncapped and _expected_edge(prediction, market, selection, price) < MIN_EXPECTED_EDGE:
            return None

        balance = self.repository.current_balance(self.model_key, self.competition_id)
        open_today = self.repository.bets(status="placed", fixture_date=fixture["fixture_date"], model_key=self.model_key, competition_id=self.competition_id)
        daily_exposure = round(sum(float(item["stake"]) for item in open_today), 2)
        daily_base = balance + daily_exposure
        daily_remaining = balance if self.uncapped else max(0.0, daily_base * MAX_DAILY_EXPOSURE - daily_exposure)
        suggested_fraction = min(
            1.0 if self.uncapped else MAX_FIXTURE_EXPOSURE,
            max(0.0, float(recommendation.get("recommended_stake_fraction") or 0)),
        )
        stake_limits = [balance * suggested_fraction, daily_remaining, balance]
        if not self.uncapped:
            stake_limits.append(balance * MAX_FIXTURE_EXPOSURE)
        raw_stake = min(stake_limits)
        stake = math.floor(raw_stake * 100) / 100
        if stake < 0.01:
            return None

        placed_at = datetime.now(UTC).isoformat()
        handicap_line = (odds or {}).get("asian_handicap") if market == "asian_handicap" else None
        return self.repository.place_bet(
            {
                "id": str(uuid.uuid4()),
                "prediction_id": prediction["id"],
                "fixture_id": fixture["id"],
                "fixture_date": fixture["fixture_date"],
                "placed_at": placed_at,
                "market": market,
                "selection": selection,
                "handicap_line": handicap_line,
                "odds": round(price, 3),
                "stake": stake,
                "league_key": fixture["league_key"],
                "kickoff": fixture["kickoff"],
                "home_team": fixture["home_team"].get("name"),
                "away_team": fixture["away_team"].get("name"),
                "model_version": prediction["model_version"],
                "model_confidence": recommendation.get("confidence"),
                "reason": recommendation.get("reason"),
                "is_simulated": True,
                "model_key": self.model_key,
                "competition_id": self.competition_id,
            }
        )

    def summary(self) -> dict[str, Any]:
        bets = self.repository.bets(model_key=self.model_key, competition_id=self.competition_id)
        settled = [item for item in bets if item.get("status") == "settled"]
        open_bets = [item for item in bets if item.get("status") == "placed"]
        total_staked = round(sum(float(item["stake"]) for item in bets), 2)
        settled_staked = round(sum(float(item["stake"]) for item in settled), 2)
        total_returns = round(sum(float(item.get("return_amount") or 0) for item in settled), 2)
        balance = self.repository.current_balance(self.model_key, self.competition_id)
        open_exposure = round(sum(float(item["stake"]) for item in open_bets), 2)
        realized_profit = round(sum(float(item.get("net_profit") or 0) for item in settled), 2)
        profitable = sum(1 for item in settled if float(item.get("net_profit") or 0) > 0)
        decided = sum(1 for item in settled if item.get("settlement_result") != "push")
        transactions = self.repository.bankroll_transactions(self.model_key, self.competition_id)
        return {
            "initial_balance": INITIAL_BANKROLL,
            "balance": balance,
            "equity": round(balance + open_exposure, 2),
            "net_profit": realized_profit,
            "total_staked": total_staked,
            "settled_staked": settled_staked,
            "total_returns": total_returns,
            "open_exposure": open_exposure,
            "roi": round(realized_profit / settled_staked, 4) if settled_staked else 0.0,
            "hit_rate": round(profitable / decided, 4) if decided else 0.0,
            "bet_count": len(bets),
            "settled_count": len(settled),
            "open_count": len(open_bets),
            "max_drawdown": _max_drawdown(settled),
            "equity_curve": _equity_curve(settled, transactions),
            "is_simulated": True,
            "model_key": self.model_key,
            "competition_id": self.competition_id,
        }


def _matching_price(market: Any, selection: Any, odds: Any) -> float | None:
    if not isinstance(odds, dict):
        return None
    key = None
    if market == "1x2" and selection in {"home", "draw", "away"}:
        key = selection
    elif market == "asian_handicap" and selection == "home_handicap":
        key = "asian_handicap_home_odd"
    elif market == "asian_handicap" and selection == "away_handicap":
        key = "asian_handicap_away_odd"
    value = odds.get(key) if key else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _expected_edge(
    prediction: dict[str, Any],
    market: Any,
    selection: Any,
    price: float,
) -> float:
    if market == "1x2" and selection in {"home", "draw", "away"}:
        probability = float((prediction.get("probabilities") or {}).get(selection) or 0)
        return probability * price - 1
    if market != "asian_handicap":
        return -1.0
    handicap = prediction.get("asian_handicap") or {}
    home = handicap.get("home_settlement") or {}
    if not home:
        return -1.0
    if selection == "away_handicap":
        weights = {
            "full_win": float(home.get("full_loss") or 0),
            "half_win": float(home.get("half_loss") or 0),
            "push": float(home.get("push") or 0),
            "half_loss": float(home.get("half_win") or 0),
            "full_loss": float(home.get("full_win") or 0),
        }
    else:
        weights = {key: float(home.get(key) or 0) for key in ("full_win", "half_win", "push", "half_loss", "full_loss")}
    expected_return = (
        weights["full_win"] * price
        + weights["half_win"] * (price + 1) / 2
        + weights["push"]
        + weights["half_loss"] * 0.5
    )
    return expected_return - 1


def _max_drawdown(settled_bets: list[dict[str, Any]]) -> float:
    peak = INITIAL_BANKROLL
    maximum = 0.0
    balance = INITIAL_BANKROLL
    for bet in sorted(settled_bets, key=lambda item: (item.get("settled_at") or "", item["id"])):
        balance += float(bet.get("net_profit") or 0)
        peak = max(peak, balance)
        if peak > 0:
            maximum = max(maximum, (peak - balance) / peak)
    return round(maximum, 4)


def _equity_curve(
    settled_bets: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    initial_at = transactions[0].get("created_at") if transactions else None
    points = [{"at": initial_at, "balance": INITIAL_BANKROLL}]
    balance = INITIAL_BANKROLL
    for bet in sorted(settled_bets, key=lambda item: (item.get("settled_at") or "", item["id"])):
        balance = round(balance + float(bet.get("net_profit") or 0), 2)
        points.append({"at": bet.get("settled_at"), "balance": balance, "bet_id": bet["id"]})
    return points


class DualBankrollService:
    """Dispatch independent model investments and expose comparable summaries."""

    def __init__(self, services: dict[str, BankrollService], competition_id: str) -> None:
        self.services = services
        self.competition_id = competition_id

    def place_for_prediction(self, prediction: dict[str, Any], fixture: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        model_key = prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek"
        service = self.services.get(model_key)
        return service.place_for_prediction(prediction, fixture, context) if service else None

    def place_for_predictions(self, predictions: list[dict[str, Any]], fixture: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        return [bet for prediction in predictions if (bet := self.place_for_prediction(prediction, fixture, context))]

    def summary(self) -> dict[str, Any]:
        accounts = {key: service.summary() for key, service in self.services.items()}
        primary = accounts.get("deepseek") or next(iter(accounts.values()), {})
        return {
            **primary,
            "competition_id": self.competition_id,
            "accounts": accounts,
            "is_simulated": True,
        }
