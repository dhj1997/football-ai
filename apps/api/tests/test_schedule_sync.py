"""Focused cache freshness behavior for schedule acquisition."""

from datetime import UTC, datetime, timedelta

import pytest

from app.schedule_sync import ScheduleSyncService


class FakeRepository:
    def __init__(self, metadata=None) -> None:
        self.metadata = metadata
        self.replacements = []

    def fixture_sync(self):
        return self.metadata

    def replace_fixtures(self, start_date, end_date, rows, synced_at) -> None:
        self.replacements.append((start_date, end_date, rows))
        self.metadata = {"synced_at": synced_at, "item_count": len(rows)}


class FakeProvider:
    LEAGUE_IDS = {"epl": 1, "laliga": 2, "csl": 3}

    def __init__(self, *, configured=True, error=False) -> None:
        self.configured = configured
        self.error = error
        self.calls = 0

    async def fixtures(self, start_date, end_date):
        self.calls += 1
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
