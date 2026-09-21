import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from types import MethodType, SimpleNamespace

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


def test_dual_service_delegates_shared_context_preparation_to_primary() -> None:
    started: list[str] = []

    class PreparingService(FakePredictionService):
        async def prepare_context(self, current_fixture: dict, context: dict, *, prediction_timestamp=None) -> dict:
            started.append(f"prepare:{self.model_key}")
            context["prepared_fixture"] = current_fixture["id"]
            context["prediction_timestamp"] = prediction_timestamp
            return context

    service = DualPredictionService(
        {
            "deepseek": PreparingService("deepseek", started),
            "chatgpt": PreparingService("chatgpt", started),
        },
        "dual",
        player_name_service=FakePlayerNameService(started),
    )
    context: dict = {}

    result = asyncio.run(
        service.prepare_context(
            fixture(),
            context,
            prediction_timestamp="2099-08-27T10:00:00+00:00",
        )
    )

    assert result is context
    assert context["prepared_fixture"] == "dual-fixture"
    assert context["prediction_timestamp"] == "2099-08-27T10:00:00+00:00"
    assert started == ["player-names", "prepare:deepseek"]


def test_dual_models_assign_one_production_evidence_owner() -> None:
    ownership: dict[str, bool] = {}

    class Service(FakePredictionService):
        async def create(
            self,
            fixture: dict,
            context: dict,
            persist_production_evidence: bool = True,
        ) -> dict:
            ownership[self.model_key] = persist_production_evidence
            return {
                "id": f"prediction-{self.model_key}",
                "model_key": self.model_key,
                "model_probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
            }

    started: list[str] = []
    service = DualPredictionService(
        {
            "deepseek": Service("deepseek", started),
            "chatgpt": Service("chatgpt", started),
        },
        "dual",
    )

    results = asyncio.run(service.create(fixture(), {}))

    assert len(results) == 2
    assert ownership == {"deepseek": True, "chatgpt": False}


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


def test_live_ensemble_uses_registry_weights_and_keeps_poisson_baseline() -> None:
    class Service:
        def __init__(self, model_key: str) -> None:
            self.model_key = model_key
            self.model_provider = FakeProvider()

        async def create(self, _fixture: dict, _context: dict) -> dict:
            return {
                "id": f"prediction-{self.model_key}",
                "model_key": self.model_key,
                "model_probabilities": {"home": 0.7, "draw": 0.2, "away": 0.1},
                "baseline": {"probabilities": {"home": 0.3, "draw": 0.3, "away": 0.4}},
            }

    class Registry:
        def champion(self, model_key: str) -> SimpleNamespace:
            assert model_key == "ensemble"
            return SimpleNamespace(payload={"weights": {"deepseek": 0.1, "chatgpt": 0.2, "poisson": 0.7}})

    service = DualPredictionService(
        {"deepseek": Service("deepseek"), "chatgpt": Service("chatgpt")},
        "dual",
        model_registry_service=Registry(),
    )

    results = asyncio.run(service.create(fixture(), {}))

    ensemble = results[0]["p3_ensemble"]
    assert ensemble["weights_source"] == "model_registry"
    assert ensemble["weights"]["poisson"] == 0.7
    assert ensemble["base_predictions"]["poisson"] == {"home": 0.3, "draw": 0.3, "away": 0.4}


def test_ensemble_annotation_does_not_mutate_saved_pre_match_prediction() -> None:
    class Repository:
        def __init__(self) -> None:
            self.saved: list[dict] = []

        def fixture_settlements(self, **_filters: object) -> list[dict]:
            return []

        def update_prediction(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("an ensemble annotation must not update a frozen prediction")

    class Service:
        def __init__(self, model_key: str, repository: Repository) -> None:
            self.model_key = model_key
            self.model_provider = FakeProvider()
            self.repository = repository

        async def create(self, _fixture: dict, _context: dict) -> dict:
            result = {
                "id": f"prediction-{self.model_key}",
                "model_key": self.model_key,
                "model_probabilities": {"home": 0.7, "draw": 0.2, "away": 0.1},
            }
            self.repository.saved.append(deepcopy(result))
            return result

    repository = Repository()
    service = DualPredictionService(
        {"deepseek": Service("deepseek", repository), "chatgpt": Service("chatgpt", repository)},
        "dual",
    )

    results = asyncio.run(service.create(fixture(), {}))

    assert results[0]["p3_ensemble"]["ensemble_probabilities"]
    assert all("p3_ensemble" not in item for item in repository.saved)


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


def test_shadow_model_cannot_displace_or_create_simulated_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "shadow.db"), "dual", ("deepseek", "chatgpt"))
    repository.initialize()
    context = {
        "odds": {
            "home": 2.1,
            "draw": 3.2,
            "away": 3.6,
            "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
    }
    deepseek = BankrollService(repository, PortfolioConfig()).configure(
        "deepseek",
        "dual",
        execution_mode="shadow",
    )
    chatgpt = BankrollService(repository, PortfolioConfig()).configure(
        "chatgpt",
        "dual",
        execution_mode="active",
    )
    services = {"deepseek": deepseek, "chatgpt": chatgpt}
    dual = DualBankrollService(services, "dual")
    deepseek_prediction = prediction("deepseek", "prediction-deepseek-shadow")
    chatgpt_prediction = prediction("chatgpt", "prediction-chatgpt-active")

    def fixed_candidate(self, item, _fixture, _context):
        score = {"deepseek": 0.99, "chatgpt": 0.90}[self.model_key]
        return candidate(self.model_key, item["id"], score)

    for service in services.values():
        service.candidate_for_prediction = MethodType(fixed_candidate, service)

    deepseek_transactions_before = repository.bankroll_transactions("deepseek", "dual")
    assert deepseek.place_for_candidate(
        deepseek_prediction,
        fixture(),
        candidate("deepseek", deepseek_prediction["id"], 0.99),
    ) is None

    bets = dual.place_for_predictions(
        [deepseek_prediction, chatgpt_prediction],
        fixture(),
        context,
    )

    assert [bet["model_key"] for bet in bets] == ["chatgpt"]
    assert repository.bets(model_key="deepseek", competition_id="dual") == []
    assert repository.bankroll_transactions("deepseek", "dual") == deepseek_transactions_before
    assert all(
        execution["model_key"] != "deepseek"
        for execution in repository.bet_executions(competition_id="dual")
    )
    assert deepseek.execution_for_prediction(
        deepseek_prediction,
        fixture(),
        linked_bet=None,
        bet_lookup_complete=True,
    ) == {
        "status": "no_bet",
        "reason_codes": ["model_shadow_only"],
        "reason": "模型仅观察，不执行模拟下注",
        "bet_id": None,
        "execution_id": None,
        "execution_status": "REJECTED",
    }


def test_failed_ai_does_not_place_poisson_fallback_bet() -> None:
    class Service:
        def candidate_for_prediction(self, *_args):
            return None

        def candidate_for_poisson(self, *_args):
            raise AssertionError("failed AI must not use Poisson for automatic betting")

    dual = DualBankrollService({"chatgpt": Service()}, "dual")
    failed_prediction = prediction("chatgpt", "prediction-failed")
    failed_prediction["ai"] = {"status": "failed"}

    assert dual.place_for_predictions([failed_prediction], fixture(), {}) == []


def test_invalidated_candidate_releases_previous_open_fixture_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "stale-bet.db"), "dual", ("chatgpt",))
    repository.initialize()
    repository.place_bet(
        {
            "id": "bet-old",
            "prediction_id": "prediction-old",
            "fixture_id": "dual-fixture",
            "fixture_date": "2099-08-27",
            "placed_at": datetime.now(UTC).isoformat(),
            "model_key": "chatgpt",
            "competition_id": "dual",
            "odds": 2.1,
            "stake": 100.0,
        }
    )

    class Service:
        def __init__(self, repository):
            self.repository = repository

        def candidate_for_prediction(self, *_args):
            return None

        def candidate_for_poisson(self, *_args):
            return None

    dual = DualBankrollService({"chatgpt": Service(repository)}, "dual")
    current = prediction("chatgpt", "prediction-new")

    assert dual.place_for_predictions([current], fixture(), {}) == []
    assert repository.bets(model_key="chatgpt", competition_id="dual") == []


def test_poisson_fallback_cannot_bet_against_ai_predicted_outcome() -> None:
    """The deterministic baseline is a calculator, not an opinion: it may not
    bet against the direction the AI research concluded (e.g. laying a huge
    favourite on thin xG data)."""

    from dataclasses import replace as dc_replace

    away_candidate = dc_replace(candidate("poisson", "prediction-chatgpt", 0.9), selection="away")

    class Service:
        configured = True
        placed: list = []

        def candidate_for_prediction(self, *_args):
            return None

        def candidate_for_poisson(self, *_args):
            return away_candidate

        def place_for_candidate(self, prediction, fixture, candidate, fixed_stake=None):
            Service.placed.append(candidate)
            return {"model_key": "chatgpt", "stake": 100.0}

    service = Service()
    dual = DualBankrollService({"chatgpt": service}, "dual")
    ai_prediction = prediction("chatgpt", "prediction-chatgpt")
    ai_prediction["predicted_outcome"] = "home"

    bets = dual.place_for_predictions([ai_prediction], fixture(), {})

    assert bets == []
    assert service.placed == []


def test_poisson_fallback_bets_along_ai_predicted_outcome() -> None:
    from dataclasses import replace as dc_replace

    away_candidate = dc_replace(candidate("poisson", "prediction-chatgpt", 0.9), selection="away")

    class Service:
        configured = True

        def candidate_for_prediction(self, *_args):
            return None

        def candidate_for_poisson(self, *_args):
            return away_candidate

        def place_for_candidate(self, prediction, fixture, candidate, fixed_stake=None):
            return {"model_key": "chatgpt", "stake": 100.0}

    dual = DualBankrollService({"chatgpt": Service()}, "dual")
    ai_prediction = prediction("chatgpt", "prediction-chatgpt")
    ai_prediction["predicted_outcome"] = "away"

    bets = dual.place_for_predictions([ai_prediction], fixture(), {})

    assert len(bets) == 1
