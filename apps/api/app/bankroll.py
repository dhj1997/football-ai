"""Simulated bankroll placement rules and aggregate reporting."""

import math
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .market_decision import REASON_TEXT, assess_markets
from .portfolio import PortfolioConfig, build_candidates, select_portfolio


INITIAL_BANKROLL = 1000.0
MIN_FIXTURE_EXPOSURE = 0.10
MAX_FIXTURE_EXPOSURE = 0.25
MAX_DAILY_EXPOSURE = 0.50
MIN_DATA_COMPLETENESS = 0.70
MIN_EXPECTED_EDGE = 0.03


class BankrollService:
    """Place bounded simulated bets from deterministic backend decisions."""

    def __init__(self, repository: Any, portfolio_config: PortfolioConfig | None = None) -> None:
        self.repository = repository
        self.portfolio_config = portfolio_config
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
        working_prediction = deepcopy(prediction)
        _complete_candidate_decision(working_prediction, context, self.repository)
        discard = getattr(self.repository, "discard_open_fixture_bets", None)
        if callable(discard):
            discard(fixture["id"], self.model_key, self.competition_id, working_prediction.get("id"))

        fixtures = self._league_day_fixtures(fixture)
        candidates = self._league_day_candidates(working_prediction, fixture, fixtures, context)
        group_bets = self._league_day_bets(fixture["fixture_date"], fixture.get("league_key"))
        locked = next(
            (
                bet for bet in group_bets
                if (
                    bet.get("fixture_id") == fixture.get("id")
                    if self.portfolio_config is not None
                    else bet.get("status") == "settled"
                    or _fixture_started(next((item for item in fixtures if item["id"] == bet.get("fixture_id")), {}))
                )
            ),
            None,
        )
        if locked:
            return locked
        if not candidates:
            return None

        selected_prediction, selected_fixture = candidates[0]
        if callable(discard) and self.portfolio_config is None:
            for grouped_fixture in fixtures:
                discard(
                    grouped_fixture["id"],
                    self.model_key,
                    self.competition_id,
                    selected_prediction["id"] if grouped_fixture["id"] == selected_fixture["id"] else None,
                )
        existing_selected = self.repository.bet_for_prediction(selected_prediction["id"])
        if existing_selected and _bet_matches_candidate(existing_selected, selected_prediction, self.portfolio_config):
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
                "execution_id": linked.get("execution_id"),
                "execution_status": "SETTLED" if linked.get("status") == "settled" else "EXECUTED",
                "risk_gate": linked.get("risk_gate"),
                "portfolio_candidate": linked.get("portfolio_candidate"),
            }
        if decision.get("status") != "bet":
            return {
                "status": decision.get("status") or "insufficient_data",
                "reason_codes": decision.get("reason_codes") or [],
                "reason": decision.get("reason") or "当前数据不足，未执行模拟下注",
                "bet_id": None,
                "execution_id": None,
                "execution_status": "REJECTED",
            }

        if self.portfolio_config is not None:
            fixtures = self._league_day_fixtures(fixture)
            candidates = self._league_day_candidates(
                prediction,
                fixture,
                fixtures,
                fixture.get("evidence") or {},
            )
            current = next((item for item in candidates if item[0].get("id") == prediction.get("id")), None)
            if current is None:
                return {
                    "status": "no_bet",
                    "reason_codes": ["portfolio_filter"],
                    "reason": "候选未同时满足 Edge、EV、数据质量或赔率新鲜度门槛",
                    "bet_id": None,
                    "execution_id": None,
                    "execution_status": "REJECTED",
                }
            existing = self.repository.bets(competition_id=self.competition_id)
            active = [item for item in existing if str(item.get("status") or "").lower() in {"placed", "pending", "executed", "selected"}]
            own_active = [item for item in active if item.get("model_key") == self.model_key]
            base = self.repository.current_balance(self.model_key, self.competition_id) + sum(float(item.get("stake") or 0) for item in own_active)
            selected = select_portfolio(
                [current[0].get("portfolio_candidate") or {}],
                base,
                existing_bets=existing,
                config=self.portfolio_config,
                drawdown=float(self.summary().get("max_drawdown") or 0),
            )
            if selected:
                return {
                    "status": "candidate",
                    "reason_codes": [],
                    "reason": "候选已通过组合风险门禁，等待 Paper Execution",
                    "bet_id": None,
                    "execution_id": None,
                    "execution_status": "PENDING",
                    "risk_gate": selected[0].get("risk_gate"),
                    "candidate": current[0].get("portfolio_candidate"),
                    "portfolio_candidate": current[0].get("portfolio_candidate"),
                }
            return {
                "status": "no_bet",
                "reason_codes": ["risk_limit"],
                "reason": "组合风险门禁未通过，未执行 Paper Execution",
                "bet_id": None,
                "execution_id": None,
                "execution_status": "REJECTED",
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
                "execution_id": None,
                "execution_status": "REJECTED",
            }
        return {
            "status": "no_bet",
            "reason_codes": ["risk_limit"],
            "reason": "模拟账户当日剩余额度不足以满足最低10%仓位",
            "bet_id": None,
            "execution_id": None,
            "execution_status": "REJECTED",
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
                current = deepcopy(current)
                _complete_candidate_decision(current, candidate_context, self.repository)
            if not current:
                continue
            if self.portfolio_config is not None:
                candidates = build_candidates(
                    current,
                    grouped_fixture,
                    self.portfolio_config,
                    historical_clv=self._historical_clv(),
                )
                if candidates:
                    current["portfolio_candidate"] = candidates[0].to_dict()
                    rows.append((current, grouped_fixture))
            elif _eligible_candidate(current, grouped_fixture):
                rows.append((current, grouped_fixture))
        if self.portfolio_config is not None:
            return sorted(
                rows,
                key=lambda item: -float((item[0].get("portfolio_candidate") or {}).get("candidate_score") or 0),
            )
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

    def _historical_clv(self) -> float | None:
        values = [
            float(item["clv"])
            for item in self.repository.bets(
                status="settled",
                model_key=self.model_key,
                competition_id=self.competition_id,
            )
            if item.get("clv") is not None
        ]
        return round(sum(values) / len(values), 6) if values else None

    def _place_candidate(
        self,
        prediction: dict[str, Any],
        fixture: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.portfolio_config is not None:
            return self._place_portfolio_candidate(prediction, fixture)
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
                "bet_odds": round(price, 3),
                "stake": stake,
                "league_key": fixture["league_key"],
                "kickoff": fixture["kickoff"],
                "home_team": fixture["home_team"].get("name"),
                "away_team": fixture["away_team"].get("name"),
                "model_version": prediction["model_version"],
                "model_confidence": decision.get("model_confidence"),
                "expected_edge": round(edge, 4),
                "bookmaker": market_row.get("bookmaker"),
                "line_at_bet": (
                    market_row.get("line")
                    if market_row.get("line") is not None
                    else (prediction.get("asian_handicap") or {}).get("line")
                ) if market == "asian_handicap" else None,
                "odds_snapshot_id": prediction.get("odds_snapshot_id"),
                "reason": decision.get("reason"),
                "reason_codes": decision.get("reason_codes") or [],
                "prediction_phase": prediction.get("phase") or "preliminary",
                "lineup_confirmed": bool(((fixture.get("evidence") or {}).get("lineup") or {}).get("confirmed")),
                "is_simulated": True,
                "model_key": self.model_key,
                "competition_id": self.competition_id,
            }
        )

    def _place_portfolio_candidate(
        self,
        prediction: dict[str, Any],
        fixture: dict[str, Any],
    ) -> dict[str, Any] | None:
        candidate = prediction.get("portfolio_candidate")
        if not isinstance(candidate, dict):
            candidates = build_candidates(
                prediction,
                fixture,
                self.portfolio_config,
                historical_clv=self._historical_clv(),
            )
            candidate = candidates[0].to_dict() if candidates else None
        if not candidate:
            return None
        bets = self.repository.bets(competition_id=self.competition_id)
        active = [item for item in bets if str(item.get("status") or "").lower() in {"placed", "pending", "executed", "selected"}]
        open_exposure = sum(float(item.get("stake") or 0) for item in active)
        own_open_exposure = sum(
            float(item.get("stake") or 0)
            for item in active
            if item.get("model_key") == self.model_key
        )
        bankroll = self.repository.current_balance(self.model_key, self.competition_id) + own_open_exposure
        selected = select_portfolio(
            [candidate],
            bankroll,
            existing_bets=bets,
            config=self.portfolio_config,
            drawdown=float(self.summary().get("max_drawdown") or 0),
        )
        if not selected:
            return None
        selected_candidate = selected[0]
        stake = float(selected_candidate.get("stake") or 0)
        if stake <= 0:
            return None
        execution_id = f"execution:{uuid.uuid4()}"
        decision = prediction.get("decision") or {}
        payload = {
            "id": str(uuid.uuid4()),
            "execution_id": execution_id,
            "prediction_id": prediction["id"],
            "fixture_id": fixture["id"],
            "fixture_date": fixture["fixture_date"],
            "placed_at": datetime.now(UTC).isoformat(),
            "market": selected_candidate.get("market") or decision.get("market"),
            "selection": selected_candidate.get("selection") or decision.get("selection"),
            "handicap_line": selected_candidate.get("line"),
            "line_at_bet": selected_candidate.get("line"),
            "odds": selected_candidate.get("odds"),
            "bet_odds": selected_candidate.get("odds"),
            "stake": stake,
            "league_key": fixture.get("league_key"),
            "kickoff": fixture.get("kickoff"),
            "home_team": (fixture.get("home_team") or {}).get("name"),
            "away_team": (fixture.get("away_team") or {}).get("name"),
            "model_version": prediction.get("model_version"),
            "model_key": self.model_key,
            "competition_id": self.competition_id,
            "model_confidence": selected_candidate.get("confidence"),
            "model_probability": selected_candidate.get("model_probability"),
            "market_probability": selected_candidate.get("market_probability"),
            "edge": selected_candidate.get("edge"),
            "ev": selected_candidate.get("ev"),
            "expected_edge": selected_candidate.get("ev"),
            "risk_score": selected_candidate.get("risk_score"),
            "data_quality": selected_candidate.get("data_quality"),
            "odds_age_minutes": selected_candidate.get("odds_age_minutes"),
            "candidate_score": selected_candidate.get("candidate_score"),
            "correlation_group": selected_candidate.get("correlation_group") or fixture.get("id"),
            "bookmaker": selected_candidate.get("bookmaker"),
            "odds_snapshot_id": selected_candidate.get("odds_snapshot_id") or prediction.get("odds_snapshot_id"),
            "portfolio_selection": "selected",
            "risk_gate": selected_candidate.get("risk_gate"),
            "reason": decision.get("reason"),
            "reason_codes": decision.get("reason_codes") or [],
            "prediction_phase": prediction.get("phase") or "preliminary",
            "is_simulated": True,
        }
        placed = self.repository.place_bet(payload)
        if placed and callable(getattr(self.repository, "create_bet_execution", None)):
            self.repository.create_bet_execution(
                {
                    "execution_id": execution_id,
                    "prediction_id": placed["prediction_id"],
                    "fixture_id": placed["fixture_id"],
                    "fixture_date": placed.get("fixture_date"),
                    "model_key": placed.get("model_key"),
                    "competition_id": placed.get("competition_id"),
                    "market": placed.get("market"),
                    "selection": placed.get("selection"),
                    "line": placed.get("line_at_bet") or placed.get("handicap_line"),
                    "odds": placed.get("bet_odds") or placed.get("odds"),
                    "stake": placed.get("stake"),
                    "requested_at": placed.get("placed_at"),
                    "executed_at": placed.get("placed_at"),
                    "status": "EXECUTED",
                    "source": "paper",
                    "payload": placed,
                }
            )
        return placed

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
        active_exposure = round(sum(float(item.get("stake") or 0) for item in open_bets), 2)
        betting_drawdown = _max_drawdown(settled)
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
            "max_drawdown": betting_drawdown,
            "equity_curve": _equity_curve(settled, transactions),
            "is_simulated": True,
            "model_key": self.model_key,
            "competition_id": self.competition_id,
            "active_exposure": active_exposure,
            "total_exposure": active_exposure,
            "drawdown_limit": self.portfolio_config.max_drawdown if self.portfolio_config else None,
            "risk_gate_status": (
                "FAIL" if self.portfolio_config and betting_drawdown >= self.portfolio_config.max_drawdown else "PASS"
            ) if self.portfolio_config else None,
            "portfolio_policy": (
                {
                    "min_edge": self.portfolio_config.min_edge,
                    "min_ev": self.portfolio_config.min_ev,
                    "stake_fraction": self.portfolio_config.stake_fraction,
                    "max_single_bet_fraction": self.portfolio_config.max_single_bet_fraction,
                    "max_daily_exposure": self.portfolio_config.max_daily_exposure,
                    "max_league_exposure": self.portfolio_config.max_league_exposure,
                    "max_total_exposure": self.portfolio_config.max_total_exposure,
                    "max_drawdown": self.portfolio_config.max_drawdown,
                }
                if self.portfolio_config
                else None
            ),
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


def _complete_candidate_decision(
    prediction: dict[str, Any],
    context: dict[str, Any],
    repository: Any | None = None,
) -> None:
    odds = context.get("odds")
    snapshot_id = prediction.get("odds_snapshot_id")
    reader = getattr(repository, "odds_snapshot", None) if repository is not None else None
    if snapshot_id and callable(reader):
        snapshot = reader(str(snapshot_id))
        if snapshot and isinstance(snapshot.get("payload"), dict):
            odds = snapshot["payload"]
    prediction["market_assessment"] = assess_markets(prediction, odds)
    prediction["market_assessment"]["odds_snapshot_id"] = snapshot_id
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
                "edge": None,
                "ev": None,
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
            "edge": candidate.get("edge"),
            "ev": candidate.get("ev") or candidate.get("expected_edge"),
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


def _bet_matches_candidate(
    bet: dict[str, Any],
    prediction: dict[str, Any],
    portfolio_config: PortfolioConfig | None = None,
) -> bool:
    decision = prediction.get("decision") or {}
    balance_before = float(bet.get("balance_before") or 0)
    actual_fraction = float(bet.get("stake") or 0) / balance_before if balance_before > 0 else 0.0
    candidate = prediction.get("portfolio_candidate") or {}
    expected = candidate.get("ev") if portfolio_config is not None else decision.get("expected_edge")
    stored_expected = bet.get("ev") if portfolio_config is not None else bet.get("expected_edge")
    lower_fraction = 0.0 if portfolio_config is not None else MIN_FIXTURE_EXPOSURE
    upper_fraction = portfolio_config.max_single_bet_fraction if portfolio_config is not None else MAX_FIXTURE_EXPOSURE
    return bool(
        bet.get("status") == "placed"
        and bet.get("market") == decision.get("market")
        and bet.get("selection") == decision.get("selection")
        and lower_fraction <= actual_fraction <= upper_fraction
        and abs(float(stored_expected or 0) - float(expected or 0)) < 0.0001
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
