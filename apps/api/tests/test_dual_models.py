import asyncio
from datetime import UTC, datetime

from app.bankroll import BankrollService
from app.database import PredictionRepository
from app.dual_prediction_service import DualPredictionService


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


def test_models_have_independent_accounts_but_cannot_bypass_risk_cap(tmp_path) -> None:
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
    deepseek = BankrollService(repository).configure("deepseek", "dual", uncapped=True)
    chatgpt = BankrollService(repository).configure("chatgpt", "dual", uncapped=True)

    first = deepseek.place_for_prediction(prediction("deepseek", "prediction-deepseek"), fixture(), context)
    second = chatgpt.place_for_prediction(prediction("chatgpt", "prediction-chatgpt"), fixture(), context)

    assert first is not None and first["stake"] == 250.0
    assert second is not None and second["stake"] == 250.0
    assert repository.current_balance("deepseek", "dual") == 750.0
    assert repository.current_balance("chatgpt", "dual") == 750.0
    assert len(repository.bets(competition_id="dual")) == 2
