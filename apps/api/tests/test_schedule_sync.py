"""Focused cache freshness behavior for schedule acquisition."""

from datetime import UTC, datetime, timedelta

import pytest

from app.schedule_sync import ScheduleSyncService, deduplicate_fixtures


class FakeRepository:
    def __init__(self, metadata=None) -> None:
        self.metadata = metadata
        self.replacements = []
        self.rows = []

    def fixture_sync(self):
        return self.metadata

    def list_fixtures(self, start_date=None, end_date=None):
        return list(self.rows)

    def replace_fixtures(self, start_date, end_date, rows, synced_at) -> None:
        self.replacements.append((start_date, end_date, rows))
        self.metadata = {"synced_at": synced_at, "item_count": len(rows)}


class FakeProvider:
    LEAGUE_IDS = {"epl": 1, "laliga": 2, "csl": 3}

    def __init__(self, *, configured=True, error=False) -> None:
        self.configured = configured
        self.error = error
        self.calls = 0
        self.windows = []

    async def fixtures(self, start_date, end_date):
        self.calls += 1
        self.windows.append((start_date, end_date))
        if self.error:
            raise RuntimeError("upstream unavailable")
        return [{"id": "fixture-1"}]


def fixture_row(*, status="live", score=None, away="布莱顿"):
    return {
        "id": "sportsdb-1",
        "league_key": "epl",
        "kickoff": "2026-08-30T13:00:00+00:00",
        "status": status,
        "provider_status": "2H",
        "score": score or {"home": 3, "away": 1},
        "home_team": {"name": "切尔西"},
        "away_team": {"name": away},
    }


class FixtureProvider(FakeProvider):
    def __init__(self, rows, *, error=False) -> None:
        super().__init__(error=error)
        self.rows = rows

    async def fixtures(self, start_date, end_date):
        self.calls += 1
        if self.error:
            raise RuntimeError("upstream unavailable")
        return self.rows


@pytest.mark.asyncio
async def test_refresh_merges_configured_supplemental_provider_rows() -> None:
    repository = FakeRepository()
    primary = FixtureProvider([fixture_row(status="scheduled", score=None)])
    supplemental = FixtureProvider(
        [
            {
                **fixture_row(status="scheduled", score=None),
                "id": "api-1",
                "source": "api-football",
                "kickoff": "2026-08-30T13:05:00+00:00",
                "external_ids": {"api_football": "1"},
            }
        ]
    )
    service = ScheduleSyncService(primary, repository, 1, 60, supplemental_providers=[supplemental])

    await service.force_refresh()

    assert len(repository.replacements[0][2]) == 1
    assert repository.replacements[0][2][0]["id"] == "sportsdb-1"
    assert repository.replacements[0][2][0]["external_ids"]["api_football"] == "1"


@pytest.mark.asyncio
async def test_missing_cache_is_refreshed_once() -> None:
    repository = FakeRepository()
    provider = FakeProvider()
    service = ScheduleSyncService(provider, repository, lookback_days=1, ttl_minutes=60)

    result = await service.ensure_fresh()

    assert result["status"] == "updated"
    assert result["request_count"] == 9
    assert provider.calls == 1
    assert len(repository.replacements) == 1


@pytest.mark.asyncio
async def test_refresh_uses_configured_seven_day_lookahead() -> None:
    repository = FakeRepository()
    provider = FakeProvider()
    service = ScheduleSyncService(provider, repository, lookback_days=1, ttl_minutes=60, lookahead_days=7)

    await service.ensure_fresh()

    start_date, end_date = provider.windows[0]
    assert (end_date - start_date).days == 8


@pytest.mark.asyncio
async def test_fresh_cache_skips_provider() -> None:
    repository = FakeRepository(
        {"synced_at": datetime.now(UTC).replace(microsecond=0).isoformat(), "item_count": 4}
    )
    provider = FakeProvider()
    service = ScheduleSyncService(provider, repository, lookback_days=1, ttl_minutes=60)

    result = await service.ensure_fresh()

    assert result == {
        "status": "fresh",
        "last_synced_at": repository.metadata["synced_at"],
        "item_count": 4,
    }
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_refresh_failure_preserves_stale_cache() -> None:
    repository = FakeRepository(
        {
            "synced_at": (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat(),
            "item_count": 2,
        }
    )
    provider = FakeProvider(error=True)
    service = ScheduleSyncService(provider, repository, lookback_days=1, ttl_minutes=60)

    result = await service.ensure_fresh()

    assert result["status"] == "stale"
    assert result["item_count"] == 2
    assert provider.calls == 1
    assert repository.replacements == []


@pytest.mark.asyncio
async def test_result_provider_overlays_exact_match_only() -> None:
    repository = FakeRepository()
    primary = FixtureProvider([fixture_row()])
    result_provider = FixtureProvider(
        [
            {
                **fixture_row(status="finished", score={"home": 4, "away": 3}),
                "id": "espn-1",
                "provider_status": "FT",
                "captured_at": "2026-08-30T15:00:00+00:00",
            },
            fixture_row(status="finished", away="其他球队"),
        ]
    )
    service = ScheduleSyncService(primary, repository, 1, 60, result_provider)

    result = await service.force_refresh()
    stored = repository.replacements[0][2][0]

    assert result["result_sync_status"] == "updated"
    assert stored["id"] == "sportsdb-1"
    assert stored["status"] == "finished"
    assert stored["provider_status"] == "FT"
    assert stored["score"] == {"home": 4, "away": 3}
    assert stored["result_source"] == "espn"


@pytest.mark.asyncio
async def test_result_provider_failure_preserves_primary_rows() -> None:
    repository = FakeRepository()
    primary_row = fixture_row()
    service = ScheduleSyncService(
        FixtureProvider([primary_row]),
        repository,
        1,
        60,
        FixtureProvider([], error=True),
    )

    result = await service.force_refresh()

    assert result["result_sync_status"] == "failed"
    assert repository.replacements[0][2] == [primary_row]


@pytest.mark.asyncio
async def test_warm_cache_loads_persisted_rows_without_refreshing() -> None:
    repository = FakeRepository({"synced_at": "2026-08-30T10:00:00+00:00", "item_count": 1})
    repository.rows = [fixture_row()]
    service = ScheduleSyncService(FakeProvider(), repository, 1, 60)

    await service.warm_cache()

    assert service.cached_fixtures(None, None) == repository.rows
    assert service.cached_state()["status"] in {"fresh", "stale"}
    assert repository.replacements == []


def test_deduplicate_fixtures_merges_cross_provider_same_match() -> None:
    sportsdb = {
        **fixture_row(status="scheduled", score=None),
        "id": "sportsdb-1",
        "kickoff": "2026-08-30T13:00:00+00:00",
        "evidence": {"recent_form": {"home": ["W"], "away": ["D"]}},
        "external_ids": {"api_football": "42"},
    }
    dongqiudi = {
        **sportsdb,
        "id": "dongqiudi-9",
        "source": "dongqiudi",
        "kickoff": "2026-08-30T13:08:00+00:00",
        "external_ids": {"dongqiudi": "9"},
        "evidence": {"recent_form": {"home": ["W"], "away": ["D"]}, "odds": {"home": 2.0}},
    }

    result = deduplicate_fixtures([sportsdb, dongqiudi])

    assert len(result) == 1
    assert result[0]["id"] == "sportsdb-1"
    assert result[0]["external_ids"] == {"api_football": "42", "dongqiudi": "9"}
    assert result[0]["evidence"]["odds"] == {"home": 2.0}


def test_deduplicate_fixtures_matches_chinese_alias_and_keeps_finished_result() -> None:
    sportsdb = {
        **fixture_row(status="finished", score={"home": 0, "away": 0}, away="维戈塞尔塔"),
        "id": "sportsdb-celta",
        "external_ids": {"api_football": "1570392"},
    }
    dongqiudi = {
        **sportsdb,
        "id": "dongqiudi-celta",
        "source": "dongqiudi",
        "status": "scheduled",
        "provider_status": "Fixture",
        "score": None,
        "external_ids": {"dongqiudi": "54493255"},
        "away_team": {"name": "塞尔塔"},
        "evidence": {"dongqiudi_analysis": {"match_id": "54493255"}},
    }

    result = deduplicate_fixtures([sportsdb, dongqiudi])

    assert len(result) == 1
    assert result[0]["id"] == "sportsdb-celta"
    assert result[0]["status"] == "finished"
    assert result[0]["score"] == {"home": 0, "away": 0}
    assert result[0]["away_team"]["name"] == "维戈塞尔塔"
    assert result[0]["external_ids"]["dongqiudi"] == "54493255"
    assert result[0]["evidence"]["dongqiudi_analysis"]["match_id"] == "54493255"


def test_deduplicate_fixtures_matches_current_ucl_english_aliases() -> None:
    sportsdb = {
        **fixture_row(status="scheduled", score=None, away="Viking"),
        "id": "sportsdb-stuttgart",
        "kickoff": "2026-09-09T16:45:00+00:00",
        "home_team": {"name": "Stuttgart", "provider_id": 1},
        "away_team": {"name": "Viking", "provider_id": 2},
    }
    dongqiudi = {
        **sportsdb,
        "id": "dongqiudi-stuttgart",
        "source": "dongqiudi",
        "home_team": {"name": "斯图加特", "provider_id": 3},
        "away_team": {"name": "维京", "provider_id": 4},
        "external_ids": {"dongqiudi": "54577422"},
        "evidence": {"dongqiudi_analysis": {"match_id": "54577422"}},
    }

    result = deduplicate_fixtures([sportsdb, dongqiudi])

    assert len(result) == 1
    assert result[0]["id"] == "sportsdb-stuttgart"
    assert result[0]["home_team"]["name"] == "斯图加特"
    assert result[0]["away_team"]["name"] == "维京"
    assert result[0]["external_ids"]["dongqiudi"] == "54577422"


def test_deduplicate_fixtures_keeps_reversed_or_late_matches() -> None:
    original = {**fixture_row(status="scheduled", score=None), "id": "fixture-1", "external_ids": {}}
    reversed_fixture = {
        **original,
        "id": "fixture-2",
        "home_team": original["away_team"],
        "away_team": original["home_team"],
    }
    late_fixture = {**original, "id": "fixture-3", "kickoff": "2026-08-30T13:16:00+00:00"}

    result = deduplicate_fixtures([original, reversed_fixture, late_fixture])

    assert [item["id"] for item in result] == ["fixture-1", "fixture-2", "fixture-3"]
