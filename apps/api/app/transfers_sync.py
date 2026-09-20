"""Team transfer records ingestion and pre-match transfer evidence.

API-Football ``/transfers?team=`` records are stored per team (weekly
staleness, one attempt marker so plan/quota errors don't burn the daily
budget) and merged into prediction evidence as each side's recent transfer
activity. Team ids come from the fixture evidence ``team_ids`` captured by
the API-Football evidence sync.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .competition_registry import season_for
from .historical_validation import parse_timestamp
from .team_names import to_chinese_player_name, to_chinese_team_name

TRANSFER_LEAGUES: tuple[str, ...] = ("epl", "laliga", "csl", "cfa_cup")
STALE_AFTER = timedelta(days=30)


async def sync_transfers(
    repository: Any,
    provider: Any,
    *,
    leagues: tuple[str, ...] = TRANSFER_LEAGUES,
    limit: int = 6,
    lookahead_days: int = 14,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh transfer records for up to ``limit`` stale teams per run."""

    current = now or datetime.now(UTC)
    rows = repository.list_fixtures() or []
    identity_index = _api_football_identity_index(repository)
    team_ids, target_state = _transfer_targets(
        rows,
        leagues,
        current=current,
        lookahead_days=lookahead_days,
        identity_index=identity_index,
    )
    run = _start_sync_run(repository, target_state)
    attempted = 0
    fetched = 0
    failed = 0
    empty = 0
    skipped_fresh = 0
    records_saved = 0
    errors: list[str] = []
    now_iso = current.replace(microsecond=0).isoformat()
    for league_key, team_id in team_ids:
        if attempted >= max(0, int(limit)):
            break
        season = str(season_for(league_key, current.date()))
        existing = repository.team_transfers_row(team_id, season)
        if existing is not None:
            synced = parse_timestamp(existing.get("synced_at"))
            if synced is not None and current - synced < STALE_AFTER:
                skipped_fresh += 1
                continue
        attempted += 1
        try:
            transfers = await provider.team_transfers(team_id)
        except Exception as error:
            failed += 1
            errors.append(f"team {team_id}: {type(error).__name__}: {str(error)[:200]}")
            continue
        localized = []
        for record in transfers:
            item = dict(record)
            if item.get("player"):
                item["player"] = to_chinese_player_name(str(item["player"]))
            localized.append(item)
        transfers = localized
        repository.save_team_transfers(team_id, season, transfers, now_iso)
        fetched += 1
        records_saved += len(transfers)
        if not transfers:
            empty += 1
    status = "zero_targets" if not team_ids else "failed" if failed and not fetched else "partial" if failed else "completed"
    result = {
        "status": status,
        **target_state,
        "teams_targeted": len(team_ids),
        "teams_attempted": attempted,
        "teams_fetched": fetched,
        "records_saved": records_saved,
        "empty_teams": empty,
        "skipped_fresh": skipped_fresh,
        "failed": failed,
        "errors": errors[:20],
        "item_count": records_saved,
    }
    _finish_sync_run(
        repository,
        run,
        status="completed" if status in {"completed", "zero_targets"} else status,
        records_seen=attempted,
        records_inserted=records_saved,
        records_rejected=failed + int(target_state["provider_id_missing"]),
        error_category="provider_request_failed" if failed else "provider_id_missing" if target_state["provider_id_missing"] else None,
        errors=errors[:20],
    )
    return result


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
    identity_index = _api_football_identity_index(repository)
    home_id = team_ids.get("home") or _identity_team_id(identity_index, fixture, "home")
    away_id = team_ids.get("away") or _identity_team_id(identity_index, fixture, "away")
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
                name = to_chinese_player_name(str(record["player"]))
                transfers_in.append(f"{name}（{date}，自 {record.get('out_team') or '未知'}）")
            if str(record.get("out_team_id") or "") == str(team_id) and record.get("player"):
                name = to_chinese_player_name(str(record["player"]))
                transfers_out.append(f"{name}（{date}，至 {record.get('in_team') or '未知'}）")
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


def _transfer_targets(
    rows: list[dict[str, Any]],
    leagues: tuple[str, ...],
    *,
    current: datetime,
    lookahead_days: int,
    identity_index: Mapping[tuple[str, str], str] | None = None,
) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Upcoming distinct teams with real API-Football IDs and target diagnostics."""

    seen: dict[str, str] = {}
    upcoming = 0
    provider_id_missing = 0
    identity_resolved = 0
    horizon = current + timedelta(days=max(1, int(lookahead_days)))
    for row in rows:
        if str(row.get("league_key") or "") not in leagues:
            continue
        if str(row.get("status") or "").casefold() != "scheduled":
            continue
        kickoff = parse_timestamp(row.get("kickoff"))
        if kickoff is None or kickoff < current or kickoff > horizon:
            continue
        upcoming += 1
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        team_ids = evidence.get("team_ids") if isinstance(evidence.get("team_ids"), dict) else {}
        league_key = str(row.get("league_key") or "")
        for side in ("home", "away"):
            team_id = team_ids.get(side)
            if team_id in (None, ""):
                team_id = _identity_team_id(identity_index or {}, row, side)
                if team_id not in (None, ""):
                    identity_resolved += 1
            if team_id in (None, ""):
                provider_id_missing += 1
                continue
            seen.setdefault(str(team_id), league_key)
    return (
        [(league, team_id) for team_id, league in seen.items()],
        {
            "upcoming_fixture_count": upcoming,
            "provider_id_missing": provider_id_missing,
            "identity_resolved": identity_resolved,
        },
    )


def _api_football_identity_index(repository: Any) -> dict[tuple[str, str], str]:
    reader = getattr(repository, "team_identities", None)
    identities = reader(limit=1000) if callable(reader) else []
    candidates: dict[tuple[str, str], set[str]] = {}
    for item in identities or []:
        if str(item.get("source") or "").casefold() != "api-football":
            continue
        if str(item.get("identity_status") or "").casefold() != "resolved" or item.get("conflict"):
            continue
        provider_id = str(item.get("source_team_id") or "")
        key = (
            _league_key(item.get("league")),
            _team_name_key(item.get("display_name") or item.get("normalized_name")),
        )
        if provider_id and all(key):
            candidates.setdefault(key, set()).add(provider_id)
    return {
        key: next(iter(values))
        for key, values in candidates.items()
        if len(values) == 1
    }


def _identity_team_id(
    identity_index: Mapping[tuple[str, str], str],
    fixture: Mapping[str, Any],
    side: str,
) -> str | None:
    team = fixture.get(f"{side}_team")
    name = team.get("name") if isinstance(team, Mapping) else None
    return identity_index.get(
        (_league_key(fixture.get("league_key")), _team_name_key(name))
    )


def _league_key(value: Any) -> str:
    normalized = str(value or "").strip().casefold().replace("_", "")
    return {"lal": "laliga", "laliga": "laliga", "epl": "epl", "csl": "csl", "cfacup": "cfacup"}.get(
        normalized,
        normalized,
    )


def _team_name_key(value: Any) -> str:
    return "".join(to_chinese_team_name(str(value or "")).split()).casefold()


def _start_sync_run(repository: Any, target_state: Mapping[str, int]) -> dict[str, Any]:
    run = {
        "run_id": f"sync:{uuid.uuid4()}",
        "provider": "api-football",
        "league": None,
        "entity_type": "transfers",
        "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "finished_at": None,
        "status": "running",
        "records_seen": 0,
        "records_inserted": 0,
        "records_updated": 0,
        "records_rejected": 0,
        "error_category": None,
        "errors": [],
        "config": dict(target_state),
    }
    saver = getattr(repository, "save_data_sync_run", None)
    if callable(saver):
        saver(run)
    return run


def _finish_sync_run(repository: Any, run: Mapping[str, Any], **updates: Any) -> None:
    updates["finished_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    updater = getattr(repository, "update_data_sync_run", None)
    if callable(updater):
        updater(str(run["run_id"]), updates)
