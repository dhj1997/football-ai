from datetime import UTC, datetime

import pytest

from app.league_sync import LeagueSyncService


class FakeRepository:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.saved = 0

    def league_snapshots(self) -> list[dict]:
        return self.rows

    def save_league_snapshots(self, rows: list[dict]) -> None:
        self.rows = rows
        self.saved += 1


class FakeProvider:
    LEAGUE_SLUGS = {"epl": "eng.1", "laliga": "esp.1", "csl": "chn.1"}

    def __init__(self, rows: list[dict], error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.configured = True
        self.calls = 0

    async def standings(self) -> list[dict]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


def snapshots(updated_at: str) -> list[dict]:
    return [
        {"league_key": key, "updated_at": updated_at, "season": {"year": 2026}}
        for key in ("epl", "laliga", "csl")
    ]


@pytest.mark.asyncio
async def test_stale_tables_are_refreshed_once() -> None:
    fresh = snapshots(datetime.now(UTC).isoformat())
    repository = FakeRepository()
    provider = FakeProvider(fresh)
    service = LeagueSyncService(provider, repository, ttl_minutes=360)

    first = await service.ensure_fresh()
    second = await service.ensure_fresh()

    assert first["status"] == "updated"
    assert second["status"] == "fresh"
    assert provider.calls == 1
    assert repository.saved == 1


@pytest.mark.asyncio
async def test_refresh_failure_preserves_cached_tables() -> None:
    old = snapshots("2026-08-01T00:00:00+00:00")
    repository = FakeRepository(old)
    provider = FakeProvider([], RuntimeError("upstream unavailable"))
    service = LeagueSyncService(provider, repository, ttl_minutes=1)

    result = await service.ensure_fresh()

    assert result["status"] == "stale"
    assert repository.rows == old

