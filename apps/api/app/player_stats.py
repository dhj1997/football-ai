"""Player season statistics: ESPN ingestion and squad evidence merge.

The deterministic player-impact model already consumes per-player season
statistics (appearances / starts / minutes / goals / assists / saves);
this module is the data supply. ESPN's roster endpoint provides exactly
those keys for the current season with no key or season restriction, and
its athlete ids are the same id space as the stored squad evidence.

Only the evidence layer merges live snapshots: the numeric ``player_impact``
feature keeps its rule-based path, because season snapshots carry no as-of
availability and would leak future information into historical features.
ESPN does not cover the CFA Cup, so ``cfa_cup`` stays rule-based/estimated.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from .competition_registry import season_for

# ESPN 联赛覆盖（LEAGUE_SLUGS）之外的足协杯不接入。
STAT_LEAGUES: tuple[str, ...] = ("epl", "laliga", "csl")


async def sync_player_stats(
    repository: Any,
    team_provider: Any,
    *,
    leagues: tuple[str, ...] = STAT_LEAGUES,
    limit: int = 8,
    stale_after_days: int = 7,
    request_interval_seconds: float = 1.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh season statistics for up to ``limit`` stale teams per run.

    The provider team list is cached once per league-season; rosters are
    paced to stay polite to the public ESPN endpoints.
    """

    current = now or datetime.now(UTC)
    today = current.date()
    stale_after = timedelta(days=max(1, int(stale_after_days)))
    fetched_teams = 0
    players_saved = 0
    failed = 0
    skipped_fresh = 0
    for league in leagues:
        season = season_for(league, today)
        teams = repository.league_teams(league, str(season))
        if teams is None:
            teams = await team_provider.teams(league)
            await _pace(request_interval_seconds)
            repository.save_league_teams(league, str(season), teams)
        for team in teams or []:
            if fetched_teams >= max(0, int(limit)):
                break
            team_id = str(team.get("id") or "")
            if not team_id:
                continue
            synced_at = repository.player_stats_synced_at(team_id, str(season))
            if synced_at and current - _parse(synced_at, current) < stale_after:
                skipped_fresh += 1
                continue
            try:
                players = await team_provider.team_players(league, team_id)
            except Exception:
                failed += 1
                continue
            await _pace(request_interval_seconds)
            fetched_teams += 1
            players_saved += _save_player_rows(
                repository, league, season, team_id, players, current
            )
        if fetched_teams >= max(0, int(limit)):
            break
    return {
        "status": "completed",
        "teams_fetched": fetched_teams,
        "players_saved": players_saved,
        "skipped_fresh": skipped_fresh,
        "failed": failed,
        "item_count": players_saved,
    }


class PlayerStatsService:
    """Merge stored season statistics into prediction squad evidence."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    async def enrich(self, context: dict[str, Any], league_key: str, season: str) -> dict[str, Any]:
        """Attach ``statistics`` to squad rows matched by ESPN athlete id.

        Squad evidence rows come from the ESPN provider with
        ``provider_player_id`` in the same id space as the snapshots; squads
        from other providers (dongqiudi) keep their estimated minutes path.
        """

        squads = context.get("squads") if isinstance(context.get("squads"), dict) else {}
        requested: list[str] = []
        for side in ("home", "away"):
            for player in squads.get(side) or []:
                player_id = player.get("provider_player_id") or player.get("id")
                if player_id not in (None, ""):
                    requested.append(str(player_id))
        rows = self.repository.player_stats(requested, season) if requested else []
        by_player: dict[str, dict[str, Any]] = {}
        for row in rows:  # ordered by synced_at: later snapshots win
            if row.get("player_id") and row.get("statistics"):
                by_player[str(row["player_id"])] = row
        attached = 0
        for side in ("home", "away"):
            for player in squads.get(side) or []:
                row = by_player.get(str(player.get("provider_player_id") or player.get("id")))
                if row is None:
                    continue
                player["statistics"] = dict(row["statistics"])
                player["statistics_source"] = str(row.get("source") or "espn")
                player["statistics_season"] = str(season)
                player["statistics_snapshot_id"] = str(row.get("id") or "") or None
                player["statistics_synced_at"] = row.get("synced_at")
                attached += 1
        return {
            "source": "espn",
            "season": str(season),
            "players_attached": attached,
            "players_requested": len(requested),
        }


def _save_player_rows(
    repository: Any,
    league: str,
    season: int,
    team_id: str,
    players: list[dict[str, Any]],
    current: datetime,
) -> int:
    synced_at = current.replace(microsecond=0).isoformat()
    rows = []
    for player in players:
        player_id = str(player.get("provider_player_id") or "")
        if not player_id:
            continue
        rows.append(
            {
                "id": f"pstats:espn:{player_id}:{season}",
                "league": league,
                "season": str(season),
                "team_id": team_id,
                "player_id": player_id,
                "synced_at": synced_at,
                "source": "espn",
                "name": player.get("name"),
                "position": player.get("position"),
                "statistics": player.get("statistics") or {},
            }
        )
    return repository.save_player_stats(rows) if rows else 0


async def _pace(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


def _parse(value: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return fallback
