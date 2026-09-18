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


def test_rolling_features_do_not_use_future_matches() -> None:
    cutoff = datetime(2026, 9, 15, 12, tzinfo=UTC)
    fixtures = [
        _fixture(index, kickoff=cutoff - timedelta(days=index))
        for index in range(1, 13)
    ]
    unavailable_result = _fixture(
        99,
        kickoff=cutoff - timedelta(minutes=30),
    )
    unavailable_result["completed_at"] = (cutoff + timedelta(hours=1)).isoformat()
    unavailable_result["score"] = {"home": 99, "away": 0}
    fixtures.append(unavailable_result)

    result = RecentFormService(FakeRepository(fixtures)).team_form(
        "team:epl:home",
        as_of=cutoff,
        league="EPL",
    )

    assert result["season_matches_used"] == 12
    assert "canonical-99" not in result["season_source_record_ids"]
    assert all(item["available_at"] <= cutoff.isoformat() for item in result["matches"])
    for window in (3, 5, 8, 10):
        assert result["rolling"][f"last_{window}"]["sample_count"] == window
    assert result["season_average"]["sample_count"] == 12
    assert result["season_average"]["goals_for"] < 99


def test_season_average_excludes_prior_seasons_when_season_is_inferred() -> None:
    cutoff = datetime(2026, 9, 15, 12, tzinfo=UTC)
    current_season = [
        _fixture(index, kickoff=cutoff - timedelta(days=index))
        for index in range(1, 4)
    ]
    prior_season = _fixture(90, kickoff=datetime(2026, 5, 1, 12, tzinfo=UTC))
    prior_season["score"] = {"home": 90, "away": 0}
    target = {
        "id": "upcoming-season-boundary",
        "league_key": "epl",
        "kickoff": (cutoff + timedelta(days=1)).isoformat(),
        "home_team": TEAM,
        "away_team": OPPONENT,
    }

    context = RecentFormService(
        FakeRepository([*current_season, prior_season])
    ).context_for_fixture(target, as_of=cutoff)

    assert context is not None
    assert context["snapshot"]["home"]["season_matches_used"] == 3
    assert "canonical-90" not in context["snapshot"]["home"]["season_source_record_ids"]


def test_date_only_result_is_available_from_next_day() -> None:
    cutoff = datetime(2026, 9, 15, 18, tzinfo=UTC)
    fixture = _fixture(91, kickoff=cutoff.replace(hour=12))
    fixture["kickoff_date_only"] = True

    before_next_day = RecentFormService(FakeRepository([fixture])).team_form(
        "team:epl:home",
        as_of=cutoff,
        league="EPL",
    )
    next_day = RecentFormService(FakeRepository([fixture])).team_form(
        "team:epl:home",
        as_of=cutoff + timedelta(days=1),
        league="EPL",
    )

    assert before_next_day["matches"] == []
    assert next_day["matches"][0]["availability_basis"] == (
        "inferred_next_day_from_date_only_kickoff"
    )


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


def test_context_for_fixture_returns_none_when_one_side_has_no_matches() -> None:
    """A one-sided snapshot would carry None ppg and crash the Poisson baseline."""

    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    other = {"canonical_team_id": "team:epl:other", "provider_id": 30, "name": "Other FC"}
    fixtures = [_fixture(index, kickoff=cutoff - timedelta(days=index)) for index in range(1, 4)]
    for item in fixtures:
        item["home_team"], item["away_team"] = TEAM, other
        item["score"] = {"home": 2, "away": 0}
    service = RecentFormService(FakeRepository(fixtures))
    fixture = {
        "id": "upcoming",
        "league_key": "epl",
        "kickoff": (cutoff + timedelta(days=1)).isoformat(),
        "home_team": TEAM,
        "away_team": OPPONENT,
    }

    context = service.context_for_fixture(fixture, as_of=cutoff)

    assert context is None
