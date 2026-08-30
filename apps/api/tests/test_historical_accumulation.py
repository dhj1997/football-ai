import asyncio
from datetime import UTC, datetime, timedelta

from app.database import PredictionRepository
from app.historical_accumulation import HistoricalOOSAccumulationService, P7_4_VERSION


def _fixture(index: int, kickoff: datetime, *, league: str = "EPL", status: str = "finished") -> dict:
    return {
        "id": f"accumulation-{index}",
        "provider_id": 6000 + index,
        "canonical_fixture_id": f"canonical-accumulation-{index}",
        "canonical_league": league,
        "league_key": league.casefold(),
        "season": "2025",
        "fixture_date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "status": status,
        "home_team": {"canonical_team_id": "team:home", "provider_id": 10, "name": "主队"},
        "away_team": {"canonical_team_id": "team:away", "provider_id": 20, "name": "客队"},
        "score": {"home": 1, "away": 0} if status == "finished" else None,
        "is_demo": False,
    }


class _Provider:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.provider_name = name
        self.model = f"{name}-historical-test"
        self.configured = True
        self.fail = fail
        self.calls = 0

    async def assess(self, _model_input: dict) -> dict:
        self.calls += 1
        if self.fail:
            raise RuntimeError("402 Payment Required")
        return {
            "assessment": {
                "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2},
                "predicted_outcome": "home",
                "forecast_confidence": 0.7,
                "asian_handicap_forecast": {"available": False, "line": None, "home_cover_probability": None, "away_cover_probability": None, "confidence": 0.0, "reason": "历史盘口不可用"},
                "player_analysis": {"key_available_players": [], "key_absent_players": [], "replacement_gap": "历史阵容证据缺失", "attack_impact": "不可用", "defense_impact": "不可用"},
                "bet_recommendation": {"status": "no_bet", "market": "no_bet", "selection": "none", "reason": "历史回填不进入下注链"},
                "analysis_summary": "冻结历史证据",
                "risk_factors": [],
                "missing_evidence": ["历史赔率不可用"],
            },
            "provider": self.provider_name,
            "requested_model": self.model,
            "returned_model": self.model,
            "prompt_version": "football-forecast-v5",
            "evidence_version": "fixture-evidence-v3",
            "usage": None,
            "request_id": "accumulation-test",
        }


def _repository(tmp_path, count: int = 4) -> PredictionRepository:
    repository = PredictionRepository(str(tmp_path / "accumulation.db"))
    repository.initialize()
    start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    for index in range(count):
        repository.upsert_fixture(_fixture(index, start + timedelta(days=index * 2)))
    return repository


def test_accumulation_is_idempotent_and_never_writes_production(tmp_path) -> None:
    repository = _repository(tmp_path)
    chatgpt = _Provider("chatgpt")
    deepseek = _Provider("deepseek")
    service = HistoricalOOSAccumulationService(repository, {"chatgpt": chatgpt, "deepseek": deepseek})

    first = asyncio.run(service.run())
    first_calls = (chatgpt.calls, deepseek.calls)
    second = asyncio.run(service.run())

    assert first["eligible_fixtures"] == 3
    assert first["newly_generated_predictions"] == 9
    assert first["generated_by_model"] == {"poisson": 3, "chatgpt": 3, "deepseek": 3}
    assert second["newly_generated_predictions"] == 0
    assert second["already_existing_predictions"] == 9
    assert (chatgpt.calls, deepseek.calls) == first_calls
    assert repository.predictions_for_fixture("accumulation-1") == []
    assert repository.bets() == []
    assert repository.bet_executions() == []
    assert repository.fixture_settlements() == []
    assert repository.historical_backfill_runs(limit=2)[0]["version"] == P7_4_VERSION
    evaluation = service.run_p6_evaluation()
    assert evaluation["leakage_audit"]["violations"] == 0
    assert evaluation["reports"]["GLOBAL"]["sample_count"] == 1


def test_accumulation_retries_missing_deepseek_without_poisson_fallback(tmp_path) -> None:
    repository = _repository(tmp_path)
    deepseek = _Provider("deepseek", fail=True)
    result = asyncio.run(
        HistoricalOOSAccumulationService(repository, {"deepseek": deepseek}).run()
    )

    assert result["model_failures"] == 3
    assert result["model_failures_by_model"]["deepseek"] == 3
    assert result["generated_by_model"]["deepseek"] == 0
    assert deepseek.calls == 3
    assert not [row for row in repository.historical_predictions(limit=100) if row["model_key"] == "deepseek"]
    assert len([row for row in repository.historical_predictions(limit=100) if row["model_key"] == "poisson"]) == 3


def test_accumulation_enforces_whitelist_caps_and_as_of_form(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "caps.db"))
    repository.initialize()
    start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    for index in range(3):
        repository.upsert_fixture(_fixture(index, start + timedelta(days=index * 2), league="EPL"))
    repository.upsert_fixture(_fixture(10, start + timedelta(days=10), league="Bundesliga"))
    repository.upsert_fixture(_fixture(11, start + timedelta(days=12), status="scheduled"))
    # A two-fixture league cap is applied before historical backfill.
    service = HistoricalOOSAccumulationService(repository, {}, max_per_league=2)
    result = asyncio.run(service.run())

    assert result["canonical_fixtures_selected"] == 2
    assert result["eligible_fixtures"] == 1
    assert result["excluded_by_reason"]["unsupported_league"] == 1
    assert result["excluded_by_reason"]["league_fixture_cap"] == 2
    rows = repository.historical_predictions(limit=20)
    assert rows and all(row["prediction_timestamp"] < row["actual_completed_at"] for row in rows)
    evidence = repository.evidence_snapshot(rows[0]["evidence_snapshot_id"])
    recent = (evidence["payload"]["context"]["recent_form"] if evidence else {})
    assert all(len(recent.get(side) or []) <= 15 for side in ("home", "away"))
