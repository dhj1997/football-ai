"""Freshness policy for the local fixture cache."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from .data import CHINA_TZ


class ScheduleSyncService:
    """Refresh the schedule cache once when it is absent or stale."""

    def __init__(
        self,
        provider: Any,
        repository: Any,
        lookback_days: int,
        ttl_minutes: int,
        result_provider: Any | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.result_provider = result_provider
        self.lookback_days = lookback_days
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def ensure_fresh(self) -> dict[str, Any]:
        """Refresh stale data, falling back to an existing cache on failure."""

        now = datetime.now(UTC)
        metadata = self.repository.fixture_sync()
        if self._is_fresh(metadata, now):
            return self._state("fresh", metadata)
        if not self.provider.configured:
            return self._state("stale" if metadata else "unconfigured", metadata)

        async with self._lock:
            metadata = self.repository.fixture_sync()
            if self._is_fresh(metadata, now):
                return self._state("fresh", metadata)
            try:
                return await self._refresh(now)
            except Exception:
                metadata = self.repository.fixture_sync()
                return self._state("stale" if metadata else "failed", metadata)

    async def force_refresh(self) -> dict[str, Any]:
        """Refresh immediately for an explicit operator action."""

        if not self.provider.configured:
            raise RuntimeError("免费赛程数据源未配置")
        async with self._lock:
            return await self._refresh(datetime.now(UTC))

    async def _refresh(self, now: datetime) -> dict[str, Any]:
        today = now.astimezone(CHINA_TZ).date()
        start_date = today - timedelta(days=self.lookback_days)
        end_date = today + timedelta(days=1)
        rows = await self.provider.fixtures(start_date, end_date)
        result_status = "unavailable"
        if self.result_provider is not None and bool(getattr(self.result_provider, "configured", False)):
            try:
                result_rows = await self.result_provider.fixtures(start_date, end_date)
                rows = _merge_result_rows(rows, result_rows)
                result_status = "updated"
            except Exception:
                result_status = "failed"
        request_count = ((end_date - start_date).days + 1) * len(self.provider.LEAGUE_IDS)
        enrich = getattr(self.provider, "enrich_fixtures", None)
        if callable(enrich):
            rows = await enrich(rows, max_teams=max(0, (30 - request_count) // 2))
        synced_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        self.repository.replace_fixtures(
            start_date.isoformat(),
            end_date.isoformat(),
            rows,
            synced_at,
        )
        return {
            **self._state(
                "updated",
                {"synced_at": synced_at, "item_count": len(rows)},
            ),
            "request_count": request_count,
            "result_sync_status": result_status,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        }

    def _is_fresh(self, metadata: dict[str, Any] | None, now: datetime) -> bool:
        if not metadata:
            return False
        try:
            synced_at = datetime.fromisoformat(metadata["synced_at"])
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=UTC)
        except (KeyError, TypeError, ValueError):
            return False
        age = now - synced_at.astimezone(UTC)
        same_local_day = synced_at.astimezone(CHINA_TZ).date() == now.astimezone(CHINA_TZ).date()
        return same_local_day and timedelta(0) <= age <= self.ttl

    @staticmethod
    def _state(status: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "status": status,
            "last_synced_at": metadata.get("synced_at") if metadata else None,
            "item_count": metadata.get("item_count", 0) if metadata else 0,
        }


def _merge_result_rows(primary_rows: list[dict[str, Any]], result_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Overlay only confidently matched status and score fields."""

    result_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    ambiguous: set[tuple[str, str, str, str]] = set()
    for row in result_rows:
        key = _fixture_key(row)
        if key is None:
            continue
        if key in result_index:
            ambiguous.add(key)
        else:
            result_index[key] = row
    merged_rows: list[dict[str, Any]] = []
    for row in primary_rows:
        key = _fixture_key(row)
        result = result_index.get(key) if key is not None and key not in ambiguous else None
        if result is None or result.get("status") == "scheduled":
            merged_rows.append(row)
            continue
        merged = dict(row)
        merged["status"] = result["status"]
        merged["provider_status"] = result.get("provider_status")
        merged["score"] = result.get("score") if result["status"] in {"live", "finished"} else None
        merged["result_source"] = "espn"
        merged["result_synced_at"] = result.get("captured_at")
        merged_rows.append(merged)
    return merged_rows


def _fixture_key(row: dict[str, Any]) -> tuple[str, str, str, str] | None:
    try:
        kickoff = datetime.fromisoformat(str(row.get("kickoff") or "").replace("Z", "+00:00"))
        kickoff = kickoff.replace(tzinfo=UTC) if kickoff.tzinfo is None else kickoff.astimezone(UTC)
    except (TypeError, ValueError):
        return None
    home = _team_name(row.get("home_team"))
    away = _team_name(row.get("away_team"))
    league = str(row.get("league_key") or "").casefold()
    if not league or not home or not away:
        return None
    return league, kickoff.replace(second=0, microsecond=0).isoformat(), home, away


def _team_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return " ".join(str(value.get("name") or "").casefold().split())
