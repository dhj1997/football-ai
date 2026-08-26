"""Freshness policy for cached current-season team detail."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any


class TeamSyncService:
    def __init__(self, provider: Any, repository: Any, ttl_minutes: int) -> None:
        self.provider = provider
        self.repository = repository
        self.ttl = timedelta(minutes=ttl_minutes)
        self._locks: dict[str, asyncio.Lock] = {}

    async def ensure_fresh(self, league_key: str, team_id: str, season_year: int) -> dict[str, Any]:
        cached = self.repository.team_snapshot(league_key, team_id)
        if self._is_fresh(cached, season_year):
            return {"status": "fresh", "item": cached}
        if not self.provider.configured:
            return {"status": "stale" if cached else "unconfigured", "item": cached}

        lock = self._locks.setdefault(f"{league_key}:{team_id}", asyncio.Lock())
        async with lock:
            cached = self.repository.team_snapshot(league_key, team_id)
            if self._is_fresh(cached, season_year):
                return {"status": "fresh", "item": cached}
            try:
                item = await self.provider.team(league_key, team_id, season_year)
                self.repository.save_team_snapshot(item)
                return {"status": "updated", "item": item}
            except Exception:
                cached = self.repository.team_snapshot(league_key, team_id)
                return {"status": "stale" if cached else "failed", "item": cached}

    def _is_fresh(self, item: dict[str, Any] | None, season_year: int) -> bool:
        if not item or (item.get("season") or {}).get("year") != season_year:
            return False
        try:
            updated_at = datetime.fromisoformat(item["updated_at"]).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            return False
        age = datetime.now(UTC) - updated_at
        return timedelta(0) <= age <= self.ttl
