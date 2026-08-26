from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.automation import AutomationRunner
from app.database import PredictionRepository


class SyncService:
    def __init__(self, item_count: int, error: Exception | None = None) -> None:
        self.item_count = item_count
        self.error = error
        self.calls = 0

    async def force_refresh(self) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        return {"status": "updated", "item_count": self.item_count}


class EvidenceProvider:
    configured = False


class FallbackEvidenceProvider:
    configured = True

    async def fetch(self, fixture: dict) -> dict:
        raise RuntimeError("rate limited")

    async def fetch_public(self, fixture: dict) -> dict:
        return {
            "synced_at": datetime.now(UTC).isoformat(),
            "source": "thesportsdb-partial",
            "lineup": {"confirmed": False},
        }


class PredictionService:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, fixture: dict, context: dict) -> dict:
        self.calls += 1
        return {"id": "prediction-1"}


class BankrollService:
    def __init__(self) -> None:
        self.calls = 0

    def place_for_prediction(self, prediction: dict, fixture: dict, context: dict) -> None:
        self.calls += 1
        return None


class SettlementService:
    def settle_finished(self) -> dict:
        return {"fixture_count": 0, "prediction_count": 0}


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        automation_tick_seconds=60,
        automation_fixture_interval_minutes=60,
        automation_standings_interval_minutes=360,
        automation_analysis_interval_minutes=5,
        automation_settlement_interval_minutes=15,
        automation_failure_backoff_minutes=15,
        prediction_lead_hours=36,
        evidence_refresh_minutes=180,
        lineup_refresh_hours=2,
        model_retry_minutes=180,
        automation_evidence_refresh_limit=1,
    )


def runner(repository, schedule=None, prediction=None, bankroll=None) -> AutomationRunner:
    return AutomationRunner(
        settings(),
        repository,
        schedule or SyncService(2),
        SyncService(3),
        EvidenceProvider(),
        prediction or PredictionService(),
        bankroll or BankrollService(),
        SettlementService(),
    )


@pytest.mark.asyncio
async def test_due_jobs_persist_and_do_not_repeat_immediately(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    automation = runner(repository)

    first = await automation.run_due()
    second = await automation.run_due()

    assert [item["job_name"] for item in first] == ["fixtures", "standings", "analysis", "settlement"]
    assert all(item["status"] == "success" for item in first)
    assert second == []
    assert len(repository.job_runs()) == 4


@pytest.mark.asyncio
async def test_failed_job_uses_persisted_backoff(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    schedule = SyncService(0, RuntimeError("upstream unavailable"))
    automation = runner(repository, schedule=schedule)

    first = await automation.run_due()
    second = await automation.run_due()

    fixture_run = next(item for item in first if item["job_name"] == "fixtures")
    assert fixture_run["status"] == "failed"
    assert fixture_run["error_summary"] == "upstream unavailable"
    assert second == []
    assert schedule.calls == 1


@pytest.mark.asyncio
async def test_analysis_only_predicts_eligible_synced_fixture(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    kickoff = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    fixture = {
        "id": "fixture-1",
        "provider_id": 1,
        "fixture_date": kickoff[:10],
        "kickoff": kickoff,
        "status": "scheduled",
        "league_key": "epl",
        "home_team": {"name": "Home"},
        "away_team": {"name": "Away"},
        "external_ids": {},
        "evidence_synced_at": datetime.now(UTC).isoformat(),
        "evidence": {
            "synced_at": datetime.now(UTC).isoformat(),
            "lineup": {"confirmed": False},
        },
    }
    repository.replace_fixtures(fixture["fixture_date"], fixture["fixture_date"], [fixture], datetime.now(UTC).isoformat())
    prediction = PredictionService()
    bankroll = BankrollService()
    automation = runner(repository, prediction=prediction, bankroll=bankroll)

    result = await automation.run_job("analysis")

    assert result["status"] == "success"
    assert result["result"]["candidate_count"] == 1
    assert result["result"]["prediction_count"] == 1
    assert prediction.calls == 1
    assert bankroll.calls == 1


@pytest.mark.asyncio
async def test_analysis_falls_back_to_partial_public_evidence(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    kickoff = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    fixture = {
        "id": "fixture-fallback",
        "provider_id": 2,
        "fixture_date": kickoff[:10],
        "kickoff": kickoff,
        "status": "scheduled",
        "league_key": "epl",
        "home_team": {"name": "Home"},
        "away_team": {"name": "Away"},
        "external_ids": {"api_football": 2},
    }
    repository.replace_fixtures(fixture["fixture_date"], fixture["fixture_date"], [fixture], datetime.now(UTC).isoformat())
    prediction = PredictionService()
    bankroll = BankrollService()
    automation = AutomationRunner(
        settings(), repository, SyncService(1), SyncService(3), FallbackEvidenceProvider(),
        prediction, bankroll, SettlementService(),
    )

    result = await automation.run_job("analysis")

    assert result["status"] == "partial"
    assert result["result"]["public_evidence_count"] == 1
    assert result["result"]["prediction_count"] == 1
    assert repository.fixture("fixture-fallback")["evidence"]["source"] == "thesportsdb-partial"


def test_legacy_prediction_without_ai_metadata_is_upgraded(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    automation = runner(repository)

    assert automation._should_predict(
        {"created_at": datetime.now(UTC).isoformat(), "phase": "preliminary"},
        {"lineup": {"confirmed": False}},
        datetime.now(UTC),
    ) is True
