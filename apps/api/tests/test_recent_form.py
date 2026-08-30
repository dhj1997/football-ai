import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.database import PredictionRepository
from app.historical_validation import HistoricalBackfillService
from app.prediction_intelligence import build_feature_snapshot
from app.recent_form import RecentFormService
from app.prediction_service import PredictionService


TEAM = {"canonical_team_id": "team:epl:home", "provider_id": 10, "name": "Home FC"}
OPPONENT = {"canonical_team_id": "team:epl:away", "provider_id": 20, "name": "Away FC"}


class FakeRepository:
    def __init__(self, fixtures: list[dict]) -> None:
        self.fixtures = fixtures

    def list_fixtures(self, league_key: str | None = None) -> list[dict]:
        if league_key is None:
            return list(self.fixtures)
        return [item for item in self.fixtures if item.get("league_key") == league_key]


def _fixture(index: int, *, kickoff: datetime, status: str = "finished", league: str = "epl") -> dict:
    return {
        "id": f"fixture-{index}",
        "canonical_fixture_id": f"canonical-{index}",
        "league_key": league,
        "fixture_date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "status": status,
        "home_team": TEAM,
        "away_team": OPPONENT,
        "score": {"home": index % 3, "away": 0},
    }


def test_recent_form_keeps_fifteen_finished_matches_and_excludes_future_statuses() -> None:
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    fixtures = [_fixture(index, kickoff=cutoff - timedelta(days=index)) for index in range(1, 19)]
    fixtures.extend(
        [
            _fixture(100, kickoff=cutoff + timedelta(days=1)),
            _fixture(101, kickoff=cutoff - timedelta(days=1), status="live"),
            _fixture(102, kickoff=cutoff - timedelta(days=2), status="postponed"),
            _fixture(103, kickoff=cutoff - timedelta(days=3), status="cancelled"),
            _fixture(104, kickoff=cutoff - timedelta(days=4), status="finished"),
        ]
    )
    fixtures[-1]["score"] = None
    service = RecentFormService(FakeRepository(fixtures))

    result = service.team_form("team:epl:home", as_of=cutoff, league="EPL")

    assert result["matches_used"] == 15
    assert result["sample_status"] == "ok"
    assert all(item["completed_at"] <= cutoff.isoformat() for item in result["matches"])
    assert all(item["result"] in {"W", "D", "L"} for item in result["matches"])
    assert result["matches"] == sorted(
        result["matches"],
        key=lambda item: (item["date"], item["fixture_id"]),
        reverse=True,
    )


def test_recent_form_reports_insufficient_and_home_away_splits() -> None:
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    fixtures = [_fixture(index, kickoff=cutoff - timedelta(days=index)) for index in range(1, 9)]
    for index, item in enumerate(fixtures[:3]):
        item["home_team"], item["away_team"] = OPPONENT, TEAM
        item["score"] = {"home": 0, "away": 2}
    service = RecentFormService(FakeRepository(fixtures))

    result = service.team_form("team:epl:home", as_of=cutoff, league="EPL")

    assert result["sample_count"] == 8
    assert result["sample_status"] == "insufficient"
    assert result["form"]["points"] == 22
    assert result["home_form"]["sample_count"] == 5
    assert result["away_form"]["sample_count"] == 3
    assert result["home_form"]["sample_status"] == "insufficient"


def test_recent_form_isolated_by_league_and_as_of_snapshot_feeds_p3() -> None:
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    fixtures = [_fixture(index, kickoff=cutoff - timedelta(days=index)) for index in range(1, 4)]
    fixtures.append(_fixture(50, kickoff=cutoff - timedelta(days=1), league="csl"))
    repository = FakeRepository(fixtures)
    service = RecentFormService(repository)
    fixture = {
        "id": "upcoming",
        "league_key": "epl",
        "kickoff": (cutoff + timedelta(days=1)).isoformat(),
        "home_team": TEAM,
        "away_team": OPPONENT,
    }

    context = service.context_for_fixture(fixture, as_of=cutoff)
    snapshot = build_feature_snapshot(fixture, {"recent_form": context or {}}, cutoff)

    assert context is not None
    assert context["snapshot"]["home"]["as_of"] == cutoff.isoformat()
    assert len(context["home"]) == 3
    assert snapshot["recent_form"]["home"]["sample_size"] == 3
    assert snapshot["recent_form"]["home"]["status"] == "complete"
    assert snapshot["leakage_check"]["passed"] is True


@pytest.mark.asyncio
async def test_prediction_context_uses_prediction_timestamp_for_recent_form() -> None:
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    repository = FakeRepository(
        [_fixture(index, kickoff=cutoff - timedelta(days=index)) for index in range(1, 17)]
    )
    fixture = {
        "id": "upcoming",
        "league_key": "epl",
        "kickoff": (cutoff + timedelta(days=1)).isoformat(),
        "home_team": TEAM,
        "away_team": OPPONENT,
    }
    context: dict = {}

    await PredictionService(object(), repository).prepare_context(
        fixture,
        context,
        prediction_timestamp=cutoff,
    )

    assert context["recent_form"]["as_of"] == cutoff.isoformat()
    assert len(context["recent_form"]["home"]) == 15


def test_p6_backfill_snapshot_uses_the_same_as_of_recent_form(tmp_path) -> None:
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    repository = PredictionRepository(str(tmp_path / "p7-backfill.db"))
    repository.initialize()
    for index in range(1, 4):
        repository.upsert_fixture(
            _fixture(index, kickoff=cutoff - timedelta(days=index))
        )
    target = _fixture(99, kickoff=cutoff + timedelta(days=1), status="scheduled")
    target["score"] = None
    repository.upsert_fixture(target)

    result = asyncio.run(
        HistoricalBackfillService(
            repository,
            recent_form_service=RecentFormService(repository),
        ).backfill("fixture-99", cutoff)
    )

    assert result["status"] == "excluded"
    recent = result["snapshot"]["payload"]["context"]["recent_form"]
    assert recent["as_of"] == cutoff.isoformat()
    assert len(recent["home"]) == 3
