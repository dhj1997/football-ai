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

    async def fetch_lineup(self, _fixture):
        return {"lineup": {"confirmed": False}}


class TheSportsDbEvidenceProvider:
    configured = True
    fetch_calls = 0
    public_calls = 0

    async def fetch(self, fixture: dict) -> dict:
        self.fetch_calls += 1
        raise RuntimeError("rate limited")

    async def fetch_public(self, fixture: dict) -> dict:
        self.public_calls += 1
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
        automation_analysis_enabled=True,
        automation_fixture_interval_minutes=60,
        automation_standings_interval_minutes=360,
        automation_analysis_interval_minutes=5,
        automation_evidence_interval_minutes=1440,
        automation_lineup_interval_minutes=5,
        lineup_refresh_offsets_minutes="60,30",
        prediction_refresh_offsets_hours="24,12,6,1,0.5",
        automation_settlement_interval_minutes=15,
        automation_failure_backoff_minutes=15,
        prediction_lead_hours=36,
        evidence_refresh_minutes=180,
        lineup_refresh_hours=2,
        model_retry_minutes=180,
        automation_evidence_refresh_limit=1,
        schedule_lookahead_days=7,
        automation_dongqiudi_score_interval_minutes=5,
    )


def runner(repository, schedule=None, prediction=None, bankroll=None, dongqiudi=None) -> AutomationRunner:
    return AutomationRunner(
        settings(),
        repository,
        schedule or SyncService(2),
        SyncService(3),
        EvidenceProvider(),
        prediction or PredictionService(),
        bankroll or BankrollService(),
        SettlementService(),
        dongqiudi_sync_service=dongqiudi,
    )


@pytest.mark.asyncio
async def test_due_jobs_persist_and_do_not_repeat_immediately(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    automation = runner(repository)

    first = await automation.run_due()
    second = await automation.run_due()

    assert [item["job_name"] for item in first] == ["fixtures", "evidence", "lineup", "standings", "analysis", "settlement"]
    assert all(item["status"] == "success" for item in first)
    assert second == []
    assert len(repository.job_runs()) == 6


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
async def test_dongqiudi_score_job_runs_with_configured_interval(tmp_path) -> None:
    class DongqiudiSync:
        async def sync_schedule(self):
            return {"item_count": 0}

        async def sync_scores(self):
            return {"item_count": 1}

        async def sync_prematch_due(self):
            return {"item_count": 0}

    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    automation = runner(repository, dongqiudi=DongqiudiSync())

    runs = await automation.run_due()

    score_run = next(item for item in runs if item["job_name"] == "dongqiudi_scores")
    assert score_run["status"] == "success"
    assert score_run["item_count"] == 1


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
async def test_analysis_uses_only_thesportsdb_public_evidence(tmp_path) -> None:
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
    evidence = TheSportsDbEvidenceProvider()
    automation = AutomationRunner(
        settings(), repository, SyncService(1), SyncService(3), evidence,
        prediction, bankroll, SettlementService(),
    )

    result = await automation.run_job("analysis")

    assert result["status"] == "success"
    assert result["result"]["evidence_refresh_count"] == 1
    assert evidence.fetch_calls == 0
    assert evidence.public_calls == 1
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


@pytest.mark.asyncio
async def test_lineup_refresh_retries_within_throttle_until_confirmed(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "lineup-retry.db"))
    repository.initialize()
    kickoff = (datetime.now(UTC) + timedelta(minutes=40)).isoformat()
    fixture = {
        "id": "fixture-lineup",
        "provider_id": 9,
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
            "automation_refresh": {
                # 上一次尝试 11 分钟前：节流窗口已过，应当重试。
                "lineup_60_at": (datetime.now(UTC) - timedelta(minutes=11)).isoformat(),
            },
        },
    }
    repository.replace_fixtures(fixture["fixture_date"], fixture["fixture_date"], [fixture], datetime.now(UTC).isoformat())
    automation = runner(repository)

    first = await automation.run_job("lineup")
    assert first["result"]["synced_count"] == 1
    stored = repository.fixture("fixture-lineup")["evidence"]["automation_refresh"]
    assert stored["lineup_60_at"] > (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    # 节流窗口内不重复抓取。
    second = await automation.run_job("lineup")
    assert second["result"]["synced_count"] == 0


@pytest.mark.asyncio
async def test_disabled_analysis_is_not_run_by_scheduler(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    configured = settings()
    configured.automation_analysis_enabled = False
    automation = AutomationRunner(
        configured,
        repository,
        SyncService(2),
        SyncService(3),
        EvidenceProvider(),
        PredictionService(),
        BankrollService(),
        SettlementService(),
    )

    first = await automation.run_due()

    assert [item["job_name"] for item in first] == ["fixtures", "evidence", "lineup", "standings", "settlement"]
    assert repository.job_runs("analysis") == []


@pytest.mark.asyncio
async def test_daily_evidence_refresh_does_not_run_prediction_or_bet(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    kickoff = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    fixture = {
        "id": "fixture-evidence",
        "provider_id": 3,
        "fixture_date": kickoff[:10],
        "kickoff": kickoff,
        "status": "scheduled",
        "league_key": "epl",
        "home_team": {"name": "Home"},
        "away_team": {"name": "Away"},
        "external_ids": {},
        "evidence": {
            "source": "thesportsdb-partial",
            "synced_at": datetime.now(UTC).isoformat(),
            "recent_form": {"home": [{"result": "W"}] * 5, "away": [{"result": "D"}] * 5},
            "head_to_head": [],
            "availability": {"players": [], "checked_at": datetime.now(UTC).isoformat()},
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
        },
    }
    repository.replace_fixtures(fixture["fixture_date"], fixture["fixture_date"], [fixture], datetime.now(UTC).isoformat())

    class Evidence:
        configured = True
        calls = 0

        async def fetch_public(self, _fixture):
            self.calls += 1
            return {
                "source": "thesportsdb-partial",
                "synced_at": datetime.now(UTC).isoformat(),
                "recent_form": {"home": [{"result": "W"}] * 5, "away": [{"result": "D"}] * 5},
                "head_to_head": [{"score": "1 - 0"}],
                "availability": {"players": [], "checked_at": datetime.now(UTC).isoformat()},
                "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            }

    class NoPrediction:
        model_keys = []
        calls = 0

    class NoBankroll:
        calls = 0

    evidence = Evidence()
    prediction = NoPrediction()
    automation = AutomationRunner(
        settings(), repository, SyncService(1), SyncService(1), evidence,
        prediction, NoBankroll(), SettlementService(),
    )

    result = await automation.run_job("evidence")

    saved = repository.fixture("fixture-evidence")
    assert result["status"] == "success"
    assert result["result"]["refresh_count"] == 1
    assert evidence.calls == 1
    assert prediction.calls == 0
    assert saved["evidence"]["head_to_head"] == [{"score": "1 - 0"}]


@pytest.mark.asyncio
async def test_lineup_job_is_registered(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    automation = runner(repository)

    result = await automation.run_job("lineup")

    assert result["status"] == "success"
    assert result["result"]["item_count"] == 0


def test_prediction_windows_cover_requested_offsets() -> None:
    automation = runner(PredictionRepository(":memory:"))
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    assert automation._prediction_window(now + timedelta(hours=24), now) == 24.0
    assert automation._prediction_window(now + timedelta(hours=12), now) == 12.0
    assert automation._prediction_window(now + timedelta(hours=6), now) == 6.0
    assert automation._prediction_window(now + timedelta(hours=1), now) == 1.0
    assert automation._prediction_window(now + timedelta(minutes=30), now) == 0.5
    assert automation._prediction_window(now + timedelta(hours=23), now) == 24.0
    assert automation._prediction_window(now + timedelta(hours=2, minutes=45), now) == 6.0


def test_prediction_window_skips_completed_window_and_waits_for_next_threshold() -> None:
    automation = runner(PredictionRepository(":memory:"))
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    refresh_state = {"prediction_6h_default_at": now.isoformat()}

    assert automation._prediction_window(
        now + timedelta(hours=2), now, refresh_state, []
    ) is None
    assert automation._prediction_window(
        now + timedelta(minutes=45), now, refresh_state, []
    ) == 1.0


@pytest.mark.asyncio
async def test_forced_analysis_repredicts_an_already_marked_window(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "jobs.db"))
    repository.initialize()
    kickoff = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    fixture = {
        "id": "fixture-force",
        "provider_id": 3,
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
            "automation_refresh": {
                "prediction_1h_default_at": datetime.now(UTC).isoformat(),
            },
        },
    }
    repository.replace_fixtures(fixture["fixture_date"], fixture["fixture_date"], [fixture], datetime.now(UTC).isoformat())
    prediction = PredictionService()
    automation = runner(repository, prediction=prediction)

    result = await automation.run_job("analysis", force=True)

    assert result["status"] == "success"
    assert result["result"]["prediction_count"] == 1
    assert prediction.calls == 1


@pytest.mark.asyncio
async def test_analysis_repredicts_once_after_lineup_confirmation(tmp_path) -> None:
    kickoff = datetime.now(UTC) + timedelta(minutes=20)

    class Repository:
        def __init__(self) -> None:
            self.fixture_data = {
                "id": "fixture-lineup-reprediction",
                "provider_id": 4,
                "fixture_date": kickoff.date().isoformat(),
                "kickoff": kickoff.isoformat(),
                "status": "scheduled",
                "league_key": "acl",
                "home_team": {"name": "Home"},
                "away_team": {"name": "Away"},
                "evidence_synced_at": datetime.now(UTC).isoformat(),
                "evidence": {
                    "synced_at": datetime.now(UTC).isoformat(),
                    "lineup": {"confirmed": True},
                    "automation_refresh": {
                        "prediction_30m_chatgpt_at": datetime.now(UTC).isoformat(),
                    },
                },
            }
            self.latest = {
                "id": "prediction-before-lineup",
                "phase": "preliminary",
                "created_at": datetime.now(UTC).isoformat(),
                "ai": {"status": "completed"},
            }

        def list_fixtures(self):
            return [self.fixture_data]

        def latest_current(self, *_args):
            return self.latest

        def save_fixture_evidence(self, _fixture_id, context):
            self.fixture_data["evidence"] = context
            return self.fixture_data

    class Prediction:
        model_keys = ("chatgpt",)
        competition_id = "test-competition"

        def __init__(self, repository):
            self.repository = repository
            self.calls = 0

        async def create(self, _fixture, _context, model_keys=None):
            self.calls += 1
            self.repository.latest = {
                "id": "prediction-after-lineup",
                "phase": "confirmed_lineup",
                "created_at": datetime.now(UTC).isoformat(),
                "model_key": (model_keys or ["chatgpt"])[0],
                "ai": {"status": "completed"},
            }
            return [self.repository.latest]

    repository = Repository()
    prediction = Prediction(repository)
    automation = runner(repository, prediction=prediction)

    first = await automation._analyze_upcoming()
    second = await automation._analyze_upcoming()

    assert first["prediction_count"] == 1
    assert second["prediction_count"] == 0
    assert prediction.calls == 1
    assert repository.fixture_data["evidence"]["automation_refresh"]["prediction_lineup_chatgpt_at"]
