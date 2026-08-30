import asyncio
from datetime import UTC, datetime, timedelta

from app.database import PredictionRepository
from app.historical_backfill import HistoricalEvaluationRepository, HistoricalPredictionBackfillService
from app.historical_multimodel import HistoricalMultiModelBackfillService, P7_3_VERSION
from app.model_evaluation import ModelEvaluationService


def _fixture(index: int, kickoff: datetime, *, status: str = "finished") -> dict:
    return {
        "id": f"multi-history-{index}",
        "provider_id": 2000 + index,
        "canonical_fixture_id": f"canonical-multi-{index}",
        "canonical_league": "EPL",
        "league_key": "epl",
        "season": "2025",
        "fixture_date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "status": status,
        "home_team": {"canonical_team_id": "team:home", "provider_id": 10, "name": "主队"},
        "away_team": {"canonical_team_id": "team:away", "provider_id": 20, "name": "客队"},
        "score": {"home": 1, "away": 0} if status == "finished" else None,
        "is_demo": False,
    }


def _seed(repository: PredictionRepository) -> None:
    start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    for index in range(4):
        repository.upsert_fixture(_fixture(index, start + timedelta(days=index * 2)))


class _FakeProvider:
    def __init__(self, provider_name: str, *, fail: bool = False) -> None:
        self.provider_name = provider_name
        self.model = f"{provider_name}-historical-test"
        self.configured = not fail
        self.fail = fail

    async def assess(self, _model_input: dict) -> dict:
        if self.fail:
            raise RuntimeError("provider test failure")
        return {
            "assessment": {
                "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2},
                "predicted_outcome": "home",
                "forecast_confidence": 0.7,
                "asian_handicap_forecast": {
                    "available": False,
                    "line": None,
                    "home_cover_probability": None,
                    "away_cover_probability": None,
                    "confidence": 0.0,
                    "reason": "没有历史盘口",
                },
                "player_analysis": {
                    "key_available_players": [],
                    "key_absent_players": [],
                    "replacement_gap": "历史阵容证据缺失",
                    "attack_impact": "无法从历史证据确认",
                    "defense_impact": "无法从历史证据确认",
                },
                "bet_recommendation": {
                    "status": "no_bet",
                    "market": "no_bet",
                    "selection": "none",
                    "reason": "历史回填不进入下注链",
                },
                "analysis_summary": "仅使用冻结历史证据生成预测",
                "risk_factors": ["历史样本有限"],
                "missing_evidence": ["历史赔率不可用"],
            },
            "provider": self.provider_name,
            "requested_model": self.model,
            "returned_model": self.model,
            "prompt_version": "football-forecast-v5",
            "evidence_version": "fixture-evidence-v3",
            "usage": None,
            "request_id": "test-request",
        }


def test_multimodel_backfill_reuses_p72_snapshots_and_enters_p6(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "historical-multimodel.db"))
    repository.initialize()
    _seed(repository)
    asyncio.run(HistoricalPredictionBackfillService(repository).run())

    service = HistoricalMultiModelBackfillService(
        repository,
        {"chatgpt": _FakeProvider("chatgpt"), "deepseek": _FakeProvider("deepseek")},
    )
    first = asyncio.run(service.run())
    second = asyncio.run(service.run())

    assert first["eligible_fixtures"] == 3
    assert first["generated_by_model"]["poisson"] == 3
    assert first["generated_by_model"]["chatgpt"] == 3
    assert first["generated_by_model"]["deepseek"] == 3
    assert first["ensemble_ready_fixtures"] == 3
    assert second["generated_by_model"]["chatgpt"] == 0
    assert second["reused_by_model"]["chatgpt"] == 3
    assert second["reused_by_model"]["deepseek"] == 3
    rows = repository.historical_predictions(limit=100)
    assert len(rows) == 9
    assert {row["model_key"] for row in rows} == {"poisson", "chatgpt", "deepseek"}
    assert all(row["historical_backfill"]["version"] == P7_3_VERSION for row in rows if row["model_key"] != "poisson")
    for fixture_id in {row["fixture_id"] for row in rows}:
        fixture_rows = [row for row in rows if row["fixture_id"] == fixture_id]
        assert len({row["prediction_timestamp"] for row in fixture_rows}) == 1
        assert len({row["feature_snapshot_id"] for row in fixture_rows}) == 1
        assert len({row["evidence_snapshot_id"] for row in fixture_rows}) == 1
    assert repository.predictions_for_fixture("multi-history-1") == []
    assert repository.fixture_settlements() == []
    assert repository.bets() == []
    assert repository.bet_executions() == []

    evaluation_rows = HistoricalPredictionBackfillService(repository).evaluation_rows()
    evaluation = ModelEvaluationService(HistoricalEvaluationRepository(repository)).evaluate(evaluation_rows)
    models = evaluation["reports"]["GLOBAL"]["models"]
    assert models["gpt"]["sample_count"] > 0
    assert models["deepseek"]["sample_count"] > 0
    assert models["ensemble"]["sample_count"] > 0
    assert evaluation["leakage_audit"]["violations"] == 0


def test_multimodel_provider_failure_is_recorded_without_fallback_prediction(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "historical-multimodel-failure.db"))
    repository.initialize()
    _seed(repository)
    asyncio.run(HistoricalPredictionBackfillService(repository).run())

    result = asyncio.run(
        HistoricalMultiModelBackfillService(
            repository,
            {"deepseek": _FakeProvider("deepseek", fail=True)},
        ).run()
    )

    assert result["failed_by_model"]["deepseek"] == 3
    assert result["errors"]
    assert not [row for row in repository.historical_predictions(limit=100) if row["model_key"] == "deepseek"]
