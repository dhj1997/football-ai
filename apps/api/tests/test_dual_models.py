import asyncio
from datetime import UTC, datetime
from types import MethodType

from app.bankroll import BankrollService, DualBankrollService
from app.database import PredictionRepository
from app.dual_prediction_service import DualPredictionService
from app.portfolio import BetCandidate, PortfolioConfig


class FakeProvider:
    configured = True


class FakePredictionService:
    def __init__(self, model_key: str, started: list[str]) -> None:
        self.model_key = model_key
        self.model_provider = FakeProvider()
        self.started = started

    async def create(self, fixture: dict, context: dict) -> dict:
        self.started.append(self.model_key)
        await asyncio.sleep(0)
        return {"id": f"prediction-{self.model_key}", "model_key": self.model_key}


class FakePlayerNameService:
    def __init__(self, started: list[str]) -> None:
        self.started = started

    async def enrich(self, context: dict, resolve_missing: bool = False) -> dict:
        assert resolve_missing is True
        self.started.append("player-names")
        return context


def fixture() -> dict:
    return {
        "id": "dual-fixture",
        "fixture_date": "2099-08-27",
        "kickoff": "2099-08-27T12:00:00+00:00",
        "status": "scheduled",
        "league_key": "epl",
        "home_team": {"name": "主队"},
        "away_team": {"name": "客队"},
    }


def prediction(model_key: str, prediction_id: str) -> dict:
    return {
        "id": prediction_id,
        "fixture_id": "dual-fixture",
        "model_key": model_key,
        "competition_id": "dual",
        "model_version": f"{model_key}:test",
        "probabilities": {"home": 0.7, "draw": 0.2, "away": 0.1},
        "data_completeness": 0.9,
        "ai": {"status": "completed"},
        "decision": {
            "status": "bet",
            "market": "1x2",
            "selection": "home",
            "model_confidence": 0.8,
            "stake_fraction": 0.5 if model_key == "deepseek" else 0.25,
            "reason": "测试执行",
            "reason_codes": [],
        },
    }


def candidate(model_key: str, prediction_id: str, score: float) -> BetCandidate:
    return BetCandidate(
        fixture_id="dual-fixture",
        fixture_date="2099-08-27",
        league_key="epl",
        prediction_id=prediction_id,
        model_key=model_key,
        market="1x2",
        selection="home",
        line=None,
        odds=2.1,
        model_probability=0.7,
        market_probability=0.5,
        edge=0.2,
        ev=0.47,
        risk_score=0.1,
        data_quality=0.9,
        odds_age_minutes=0.0,
        confidence=0.8,
        correlation_group="dual-fixture",
        candidate_score=score,
    )


def test_prediction_services_run_for_both_models() -> None:
    started: list[str] = []
    service = DualPredictionService(
        {
            "deepseek": FakePredictionService("deepseek", started),
            "chatgpt": FakePredictionService("chatgpt", started),
        },
        "dual",
    )

    results = asyncio.run(service.create(fixture(), {}))

    assert {item["model_key"] for item in results} == {"deepseek", "chatgpt"}
    assert set(started) == {"deepseek", "chatgpt"}


def test_player_names_are_resolved_once_before_both_models() -> None:
    started: list[str] = []
    service = DualPredictionService(
        {
            "deepseek": FakePredictionService("deepseek", started),
            "chatgpt": FakePredictionService("chatgpt", started),
        },
        "dual",
        FakePlayerNameService(started),
    )

    asyncio.run(service.create(fixture(), {}))

    assert started[0] == "player-names"
    assert started.count("player-names") == 1


def test_bankroll_service_global_selection_creates_one_bet_and_execution(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "dual.db"), "dual", ("deepseek", "chatgpt"))
    repository.initialize()
    context = {
        "odds": {
            "home": 2.1,
            "draw": 3.2,
            "away": 3.6,
            "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
    }
    services = {
        model_key: BankrollService(repository, PortfolioConfig()).configure(model_key, "dual")
        for model_key in ("deepseek", "chatgpt")
    }
    dual = DualBankrollService(services, "dual")
    deepseek_prediction = prediction("deepseek", "prediction-deepseek")
    chatgpt_prediction = prediction("chatgpt", "prediction-chatgpt")

    def fixed_candidate(self, item, _fixture, _context):
        score = {"deepseek": 0.80, "chatgpt": 0.90}[self.model_key]
        return candidate(self.model_key, item["id"], score)

    def forbidden_placement(self, *_args):
        raise AssertionError("global selection must bypass per-model placement")

    for service in services.values():
        service.candidate_for_prediction = MethodType(fixed_candidate, service)
        service.place_for_prediction = MethodType(forbidden_placement, service)
    poisson_candidate = candidate("poisson", "prediction-poisson", 0.70)

    bets = dual.place_for_predictions(
        [deepseek_prediction, chatgpt_prediction],
        fixture(),
        context,
        additional_candidates=[poisson_candidate],
    )

    assert len(bets) == 1
    assert bets[0]["model_key"] == "chatgpt"
    assert bets[0]["candidate_score"] == 0.90
    assert len(repository.bet_executions(competition_id="dual")) == 1
    assert repository.current_balance("deepseek", "dual") == 1000.0
    assert repository.current_balance("chatgpt", "dual") == 990.0

    selected = dual.select_portfolio_candidates(
        [candidate("deepseek", "prediction-deepseek", 0.8), candidate("chatgpt", "prediction-chatgpt", 0.9), candidate("poisson", "prediction-poisson", 0.7)]
    )
    assert len(selected) == 1
    assert selected[0].model_key == "chatgpt"
