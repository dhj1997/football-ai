"""Simulated bankroll placement rules and aggregate reporting."""

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from .market_decision import REASON_TEXT, assess_markets


INITIAL_BANKROLL = 1000.0
MIN_FIXTURE_EXPOSURE = 0.10
MAX_FIXTURE_EXPOSURE = 0.25
MAX_DAILY_EXPOSURE = 0.50
MIN_DATA_COMPLETENESS = 0.70
MIN_EXPECTED_EDGE = 0.03


class BankrollService:
    """Place bounded simulated bets from deterministic backend decisions."""

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
        if fixture.get("status") != "scheduled" or _fixture_started(fixture):
            return None
        latest_reader = getattr(self.repository, "latest", None)
        latest = latest_reader(fixture["id"], self.model_key, self.competition_id) if callable(latest_reader) else None
        if latest is not None and latest.get("id") != prediction.get("id"):
            return None
        _complete_candidate_decision(prediction, context)
        discard = getattr(self.repository, "discard_open_fixture_bets", None)
        if callable(discard):
            discard(fixture["id"], self.model_key, self.competition_id, prediction.get("id"))

        fixtures = self._league_day_fixtures(fixture)
        candidates = self._league_day_candidates(prediction, fixture, fixtures, context)
        group_bets = self._league_day_bets(fixture["fixture_date"], fixture.get("league_key"))
        locked = next(
            (
                bet for bet in group_bets
                if bet.get("status") == "settled"
                or _fixture_started(next((item for item in fixtures if item["id"] == bet.get("fixture_id")), {}))
            ),
            None,
        )
        if locked:
            return locked
        if not candidates:
            return None

        selected_prediction, selected_fixture = candidates[0]
        if callable(discard):
            for grouped_fixture in fixtures:
                discard(
                    grouped_fixture["id"],
                    self.model_key,
                    self.competition_id,
                    selected_prediction["id"] if grouped_fixture["id"] == selected_fixture["id"] else None,
                )
        existing_selected = self.repository.bet_for_prediction(selected_prediction["id"])
        if existing_selected and _bet_matches_candidate(existing_selected, selected_prediction):
            return existing_selected
        if existing_selected and callable(discard):
            discard(selected_fixture["id"], self.model_key, self.competition_id)
        return self._place_candidate(selected_prediction, selected_fixture)

    def execution_for_prediction(self, prediction: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
        """Describe portfolio execution without mutating the immutable prediction."""

        decision = prediction.get("decision") or {}
        linked = self.repository.bet_for_prediction(prediction["id"])
        if linked:
            return {
                "status": "bet",
                "reason_codes": [],
                "reason": "已获得本联赛当日模拟下注名额",
                "bet_id": linked["id"],
            }
        if decision.get("status") != "bet":
            return {
                "status": decision.get("status") or "insufficient_data",
                "reason_codes": decision.get("reason_codes") or [],
                "reason": decision.get("reason") or "当前数据不足，未执行模拟下注",
                "bet_id": None,
            }

        fixtures = self._league_day_fixtures(fixture)
        candidates = self._league_day_candidates(
            prediction,
            fixture,
            fixtures,
            fixture.get("evidence") or {},
        )
        group_bets = self._league_day_bets(fixture["fixture_date"], fixture.get("league_key"))
        if group_bets or (candidates and candidates[0][0]["id"] != prediction["id"]):
            return {
                "status": "no_bet",
                "reason_codes": ["league_daily_limit"],
                "reason": "同模型同联赛当日已有预期优势更高的比赛",
                "bet_id": None,
            }
        return {
            "status": "no_bet",
            "reason_codes": ["risk_limit"],
            "reason": "模拟账户当日剩余额度不足以满足最低10%仓位",
            "bet_id": None,
        }

    def _league_day_fixtures(self, fixture: dict[str, Any]) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "list_fixtures", None)
        rows = reader(fixture["fixture_date"], fixture["fixture_date"], fixture.get("league_key")) if callable(reader) else []
        by_id = {str(item["id"]): item for item in rows}
        by_id[str(fixture["id"])] = fixture
        return list(by_id.values())

    def _league_day_candidates(
        self,
        prediction: dict[str, Any],
        fixture: dict[str, Any],
        fixtures: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        latest_reader = getattr(self.repository, "latest", None)
        rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for grouped_fixture in fixtures:
            current = prediction if grouped_fixture["id"] == fixture["id"] else (
                latest_reader(grouped_fixture["id"], self.model_key, self.competition_id)
                if callable(latest_reader) else None
            )
            if current:
                candidate_context = (
                    context
                    if grouped_fixture["id"] == fixture["id"]
                    else grouped_fixture.get("evidence") or {}
                )
                _complete_candidate_decision(current, candidate_context)
            if current and _eligible_candidate(current, grouped_fixture):
                rows.append((current, grouped_fixture))
        return sorted(rows, key=_candidate_rank)

    def _league_day_bets(self, fixture_date: str, league_key: Any) -> list[dict[str, Any]]:
        return [
            item for item in self.repository.bets(
                fixture_date=fixture_date,
                model_key=self.model_key,
                competition_id=self.competition_id,
            )
            if item.get("league_key") == league_key
        ]

    def _place_candidate(
        self,
        prediction: dict[str, Any],
        fixture: dict[str, Any],
    ) -> dict[str, Any] | None:
        decision = prediction.get("decision") or {}
        market = decision.get("market")
        selection = decision.get("selection")
        price = _positive_number(decision.get("price"))
        edge = float(decision.get("expected_edge") or 0)
        if price is None or edge < MIN_EXPECTED_EDGE:
            return None

        balance = self.repository.current_balance(self.model_key, self.competition_id)
        today = self.repository.bets(
            fixture_date=fixture["fixture_date"],
            model_key=self.model_key,
            competition_id=self.competition_id,
        )
        daily_staked = round(sum(float(item["stake"]) for item in today), 2)
        open_exposure = round(sum(float(item["stake"]) for item in today if item.get("status") == "placed"), 2)
        daily_base = balance + open_exposure
        daily_remaining = max(0.0, daily_base * MAX_DAILY_EXPOSURE - daily_staked)
        suggested_fraction = _stake_fraction_for_edge(edge)
        raw_stake = min(balance * suggested_fraction, daily_remaining, balance)
        minimum_stake = balance * MIN_FIXTURE_EXPOSURE
        if raw_stake + 1e-9 < minimum_stake:
            return None
        stake = math.floor(raw_stake * 100) / 100
        if stake <= 0:
            return None

        market_row = next(
            (
                row for row in (prediction.get("market_assessment") or {}).get("markets", [])
                if row.get("market") == market and row.get("selection") == selection
            ),
            {},
        )
        placed_at = datetime.now(UTC).isoformat()
        return self.repository.place_bet(
            {
                "id": str(uuid.uuid4()),
                "prediction_id": prediction["id"],
                "fixture_id": fixture["id"],
                "fixture_date": fixture["fixture_date"],
                "placed_at": placed_at,
                "market": market,
                "selection": selection,
                "handicap_line": (
                    market_row.get("line")
                    if market_row.get("line") is not None
                    else (prediction.get("asian_handicap") or {}).get("line")
                ) if market == "asian_handicap" else None,
                "odds": round(price, 3),
                "stake": stake,
                "league_key": fixture["league_key"],
                "kickoff": fixture["kickoff"],
                "home_team": fixture["home_team"].get("name"),
                "away_team": fixture["away_team"].get("name"),
                "model_version": prediction["model_version"],
                "model_confidence": decision.get("model_confidence"),
                "expected_edge": round(edge, 4),
                "reason": decision.get("reason"),
                "reason_codes": decision.get("reason_codes") or [],
                "prediction_phase": prediction.get("phase") or "preliminary",
                "lineup_confirmed": bool(((fixture.get("evidence") or {}).get("lineup") or {}).get("confirmed")),
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


def _eligible_candidate(prediction: dict[str, Any], fixture: dict[str, Any]) -> bool:
    decision = prediction.get("decision") or {}
    return bool(
        fixture.get("status") == "scheduled"
        and not _fixture_started(fixture)
        and (prediction.get("ai") or {}).get("status") == "completed"
        and float(prediction.get("data_completeness") or 0) >= MIN_DATA_COMPLETENESS
        and decision.get("status") == "bet"
        and decision.get("market") in {"1x2", "asian_handicap"}
        and decision.get("selection") not in {None, "none"}
        and float(decision.get("expected_edge") or 0) >= MIN_EXPECTED_EDGE
        and (_positive_number(decision.get("price")) or 0) > 1
    )


def _complete_candidate_decision(prediction: dict[str, Any], context: dict[str, Any]) -> None:
    prediction["market_assessment"] = assess_markets(prediction, context.get("odds"))
    _apply_current_market_policy(prediction)


def _apply_current_market_policy(prediction: dict[str, Any]) -> None:
    assessment = prediction.get("market_assessment") or {}
    markets = assessment.get("markets") or []
    decision = prediction.get("decision") or {}
    reason_codes = [
        code for code in (decision.get("reason_codes") or [])
        if code not in {"ai_no_bet", "negative_edge", "no_matching_market", "stale_odds"}
    ]
    if not markets:
        reason_codes.append("no_matching_market")
        decision.update(
            {
                "status": "insufficient_data",
                "market": "no_bet",
                "selection": "none",
                "considered_market": None,
                "considered_selection": None,
                "price": None,
                "expected_edge": None,
                "stake_fraction": 0.0,
                "reason_codes": list(dict.fromkeys(reason_codes)),
                "reason": REASON_TEXT["no_matching_market"],
            }
        )
        prediction["decision"] = decision
        return

    candidate = max(markets, key=lambda item: float(item.get("expected_edge") or -1))
    if assessment.get("odds_status") != "fresh" and "stale_odds" not in reason_codes:
        reason_codes.append("stale_odds")
    edge = float(candidate.get("expected_edge") or 0)
    if edge < MIN_EXPECTED_EDGE:
        reason_codes.append("negative_edge")
    reason_codes = list(dict.fromkeys(reason_codes))
    status = "no_bet" if reason_codes else "bet"
    decision.update(
        {
            "status": status,
            "market": candidate.get("market") if status == "bet" else "no_bet",
            "selection": candidate.get("selection") if status == "bet" else "none",
            "considered_market": candidate.get("market"),
            "considered_selection": candidate.get("selection"),
            "price": candidate.get("price"),
            "expected_edge": round(edge, 4),
            "stake_fraction": (
                _stake_fraction_for_edge(edge)
                if (prediction.get("ai") or {}).get("status") == "completed"
                else 0.0
            ),
            "reason_codes": reason_codes,
            "reason": (
                "；".join(REASON_TEXT[code] for code in reason_codes)
                if reason_codes
                else "赔率优势和证据质量达到模拟执行标准"
            ),
        }
    )
    prediction["decision"] = decision


def _stake_fraction_for_edge(edge: float) -> float:
    if edge < MIN_EXPECTED_EDGE:
        return 0.0
    return round(
        min(MAX_FIXTURE_EXPOSURE, MIN_FIXTURE_EXPOSURE + max(edge - MIN_EXPECTED_EDGE, 0.0)),
        4,
    )


def _bet_matches_candidate(bet: dict[str, Any], prediction: dict[str, Any]) -> bool:
    decision = prediction.get("decision") or {}
    balance_before = float(bet.get("balance_before") or 0)
    actual_fraction = float(bet.get("stake") or 0) / balance_before if balance_before > 0 else 0.0
    return bool(
        bet.get("status") == "placed"
        and bet.get("market") == decision.get("market")
        and bet.get("selection") == decision.get("selection")
        and MIN_FIXTURE_EXPOSURE <= actual_fraction <= MAX_FIXTURE_EXPOSURE
        and abs(float(bet.get("expected_edge") or 0) - float(decision.get("expected_edge") or 0)) < 0.0001
    )


def _candidate_rank(item: tuple[dict[str, Any], dict[str, Any]]) -> tuple[float, float, str, str]:
    prediction, fixture = item
    decision = prediction.get("decision") or {}
    return (
        -float(decision.get("expected_edge") or 0),
        -float(decision.get("model_confidence") or prediction.get("forecast_confidence") or 0),
        str(fixture.get("kickoff") or ""),
        str(fixture.get("id") or ""),
    )


def _fixture_started(fixture: dict[str, Any]) -> bool:
    if fixture.get("status") != "scheduled":
        return True
    try:
        kickoff = datetime.fromisoformat(str(fixture.get("kickoff") or "").replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
    except ValueError:
        return True
    return kickoff <= datetime.now(UTC)


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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

    def execution_for_prediction(self, prediction: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
        model_key = prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek"
        service = self.services.get(model_key)
        if service:
            return service.execution_for_prediction(prediction, fixture)
        return {
            "status": "insufficient_data",
            "reason_codes": ["risk_limit"],
            "reason": "未找到对应模型的模拟账户",
            "bet_id": None,
        }

    def summary(self) -> dict[str, Any]:
        accounts = {key: service.summary() for key, service in self.services.items()}
        primary = accounts.get("deepseek") or next(iter(accounts.values()), {})
        return {
            **primary,
            "competition_id": self.competition_id,
            "accounts": accounts,
            "is_simulated": True,
        }
