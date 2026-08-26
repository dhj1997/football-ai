"""Freshness and fallback policy for cached league tables."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any


class LeagueSyncService:
    """Keep current standings fresh while preserving the last good snapshot."""

    def __init__(self, provider: Any, repository: Any, ttl_minutes: int) -> None:
        self.provider = provider
        self.repository = repository
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def ensure_fresh(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        snapshots = self.repository.league_snapshots()
        if self._is_fresh(snapshots, now):
            return self._state("fresh", snapshots)
        if not self.provider.configured:
            return self._state("stale" if snapshots else "unconfigured", snapshots)
        async with self._lock:
            snapshots = self.repository.league_snapshots()
            if self._is_fresh(snapshots, now):
                return self._state("fresh", snapshots)
            try:
                return await self._refresh()
            except Exception:
                snapshots = self.repository.league_snapshots()
                return self._state("stale" if snapshots else "failed", snapshots)

    async def force_refresh(self) -> dict[str, Any]:
        async with self._lock:
            return await self._refresh()

    async def _refresh(self) -> dict[str, Any]:
        snapshots = await self.provider.standings()
        self.repository.save_league_snapshots(snapshots)
        return self._state("updated", snapshots)

    def _is_fresh(self, snapshots: list[dict[str, Any]], now: datetime) -> bool:
        if len(snapshots) != len(self.provider.LEAGUE_SLUGS):
            return False
        try:
            newest_allowed = min(
                datetime.fromisoformat(snapshot["updated_at"]).astimezone(UTC)
                for snapshot in snapshots
            )
        except (KeyError, TypeError, ValueError):
            return False
        age = now - newest_allowed
        return timedelta(0) <= age <= self.ttl

    @staticmethod
    def _state(status: str, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        timestamps = [item.get("updated_at") for item in snapshots if item.get("updated_at")]
        return {
            "status": status,
            "item_count": len(snapshots),
            "last_synced_at": max(timestamps) if timestamps else None,
        }

