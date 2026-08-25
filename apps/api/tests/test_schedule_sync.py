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
