"""Team transfer records ingestion and pre-match transfer evidence.

API-Football ``/transfers?team=`` records are stored per team (weekly
staleness, one attempt marker so plan/quota errors don't burn the daily
budget) and merged into prediction evidence as each side's recent transfer
activity. Team ids come from the fixture evidence ``team_ids`` captured by
the API-Football evidence sync.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .competition_registry import season_for
from .historical_validation import parse_timestamp

TRANSFER_LEAGUES: tuple[str, ...] = ("epl", "laliga", "csl", "cfa_cup")
STALE_AFTER = timedelta(days=30)


async def sync_transfers(
    repository: Any,
    provider: Any,
    *,
    leagues: tuple[str, ...] = TRANSFER_LEAGUES,
    limit: int = 6,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh transfer records for up to ``limit`` stale teams per run."""

    current = now or datetime.now(UTC)
    rows = repository.list_fixtures() or []
    team_ids = _evidence_team_ids(rows, leagues)
    fetched = 0
    failed = 0
    skipped_fresh = 0
    records_saved = 0
    now_iso = current.replace(microsecond=0).isoformat()
    for league_key, team_id in team_ids:
        if fetched >= max(0, int(limit)):
            break
        season = str(season_for(league_key, current.date()))
        existing = repository.team_transfers_row(team_id, season)
        if existing is not None:
            synced = parse_timestamp(existing.get("synced_at"))
            if synced is not None and current - synced < STALE_AFTER:
                skipped_fresh += 1
                continue
        try:
            transfers = await provider.team_transfers(team_id)
        except Exception:
            failed += 1
            continue
        repository.save_team_transfers(team_id, season, transfers, now_iso)
        fetched += 1
        records_saved += len(transfers)
    return {
        "status": "completed",
        "teams_fetched": fetched,
        "records_saved": records_saved,
        "skipped_fresh": skipped_fresh,
        "failed": failed,
        "item_count": records_saved,
    }


def attach_transfers(
    repository: Any,
    fixture: Mapping,
    context: dict[str, Any],
    *,
    recent_days: int = 45,
    now: datetime | None = None,
) -> None:
    """Expose each side's transfer activity within the recent window."""

    evidence = fixture.get("evidence") if isinstance(fixture.get("evidence"), dict) else {}
    team_ids = evidence.get("team_ids") if isinstance(evidence.get("team_ids"), dict) else {}
    home_id = team_ids.get("home")
    away_id = team_ids.get("away")
    if home_id in (None, "") and away_id in (None, ""):
        return
    league_key = str(fixture.get("league_key") or "")
    season = str(season_for(league_key, (now or datetime.now(UTC)).date()))
    current = now or datetime.now(UTC)
    window_start = current - timedelta(days=max(1, int(recent_days)))
    sides: dict[str, Any] = {}
    for side, team_id in (("home", home_id), ("away", away_id)):
        row = repository.team_transfers_row(str(team_id), season) if team_id not in (None, "") else None
        if row is None:
            sides[side] = None
            continue
        transfers_in: list[str] = []
        transfers_out: list[str] = []
        for record in row.get("transfers") or []:
            date = str(record.get("date") or "")[:10]
            parsed = parse_timestamp(date) if date else None
            if parsed is None or parsed < window_start:
                continue
            if str(record.get("in_team_id") or "") == str(team_id) and record.get("player"):
                transfers_in.append(f"{record['player']}（{date}，自 {record.get('out_team') or '未知'}）")
            if str(record.get("out_team_id") or "") == str(team_id) and record.get("player"):
                transfers_out.append(f"{record['player']}（{date}，至 {record.get('in_team') or '未知'}）")
        sides[side] = {
            "transfers_in": sorted(set(transfers_in)),
            "transfers_out": sorted(set(transfers_out)),
            "window_days": int(recent_days),
        }
    if all(value is None for value in sides.values()):
        return
    context["transfers"] = {
        "home": sides.get("home"),
        "away": sides.get("away"),
        "source": "api-football",
    }


def _evidence_team_ids(rows: list[dict[str, Any]], leagues: tuple[str, ...]) -> list[tuple[str, str]]:
    """Distinct (league, api team id) pairs seen in fixture evidence, home first."""

    seen: dict[str, str] = {}
    for row in rows:
        if str(row.get("league_key") or "") not in leagues:
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        team_ids = evidence.get("team_ids") if isinstance(evidence.get("team_ids"), dict) else {}
        league_key = str(row.get("league_key") or "")
        for side in ("home", "away"):
            team_id = team_ids.get(side)
            if team_id in (None, ""):
                continue
            seen.setdefault(str(team_id), league_key)
    return [(league, team_id) for team_id, league in seen.items()]
