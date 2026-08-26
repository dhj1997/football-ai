from datetime import UTC, datetime

import pytest

from app.team_sync import TeamSyncService


class FakeRepository:
    def __init__(self, item: dict | None = None) -> None:
        self.item = item
        self.saved = 0

    def team_snapshot(self, league_key: str, team_id: str) -> dict | None:
        return self.item

    def save_team_snapshot(self, item: dict) -> None:
        self.item = item
        self.saved += 1


class FakeProvider:
    configured = True

    def __init__(self, item: dict | None = None, error: Exception | None = None) -> None:
        self.item = item
        self.error = error
        self.calls = 0

    async def team(self, league_key: str, team_id: str, season_year: int) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.item is not None
        return self.item


def snapshot(updated_at: str) -> dict:
    return {
        "league_key": "epl",
        "team_id": "359",
        "season": {"year": 2026},
        "updated_at": updated_at,
    }


@pytest.mark.asyncio
async def test_team_data_is_cached_after_refresh() -> None:
    item = snapshot(datetime.now(UTC).isoformat())
    repository = FakeRepository()
    provider = FakeProvider(item)
    service = TeamSyncService(provider, repository, ttl_minutes=360)

    first = await service.ensure_fresh("epl", "359", 2026)
    second = await service.ensure_fresh("epl", "359", 2026)

    assert first["status"] == "updated"
    assert second["status"] == "fresh"
    assert provider.calls == 1
    assert repository.saved == 1


@pytest.mark.asyncio
async def test_team_refresh_failure_preserves_stale_snapshot() -> None:
    old = snapshot("2026-08-01T00:00:00+00:00")
    service = TeamSyncService(
        FakeProvider(error=RuntimeError("upstream unavailable")),
        FakeRepository(old),
        ttl_minutes=1,
    )

    result = await service.ensure_fresh("epl", "359", 2026)

    assert result == {"status": "stale", "item": old}
