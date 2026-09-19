"""Backfill per-match team statistics (shots / SOT / corners) onto fixtures.

Sources: API-Football ``/fixtures/statistics`` for finished fixtures that
carry an ``external_ids.api_football`` id. The resulting ``match_stats``
payload shape matches the Football-Data ingestion so ``team_stats``
profiles and the Feature Engine strength fallbacks read one format.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .fixture_matching import find_fixture_rows
from .historical_validation import parse_timestamp

STAT_LEAGUES: tuple[str, ...] = ("epl", "laliga", "csl", "cfa_cup")
# 源上暂缺的每场只按天重试，避免长期缺数据的比赛耗尽每日 API 配额。
RETRY_AFTER = timedelta(hours=24)


def pending_match_stats_fixtures(
    repository: Any,
    *,
    leagues: tuple[str, ...] = STAT_LEAGUES,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Finished fixtures with an API-Football id but no match_stats yet."""

    current = now or datetime.now(UTC)
    reader = getattr(repository, "list_fixtures", None)
    rows = reader() if callable(reader) else []
    pending: list[dict[str, Any]] = []
    for row in rows or []:
        if str(row.get("league_key") or "") not in leagues:
            continue
        if row.get("status") != "finished":
            continue
        if isinstance(row.get("match_stats"), dict) and row.get("match_stats"):
            continue
        attempted = parse_timestamp(row.get("match_stats_unavailable_at"))
        if attempted is not None and current - attempted < RETRY_AFTER:
            continue
        external_id = (row.get("external_ids") or {}).get("api_football")
        if not external_id:
            continue
        pending.append(row)
    pending.sort(key=lambda row: str(row.get("kickoff") or ""), reverse=True)
    return pending


async def sync_match_stats(
    repository: Any,
    provider: Any,
    *,
    leagues: tuple[str, ...] = STAT_LEAGUES,
    limit: int = 25,
    localize: Any = None,
) -> dict[str, Any]:
    """Enrich up to ``limit`` finished fixtures per run (idempotent).

    Every provider row of the same physical match receives the statistics,
    so Feature Engine history series stay complete across duplicates.
    """

    localize = localize or _identity
    pending = pending_match_stats_fixtures(repository, leagues=leagues)
    all_rows = _all_rows(repository)
    enriched = 0
    unavailable = 0
    failed = 0
    rows_written = 0
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for row in pending[: max(0, int(limit))]:
        external_id = row["external_ids"]["api_football"]
        try:
            stats = await provider.fixture_statistics(external_id)
        except Exception:
            failed += 1
            continue
        merged = dict(row)
        if not stats:
            # 标记本次拉取时间；24h 后才会再次尝试（见 pending 过滤）。
            merged["match_stats_unavailable_at"] = now
            repository.upsert_fixture(merged, synced_at=now)
            unavailable += 1
            continue
        score = row.get("score") if isinstance(row.get("score"), dict) else {}
        siblings = find_fixture_rows(
            all_rows,
            kickoff=row.get("kickoff"),
            home_title=str((row.get("home_team") or {}).get("name") or ""),
            away_title=str((row.get("away_team") or {}).get("name") or ""),
            localize=localize,
            home_goals=score.get("home"),
            away_goals=score.get("away"),
        )
        targets = {str(s["id"]): s for s in siblings} or {str(row["id"]): row}
        for target in targets.values():
            merged = dict(target)
            merged["match_stats"] = {**stats, "source": "api-football", "captured_at": now}
            repository.upsert_fixture(merged, synced_at=now)
            rows_written += 1
        enriched += 1
    return {
        "status": "completed",
        "pending": len(pending),
        "enriched": enriched,
        "unavailable": unavailable,
        "failed": failed,
        "rows_written": rows_written,
        "item_count": enriched,
    }


def _all_rows(repository: Any) -> list[dict[str, Any]]:
    reader = getattr(repository, "list_fixtures", None)
    return list(reader()) if callable(reader) else []


def _identity(value: str) -> str:
    return str(value or "")
