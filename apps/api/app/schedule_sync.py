"""Freshness policy for the local fixture cache."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from .data import CHINA_TZ
from .team_names import to_chinese_team_name


class ScheduleSyncService:
    """Refresh the schedule cache once when it is absent or stale."""

    def __init__(
        self,
        provider: Any,
        repository: Any,
        lookback_days: int,
        ttl_minutes: int,
        result_provider: Any | None = None,
        lookahead_days: int = 1,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.result_provider = result_provider
        self.lookback_days = lookback_days
        self.lookahead_days = max(1, int(lookahead_days))
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()
        self._cached_rows: list[dict[str, Any]] | None = None
        self._cached_metadata: dict[str, Any] | None = None
        self._cached_revision: int | None = None
        self._cache_load_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None

    async def ensure_fresh(self) -> dict[str, Any]:
        """Refresh stale data, falling back to an existing cache on failure."""

        now = datetime.now(UTC)
        metadata = await asyncio.to_thread(self.repository.fixture_sync)
        if self._is_fresh(metadata, now):
            return self._state("fresh", metadata)
        if not self.provider.configured:
            return self._state("stale" if metadata else "unconfigured", metadata)

        async with self._lock:
            metadata = await asyncio.to_thread(self.repository.fixture_sync)
            if self._is_fresh(metadata, now):
                return self._state("fresh", metadata)
            try:
                return await self._refresh(now)
            except Exception:
                metadata = await asyncio.to_thread(self.repository.fixture_sync)
                return self._state("stale" if metadata else "failed", metadata)

    async def warm_cache(self) -> None:
        """Load the persisted fixture window without blocking the event loop."""

        if self._cached_rows is not None:
            return
        async with self._cache_load_lock:
            if self._cached_rows is not None:
                return
            rows, metadata, revision = await asyncio.to_thread(self._read_cache)
            self._cached_rows = rows
            self._cached_metadata = metadata
            self._cached_revision = revision

    def cached_fixtures(self, start_date: str | None, end_date: str | None) -> list[dict[str, Any]] | None:
        """Return the last loaded fixture snapshot, or ``None`` before warmup."""

        current_revision = self._repository_revision()
        if self._cached_rows is not None and self._cached_revision is not None and current_revision != self._cached_revision:
            self._cached_rows = None
            self._cached_metadata = None
            self._cached_revision = None
            return None
        if self._cached_rows is None:
            return None
        return [
            row
            for row in self._cached_rows
            if (start_date is None or str(row.get("fixture_date") or "") >= start_date)
            and (end_date is None or str(row.get("fixture_date") or "") <= end_date)
        ]

    def cached_state(self) -> dict[str, Any]:
        metadata = self._cached_metadata
        if metadata is None:
            return self._state("unconfigured", None)
        status = "fresh" if self._is_fresh(metadata, datetime.now(UTC)) else "stale"
        return self._state(status, metadata)

    def refresh_in_background(self) -> None:
        """Start one refresh without making the public list wait for it."""

        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self.ensure_fresh(), name="fixture-cache-refresh")

    def _read_cache(self) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int | None]:
        return self.repository.list_fixtures(), self.repository.fixture_sync(), self._repository_revision()

    def _repository_revision(self) -> int | None:
        getter = getattr(self.repository, "fixture_revision", None)
        try:
            return int(getter()) if callable(getter) else None
        except (TypeError, ValueError):
            return None

    async def force_refresh(self) -> dict[str, Any]:
        """Refresh immediately for an explicit operator action."""

        if not self.provider.configured:
            raise RuntimeError("免费赛程数据源未配置")
        async with self._lock:
            return await self._refresh(datetime.now(UTC))

    async def _refresh(self, now: datetime) -> dict[str, Any]:
        today = now.astimezone(CHINA_TZ).date()
        start_date = today - timedelta(days=self.lookback_days)
        end_date = today + timedelta(days=self.lookahead_days)
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
        await asyncio.to_thread(
            self.repository.replace_fixtures,
            start_date.isoformat(),
            end_date.isoformat(),
            rows,
            synced_at,
        )
        if self._cached_rows is None:
            self._cached_rows = list(rows)
        else:
            self._cached_rows = [
                row
                for row in self._cached_rows
                if not (start_date.isoformat() <= str(row.get("fixture_date") or "") <= end_date.isoformat())
            ] + list(rows)
        self._cached_metadata = {"synced_at": synced_at, "item_count": len(rows)}
        self._cached_revision = self._repository_revision()
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


def deduplicate_fixtures(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate provider records without merging distinct fixtures."""

    unique: list[dict[str, Any]] = []
    for incoming in fixtures:
        duplicate_index = next(
            (index for index, existing in enumerate(unique) if _same_fixture_identity(existing, incoming)),
            None,
        )
        if duplicate_index is None:
            unique.append(incoming)
            continue
        unique[duplicate_index] = _merge_duplicate_fixture(unique[duplicate_index], incoming)
    return unique


def _same_fixture_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Match one league, one home/away direction, and one kickoff window."""

    if left.get("id") == right.get("id"):
        return True
    if str(left.get("league_key") or "").casefold() != str(right.get("league_key") or "").casefold():
        return False
    if _shared_external_id(left, right):
        return True
    left_kickoff = _as_utc(left.get("kickoff"))
    right_kickoff = _as_utc(right.get("kickoff"))
    if left_kickoff is None or right_kickoff is None:
        return False
    if abs((left_kickoff - right_kickoff).total_seconds()) > 900:
        return False
    return (
        _canonical_team_name(left.get("home_team")) == _canonical_team_name(right.get("home_team"))
        and _canonical_team_name(left.get("away_team")) == _canonical_team_name(right.get("away_team"))
    )


def _shared_external_id(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_ids = left.get("external_ids") or {}
    right_ids = right.get("external_ids") or {}
    return any(
        str(value).strip() and str(value) == str(right_ids.get(key))
        for key, value in left_ids.items()
    )


def _canonical_team_name(value: Any) -> str:
    """Normalize common provider suffixes while preserving team direction."""

    name = to_chinese_team_name(_team_name(value)).replace(" ", "")
    for suffix in ("足球俱乐部", "足球队"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _as_utc(value: Any) -> datetime | None:
    try:
        kickoff = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return kickoff.replace(tzinfo=UTC) if kickoff.tzinfo is None else kickoff.astimezone(UTC)


def _merge_duplicate_fixture(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Keep the richer data while retaining the canonical schedule identity."""

    winner, other = sorted((left, right), key=_fixture_richness, reverse=True)
    merged = {**other, **winner}
    merged["external_ids"] = {**(other.get("external_ids") or {}), **(winner.get("external_ids") or {})}
    for field in ("evidence", "predictions", "prediction", "dongqiudi", "dongqiudi_sync", "free_team_data"):
        other_value = other.get(field)
        winner_value = winner.get(field)
        if isinstance(other_value, dict) and isinstance(winner_value, dict):
            merged[field] = {**other_value, **winner_value}
        elif not winner_value and other_value:
            merged[field] = other_value

    # The schedule-provider ID is the stable application identity. A
    # Dongqiudi-only row may still be richer, but it must not replace the
    # existing schedule row when both providers describe the same match.
    canonical = next((item for item in (left, right) if not _is_dongqiudi_fixture(item)), winner)
    for field in ("id", "provider_id", "league_key", "fixture_date", "kickoff", "league", "venue", "is_demo"):
        if field in canonical:
            merged[field] = canonical[field]
    for side in ("home", "away"):
        canonical_team = dict(canonical.get(f"{side}_team") or {})
        preferred_team = dict(winner.get(f"{side}_team") or {})
        if preferred_team.get("name") and not _contains_chinese(canonical_team.get("name")):
            canonical_team["name"] = preferred_team["name"]
        if preferred_team.get("logo"):
            canonical_team["logo"] = preferred_team["logo"]
        merged[f"{side}_team"] = canonical_team

    # A provider can lag behind the result provider. Preserve a terminal or
    # live result over a scheduled duplicate, including a valid 0:0 score.
    result = max((left, right), key=_fixture_result_priority)
    if _fixture_result_priority(result)[0] >= 2:
        for field in ("status", "provider_status", "score", "result_source", "result_synced_at"):
            if field in result:
                merged[field] = result[field]
    return merged


def _is_dongqiudi_fixture(fixture: dict[str, Any]) -> bool:
    return str(fixture.get("source") or "").casefold() == "dongqiudi" or str(fixture.get("id") or "").startswith("dongqiudi-")


def _contains_chinese(value: Any) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in str(value or ""))


def _fixture_result_priority(fixture: dict[str, Any]) -> tuple[int, int]:
    status = str(fixture.get("status") or "").casefold()
    rank = {"scheduled": 0, "postponed": 0, "live": 2, "finished": 3}.get(status, 1 if fixture.get("score") is not None else 0)
    return rank, int(fixture.get("score") is not None)


def _fixture_richness(fixture: dict[str, Any]) -> tuple[int, int, int, str]:
    evidence = fixture.get("evidence") or {}
    return (
        sum(bool(value) for value in evidence.values()) if isinstance(evidence, dict) else 0,
        int(bool(fixture.get("predictions"))) + int(bool(fixture.get("prediction"))),
        int(fixture.get("source") == "dongqiudi"),
        str(fixture.get("id") or ""),
    )
