"""Simulated bankroll placement rules and aggregate reporting."""

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from .market_decision import assess_markets
from .portfolio import (
    PortfolioConfig,
    build_candidates,
    calculate_drawdown,
    exposure_snapshot,
    is_active_bet,
    risk_gate,
    select_best_candidates,
    select_portfolio,
)


INITIAL_BANKROLL = 1000.0


class BankrollService:
    """Place bounded simulated bets from deterministic backend decisions."""

    def __init__(self, repository: Any, portfolio_config: PortfolioConfig | None = None) -> None:
        self.repository = repository
        self.portfolio_config = portfolio_config or PortfolioConfig()
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
        if not candidates:
            return None

        selected_prediction, selected_fixture = candidates[0]
        locked = next((bet for bet in group_bets if bet.get("fixture_id") == fixture.get("id")), None)
        if locked:
            locked_candidate = next(
                (item for item in candidates if item[1].get("id") == fixture.get("id")),
                None,
            )
            if locked_candidate is None:
                return locked
            locked_prediction, locked_fixture = locked_candidate
            expected_stake = self._canonical_stake(
                locked_prediction.get("portfolio_candidate") or {},
                locked_fixture,
                exclude_bet_id=locked.get("id"),
            )
            if _bet_matches_candidate(locked, locked_prediction, expected_stake=expected_stake):
                return locked
            if callable(discard):
                discard(locked_fixture["id"], self.model_key, self.competition_id)
        existing_selected = self.repository.bet_for_prediction(selected_prediction["id"])
        if existing_selected and _bet_matches_candidate(existing_selected, selected_prediction):
            return existing_selected
        if existing_selected and callable(discard):
            discard(selected_fixture["id"], self.model_key, self.competition_id)
        return self._place_candidate(selected_prediction, selected_fixture)

    def candidate_for_prediction(
        self,
        prediction: dict[str, Any],
        fixture: dict[str, Any],
        context: dict[str, Any],
    ) -> Any | None:
        """Build one derived Portfolio candidate without persisting or mutating prediction."""

        working_prediction = deepcopy(prediction)
        _complete_candidate_decision(working_prediction, context, self.repository)
        candidates = build_candidates(
            working_prediction,
            fixture,
            self.portfolio_config,
            historical_clv=self._historical_clv(),
        )
        return candidates[0] if candidates else None

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
                "reason": "候选未同时满足 Portfolio 的 Edge、EV、数据质量或赔率新鲜度门槛",
                "bet_id": None,
                "execution_id": None,
                "execution_status": "REJECTED",
            }
        all_bets = self.repository.bets(competition_id=self.competition_id)
        account_bets = [item for item in all_bets if item.get("model_key") == self.model_key]
        transactions = self.repository.bankroll_transactions(self.model_key, self.competition_id)
        snapshot = exposure_snapshot(
            account_bets,
            transactions,
            fixture_date=fixture.get("fixture_date"),
            league_key=fixture.get("league_key"),
        )
        selected = select_portfolio(
            [current[0].get("portfolio_candidate") or {}],
            account_snapshot=snapshot,
            existing_bets=account_bets,
            correlation_bets=all_bets,
            config=self.portfolio_config,
            drawdown=float(self.summary().get("max_drawdown") or 0),
        )
        if selected:
            return {
                "status": "candidate",
                "reason_codes": [],
                "reason": "候选已通过 Portfolio 风险门禁，等待 Paper Execution",
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
            "reason": "Portfolio 风险门禁未通过，未执行 Paper Execution",
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
            candidates = build_candidates(
                current,
                grouped_fixture,
                self.portfolio_config,
                historical_clv=self._historical_clv(),
            )
            if candidates:
                current["portfolio_candidate"] = candidates[0].to_dict()
                rows.append((current, grouped_fixture))
        return sorted(
            rows,
            key=lambda item: (
                -float((item[0].get("portfolio_candidate") or {}).get("candidate_score") or 0),
                str((item[0].get("portfolio_candidate") or {}).get("model_key") or ""),
                str(item[0].get("id") or ""),
            ),
        )

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
        return self._place_portfolio_candidate(prediction, fixture)

    def _canonical_stake(
        self,
        candidate: dict[str, Any],
        fixture: dict[str, Any],
        *,
        exclude_bet_id: str | None = None,
    ) -> float:
        bets = self.repository.bets(model_key=self.model_key, competition_id=self.competition_id)
        account_bets = [item for item in bets if item.get("id") != exclude_bet_id]
        transactions = [
            item
            for item in self.repository.bankroll_transactions(self.model_key, self.competition_id)
            if item.get("reference_id") != exclude_bet_id
        ]
        snapshot = exposure_snapshot(
            account_bets,
            transactions,
            fixture_date=fixture.get("fixture_date"),
            league_key=fixture.get("league_key"),
        )
        gate = risk_gate(
            candidate,
            snapshot["equity"],
            daily_exposure=snapshot["daily_exposure"],
            league_exposure=snapshot["league_exposure"],
            total_exposure=snapshot["total_exposure"],
            drawdown=float(self.summary().get("max_drawdown") or 0),
            config=self.portfolio_config,
        )
        return float(gate["allowed_stake"] if gate["status"] == "PASS" else 0.0)

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
        all_bets = self.repository.bets(competition_id=self.competition_id)
        account_bets = [item for item in all_bets if item.get("model_key") == self.model_key]
        transactions = self.repository.bankroll_transactions(self.model_key, self.competition_id)
        account_snapshot = exposure_snapshot(
            account_bets,
            transactions,
            fixture_date=fixture.get("fixture_date"),
            league_key=fixture.get("league_key"),
        )
        selected = select_portfolio(
            [candidate],
            account_snapshot=account_snapshot,
            existing_bets=account_bets,
            correlation_bets=all_bets,
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
        open_bets = [item for item in bets if is_active_bet(item.get("status"))]
        total_staked = round(sum(float(item["stake"]) for item in bets), 2)
        settled_staked = round(sum(float(item["stake"]) for item in settled), 2)
        total_returns = round(sum(float(item.get("return_amount") or 0) for item in settled), 2)
        transactions = self.repository.bankroll_transactions(self.model_key, self.competition_id)
        account = exposure_snapshot(bets, transactions)
        balance = account["cash_balance"]
        open_exposure = account["open_exposure"]
        realized_profit = round(sum(float(item.get("net_profit") or 0) for item in settled), 2)
        profitable = sum(1 for item in settled if float(item.get("net_profit") or 0) > 0)
        decided = sum(1 for item in settled if item.get("settlement_result") != "push")
        betting_drawdown = calculate_drawdown(_equity_curve(settled, transactions), INITIAL_BANKROLL)
        return {
            "initial_balance": INITIAL_BANKROLL,
            "balance": balance,
            "cash_balance": balance,
            "equity": account["equity"],
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
            "active_exposure": open_exposure,
            "total_exposure": account["total_exposure"],
            "drawdown_limit": self.portfolio_config.max_drawdown,
            "risk_gate_status": "FAIL" if betting_drawdown >= self.portfolio_config.max_drawdown else "PASS",
            "portfolio_policy": {
                "min_edge": self.portfolio_config.min_edge,
                "min_ev": self.portfolio_config.min_ev,
                "stake_fraction": self.portfolio_config.stake_fraction,
                "max_single_bet_fraction": self.portfolio_config.max_single_bet_fraction,
                "max_daily_exposure": self.portfolio_config.max_daily_exposure,
                "max_league_exposure": self.portfolio_config.max_league_exposure,
                "max_total_exposure": self.portfolio_config.max_total_exposure,
                "max_drawdown": self.portfolio_config.max_drawdown,
            },
        }


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


def _bet_matches_candidate(
    bet: dict[str, Any],
    prediction: dict[str, Any],
    *,
    expected_stake: float | None = None,
) -> bool:
    decision = prediction.get("decision") or {}
    candidate = prediction.get("portfolio_candidate") or {}
    expected = candidate.get("ev")
    stored_expected = bet.get("ev")
    return bool(
        bet.get("status") == "placed"
        and bet.get("market") == decision.get("market")
        and bet.get("selection") == decision.get("selection")
        and abs(float(stored_expected or 0) - float(expected or 0)) < 0.0001
        and (
            expected_stake is None
            or abs(float(bet.get("stake") or 0) - expected_stake) < 0.0001
        )
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
        by_prediction_id = {str(prediction.get("id")): prediction for prediction in predictions}
        candidates = []
        for prediction in predictions:
            model_key = prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "deepseek"
            service = self.services.get(model_key)
            if service is None:
                continue
            candidate = service.candidate_for_prediction(prediction, fixture, context)
            if candidate is not None:
                candidates.append(candidate)
        selected = select_best_candidates(candidates)
        bets: list[dict[str, Any]] = []
        for candidate in selected:
            prediction = by_prediction_id.get(str(getattr(candidate, "prediction_id", None)))
            if prediction is None:
                continue
            if bet := self.place_for_prediction(prediction, fixture, context):
                bets.append(bet)
        return bets

    def select_portfolio_candidates(self, candidates: list[Any]) -> list[Any]:
        """Expose the shared global candidate selection boundary for callers/tests."""

        return select_best_candidates(candidates)

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
