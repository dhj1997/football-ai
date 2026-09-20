"""模型质量三件套测试：历史扩充、参数拟合、集成权重学习。"""

import asyncio
import random
from datetime import UTC, datetime, timedelta

import pytest

from app.automation import AutomationRunner
from app.config import get_settings
from app.database import PredictionRepository
from app.model_fitting import fit_from_repository, fit_league, fitted_record, load_fitted_params
from app.model_registry import ModelRecord, ModelRegistry
from app.prediction import predict, set_fitted_params_provider


def _finished_fixture(fixture_id: str, league_key: str, kickoff: datetime, home: int, away: int) -> dict:
    return {
        "id": fixture_id,
        "provider_id": 1,
        "league_key": league_key,
        "fixture_date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "status": "finished",
        "home_team": {"name": "主队"},
        "away_team": {"name": "客队"},
        "score": {"home": home, "away": away},
        "is_demo": False,
    }


def test_fit_league_recovers_poisson_means_and_negative_rho() -> None:
    rng = random.Random(7)
    scores = []
    for _ in range(400):
        home = min(8, max(0, int(rng.gauss(1.6, 1.1))))
        away = min(8, max(0, int(rng.gauss(1.15, 1.0))))
        scores.append((home, away))

    fitted = fit_league(scores)

    assert fitted["status"] == "ok"
    assert fitted["n"] == 400
    # xG 均值是闭式 MLE：必须精确等于样本均值（生成器有截断，不能假设名义参数）。
    empirical_home = sum(h for h, _ in scores) / len(scores)
    empirical_away = sum(a for _, a in scores) / len(scores)
    assert fitted["home_xg"] == pytest.approx(empirical_home, abs=0.001)
    assert fitted["away_xg"] == pytest.approx(empirical_away, abs=0.001)
    assert -0.25 <= fitted["rho"] <= 0.0
    assert fitted["log_likelihood"] < 0


def test_fit_league_requires_minimum_sample() -> None:
    assert fit_league([(1, 1)] * 10)["status"] == "insufficient_sample"


def test_fit_from_repository_registers_and_loads(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "fit.db"))
    repository.initialize()
    rng = random.Random(9)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    index = 0
    for league in ("epl", "laliga"):
        for _ in range(60):
            repository.upsert_fixture(
                _finished_fixture(
                    f"{league}-{index}",
                    league,
                    start + timedelta(days=index % 200),
                    min(6, max(0, int(rng.gauss(1.5, 1.0)))),
                    min(6, max(0, int(rng.gauss(1.1, 0.9)))),
                )
            )
            index += 1

    fitted = fit_from_repository(repository)
    registry = ModelRegistry(repository)
    registry.register(ModelRecord(**fitted_record(fitted)))

    assert fitted["fitted_version"].startswith("dc-fit-")
    assert fitted["dataset"]["finished_matches"] == 120
    assert set(fitted["leagues"]) == {"epl", "laliga"}
    assert fitted["leagues"]["epl"]["n"] == 60
    assert fitted["dataset"]["training_cutoff"] == (
        max(
            datetime.fromisoformat(item["kickoff"])
            for item in repository.list_fixtures()
        )
        + timedelta(hours=3)
    ).isoformat()

    loaded = load_fitted_params(repository)
    assert loaded is not None
    assert loaded["fitted_version"] == fitted["fitted_version"]
    assert "epl" in loaded["leagues"]


def test_prediction_uses_fitted_params_version_suffix() -> None:
    fixture = {"id": "f1", "league_key": "epl", "is_demo": False}
    context = {
        "recent_form": {"home": [], "away": [], "updated_at": "2026-09-01T00:00:00+00:00"},
        "lineup": {"confirmed": False, "home_strength": None, "away_strength": None, "updated_at": "2026-09-01T00:00:00+00:00"},
        "availability": {"updated_at": "2026-09-01T00:00:00+00:00"},
        "player_impact": {},
    }
    try:
        set_fitted_params_provider(
            lambda: {
                "fitted_version": "dc-fit-test",
                "training_cutoff": "2026-08-31T00:00:00+00:00",
                "leagues": {"epl": {"home_xg": 1.7, "away_xg": 1.0, "rho": -0.08, "n": 120, "status": "ok"}},
            }
        )
        result = predict(fixture, context)
        assert result["model_version"].endswith("+dc-fit-test")
        assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-3
    finally:
        set_fitted_params_provider(None)

    fallback = predict(fixture, context)
    assert fallback["model_version"] == "poisson-pure-v0.2"


def test_prediction_rejects_fitted_params_trained_after_cutoff() -> None:
    fixture = {"id": "f1", "league_key": "epl", "is_demo": False}
    context = {
        "recent_form": {
            "home": [],
            "away": [],
            "as_of": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:00:00+00:00",
        },
        "lineup": {"confirmed": False, "home_strength": None, "away_strength": None, "updated_at": None},
        "availability": {"updated_at": None},
        "player_impact": {},
    }
    try:
        set_fitted_params_provider(
            lambda: {
                "fitted_version": "dc-fit-future",
                "training_cutoff": "2026-09-02T00:00:00+00:00",
                "leagues": {
                    "epl": {
                        "home_xg": 1.9,
                        "away_xg": 0.8,
                        "rho": -0.08,
                        "n": 120,
                        "status": "ok",
                    }
                },
            }
        )

        result = predict(fixture, context)

        assert result["model_version"] == "poisson-pure-v0.2"
    finally:
        set_fitted_params_provider(None)


def _seed_two_model_settlements(
    repository: PredictionRepository,
    count: int = 180,
    *,
    data_source: str | None = None,
) -> None:
    rng = random.Random(5)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(count):
        actual = rng.choice(["home", "draw", "away"])
        created = start + timedelta(hours=index * 6)
        for model_key, sharp in (("deepseek", True), ("chatgpt", False)):
            probs = (
                {key: 0.6 if key == actual else 0.2 for key in ("home", "draw", "away")}
                if sharp
                else {"home": 0.34, "draw": 0.33, "away": 0.33}
            )
            payload = {
                "id": f"mq-{model_key}-{index}",
                "prediction_id": f"mq-pred-{model_key}-{index}",
                "fixture_id": f"mq-fixture-{index}",
                "fixture_date": created.date().isoformat(),
                "league_key": "epl",
                "season": "2026",
                "model_version": f"{model_key}:v1",
                "model_key": model_key,
                "settled_at": (created + timedelta(hours=30)).isoformat(),
                "prediction_created_at": created.isoformat(),
                "actual_outcome": actual,
                "model_probabilities": probs,
                "baseline": {
                    "probabilities": {"home": 0.40, "draw": 0.30, "away": 0.30}
                },
            }
            if data_source:
                payload["data_source"] = data_source
            repository.save_fixture_settlement(payload)


def _quality_runner(repository: PredictionRepository) -> AutomationRunner:
    return AutomationRunner(
        get_settings(),
        repository,
        schedule_sync=None,
        league_sync=None,
        evidence_provider=None,
        prediction_service=None,
        bankroll_service=None,
        settlement_service=None,
        historical_data_service=None,
        model_registry_service=ModelRegistry(repository),
    )


def test_backfill_targets_pick_least_stocked_season(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "mq.db"))
    repository.initialize()

    class FakeHistoricalService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, int]] = []
            self.registry = type("R", (), {"get": staticmethod(lambda name: type("D", (), {"configured": True})())})()

        def season_existing(self, code: str, season: int) -> int:
            if season == 2026:
                return {"csl": 100, "epl": 20, "laliga": 90}.get(code, 0)
            return 0

        async def sync_league_history(self, provider: str, code: str, season: int, *, limit: int) -> dict:
            self.calls.append((code, season, limit))
            return {"status": "completed", "fixtures": {"records_inserted": 1}, "coverage": {}, "historical_snapshots": 0}

    service = FakeHistoricalService()
    automation = _quality_runner(repository)
    automation.historical_data_service = service

    targets = automation._historical_season_targets()
    assert all(existing < 100 for _, _, existing in targets)
    assert ("csl", 2026) not in [(code, season) for code, season, _ in targets]

    result = asyncio.run(automation._backfill_historical_season())

    # 最缺的组合优先（多个 0 时取排序第一个）。
    assert result["status"] == "completed"
    assert service.calls and service.calls[0][2] == 100


def test_backfill_reports_complete_when_all_seasons_capped(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "mq-full.db"))
    repository.initialize()

    class FullService:
        registry = type("R", (), {"get": staticmethod(lambda name: type("D", (), {"configured": True})())})()

        def season_existing(self, code: str, season: int) -> int:
            return 100

        def sync_league_history(self, *args, **kwargs) -> dict:
            raise AssertionError("不应触发同步")

    automation = _quality_runner(repository)
    automation.historical_data_service = FullService()

    result = asyncio.run(automation._backfill_historical_season())

    assert result["status"] == "complete"


def test_ensemble_learning_promotes_with_adequate_sample(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "mq-ens.db"), "dual-model-v1")
    repository.initialize()
    _seed_two_model_settlements(repository, count=180)
    automation = _quality_runner(repository)

    result = asyncio.run(automation._learn_ensemble_weights())

    assert result["status"] == "promoted"
    assert result["test_samples"] >= 30
    assert result["weights"]["deepseek"] > result["weights"]["chatgpt"]
    champion = ModelRegistry(repository).champion("ensemble")
    assert champion is not None and champion.status == "champion"
    assert champion.payload["weights"] == result["weights"]


def test_ensemble_learning_without_models_reports_insufficient(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "mq-empty.db"))
    repository.initialize()
    automation = _quality_runner(repository)

    result = asyncio.run(automation._learn_ensemble_weights())

    assert result["status"] == "insufficient_sample"


def test_exploratory_research_job_archives_20_pairs_with_distinct_identity(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "mq-exploratory.db"), "dual-model-v1")
    repository.initialize()
    _seed_two_model_settlements(repository, count=20)
    automation = _quality_runner(repository)

    result = asyncio.run(automation._run_exploratory_research())

    assert "exploratory_research" in automation._jobs
    assert "fd_confirmatory_research" in automation._jobs
    assert result["status"] == "completed"
    assert result["required_samples"] == 20
    stored = repository.research_runs()
    assert len(stored) == 1
    assert stored[0]["job_id"] == "production-exploratory-llm-vs-poisson"
    assert stored[0]["hypothesis"]["kind"] == "exploratory"


def test_confirmatory_research_job_keeps_30_pair_fd_gate(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "mq-confirmatory.db"), "dual-model-v1")
    repository.initialize()
    _seed_two_model_settlements(repository, count=30, data_source="football-data")
    automation = _quality_runner(repository)

    result = asyncio.run(automation._run_fd_confirmatory_research())

    assert result["status"] == "completed"
    assert result["required_samples"] == 30
    stored = repository.research_runs()
    assert len(stored) == 1
    assert stored[0]["job_id"] == "fd-confirmatory-llm-vs-poisson"
    assert stored[0]["hypothesis"]["kind"] == "confirmatory"
