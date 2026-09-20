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
    dongqiudi_provider: Any | None = None,
    leagues: tuple[str, ...] = TRANSFER_LEAGUES,
    limit: int = 6,
    lookahead_days: int = 14,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh transfer records for up to ``limit`` stale teams per run."""

    current = now or datetime.now(UTC)
    rows = repository.list_fixtures() or []
    if dongqiudi_provider is not None and getattr(dongqiudi_provider, "configured", True):
        return await _sync_preferred_transfers(
            repository,
            rows,
            dongqiudi_provider,
            provider,
            leagues=leagues,
            limit=limit,
            lookahead_days=lookahead_days,
            current=current,
        )
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


async def _sync_preferred_transfers(
    repository: Any,
    rows: list[dict[str, Any]],
    dongqiudi_provider: Any,
    fallback_provider: Any | None,
    *,
    leagues: tuple[str, ...],
    limit: int,
    lookahead_days: int,
    current: datetime,
) -> dict[str, Any]:
    targets, target_state = _preferred_transfer_targets(
        rows,
        repository,
        leagues,
        current=current,
        lookahead_days=lookahead_days,
    )
    run = _start_sync_run(repository, target_state, provider="dongqiudi")
    attempted = fetched = failed = empty = skipped_fresh = records_saved = fallback_used = 0
    player_details_attempted = player_details_fetched = player_details_failed = 0
    errors: list[str] = []
    now_iso = current.replace(microsecond=0).isoformat()
    for target in targets:
        if attempted >= max(0, int(limit)):
            break
        league_key = str(target["league_key"])
        season = str(season_for(league_key, current.date()))
        source = "dongqiudi" if target.get("dongqiudi_id") else "api-football"
        team_id = str(target.get("dongqiudi_id") or target.get("api_football_id") or "")
        existing = repository.team_transfers_row(team_id, season, source=source)
        if existing is not None:
            synced = parse_timestamp(existing.get("synced_at"))
            if synced is not None and current - synced < STALE_AFTER:
                skipped_fresh += 1
                continue
        attempted += 1
        transfers: list[dict[str, Any]] | None = None
        primary_error: Exception | None = None
        if target.get("dongqiudi_id"):
            try:
                detailed_reader = getattr(dongqiudi_provider, "team_transfers_with_diagnostics", None)
                if callable(detailed_reader):
                    diagnostic = await detailed_reader(target["dongqiudi_id"])
                    player_details_attempted += int(diagnostic.get("players_attempted") or 0)
                    player_details_fetched += int(diagnostic.get("players_fetched") or 0)
                    player_details_failed += int(diagnostic.get("players_failed") or 0)
                    errors.extend(
                        f"{target['team_name']}: {message}"
                        for message in (diagnostic.get("errors") or [])[:5]
                    )
                    if diagnostic.get("status") == "failed":
                        primary_error = RuntimeError("Dongqiudi player details unavailable")
                    else:
                        transfers = list(diagnostic.get("transfers") or [])
                else:
                    transfers = await dongqiudi_provider.team_transfers(target["dongqiudi_id"])
            except Exception as error:
                primary_error = error
        if transfers is None and target.get("api_football_id") and fallback_provider is not None:
            source = "api-football"
            team_id = str(target["api_football_id"])
            fallback_used += 1
            try:
                transfers = await fallback_provider.team_transfers(team_id)
            except Exception as error:
                failed += 1
                errors.append(
                    f"{target['team_name']}: dongqiudi={type(primary_error).__name__ if primary_error else 'unavailable'}; "
                    f"api-football={type(error).__name__}: {str(error)[:160]}"
                )
                continue
        if transfers is None:
            failed += 1
            detail = f"{type(primary_error).__name__}: {str(primary_error)[:180]}" if primary_error else "no usable provider identity"
            errors.append(f"{target['team_name']}: {detail}")
            continue
        localized = []
        for record in transfers:
            item = dict(record)
            if item.get("player"):
                item["player"] = to_chinese_player_name(str(item["player"]))
            item.setdefault("source", source)
            localized.append(item)
        repository.save_team_transfers(team_id, season, localized, now_iso, source=source)
        fetched += 1
        records_saved += len(localized)
        if not localized:
            empty += 1
    status = (
        "zero_targets"
        if not targets
        else "failed"
        if failed and not fetched
        else "partial"
        if failed or player_details_failed
        else "completed"
    )
    result = {
        "status": status,
        **target_state,
        "teams_targeted": len(targets),
        "teams_attempted": attempted,
        "teams_fetched": fetched,
        "records_saved": records_saved,
        "empty_teams": empty,
        "skipped_fresh": skipped_fresh,
        "fallback_used": fallback_used,
        "player_details_attempted": player_details_attempted,
        "player_details_fetched": player_details_fetched,
        "player_details_failed": player_details_failed,
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
        records_rejected=failed + player_details_failed + int(target_state["provider_id_missing"]),
        error_category=(
            "provider_request_failed"
            if failed
            else "player_detail_partial"
            if player_details_failed
            else "provider_id_missing"
            if target_state["provider_id_missing"]
            else None
        ),
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
    dongqiudi_ids = _dongqiudi_team_ids(repository, fixture)
    api_ids = {
        side: team_ids.get(side) or _identity_team_id(identity_index, fixture, side)
        for side in ("home", "away")
    }
    if not any(dongqiudi_ids.values()) and not any(api_ids.values()):
        return
    league_key = str(fixture.get("league_key") or "")
    season = str(season_for(league_key, (now or datetime.now(UTC)).date()))
    current = now or datetime.now(UTC)
    window_start = current - timedelta(days=max(1, int(recent_days)))
    sides: dict[str, Any] = {}
    sources: set[str] = set()
    for side in ("home", "away"):
        team_id = dongqiudi_ids.get(side)
        source = "dongqiudi"
        row = (
            repository.team_transfers_row(str(team_id), season, source=source)
            if team_id not in (None, "")
            else None
        )
        if row is None:
            team_id = api_ids.get(side)
            source = "api-football"
            row = repository.team_transfers_row(str(team_id), season) if team_id not in (None, "") else None
        if row is None:
            sides[side] = None
            continue
        sources.add(source)
        transfers_in: list[str] = []
        transfers_out: list[str] = []
        for record in row.get("transfers") or []:
            date = str(record.get("date") or "")[:10]
            parsed = parse_timestamp(date) if date else None
            if parsed is None or parsed < window_start:
                continue
            if _same_team_id(record.get("in_team_id"), team_id, source) and record.get("player"):
                name = to_chinese_player_name(str(record["player"]))
                transfers_in.append(f"{name}（{date}，自 {record.get('out_team') or '未知'}）")
            if _same_team_id(record.get("out_team_id"), team_id, source) and record.get("player"):
                name = to_chinese_player_name(str(record["player"]))
                transfers_out.append(f"{name}（{date}，至 {record.get('in_team') or '未知'}）")
        sides[side] = {
            "transfers_in": sorted(set(transfers_in)),
            "transfers_out": sorted(set(transfers_out)),
            "window_days": int(recent_days),
            "source": source,
        }
    if all(value is None for value in sides.values()):
        return
    context["transfers"] = {
        "home": sides.get("home"),
        "away": sides.get("away"),
        "source": "+".join(sorted(sources)),
    }


def _preferred_transfer_targets(
    rows: list[dict[str, Any]],
    repository: Any,
    leagues: tuple[str, ...],
    *,
    current: datetime,
    lookahead_days: int,
) -> tuple[list[dict[str, str | None]], dict[str, int]]:
    horizon = current + timedelta(days=max(1, int(lookahead_days)))
    upcoming = [
        row
        for row in rows
        if str(row.get("league_key") or "") in leagues
        and str(row.get("status") or "").casefold() == "scheduled"
        and (kickoff := parse_timestamp(row.get("kickoff"))) is not None
        and current <= kickoff <= horizon
    ]
    dongqiudi_index: dict[tuple[str, str], str] = {}
    for row in upcoming:
        if not _is_dongqiudi_fixture(row):
            continue
        league = str(row.get("league_key") or "")
        for side in ("home", "away"):
            team = row.get(f"{side}_team") if isinstance(row.get(f"{side}_team"), Mapping) else {}
            team_id = str(team.get("provider_id") or "")
            key = (league, _team_name_key(team.get("name") or team.get("original_name")))
            if team_id and all(key):
                dongqiudi_index[key] = team_id
    api_index = _api_football_identity_index(repository)
    targets: dict[tuple[str, str], dict[str, str | None]] = {}
    fixture_keys: set[str] = set()
    for row in upcoming:
        league = str(row.get("league_key") or "")
        fixture_keys.add(str((row.get("external_ids") or {}).get("dongqiudi") or row.get("id") or ""))
        for side in ("home", "away"):
            team = row.get(f"{side}_team") if isinstance(row.get(f"{side}_team"), Mapping) else {}
            name = str(team.get("name") or team.get("original_name") or "")
            key = (league, _team_name_key(name))
            if not all(key):
                continue
            target = targets.setdefault(
                key,
                {
                    "league_key": league,
                    "team_name": to_chinese_team_name(name),
                    "dongqiudi_id": None,
                    "api_football_id": None,
                },
            )
            target["dongqiudi_id"] = target["dongqiudi_id"] or dongqiudi_index.get(key)
            target["api_football_id"] = target["api_football_id"] or api_index.get(key)
    missing = sum(1 for target in targets.values() if not target["dongqiudi_id"] and not target["api_football_id"])
    usable = [target for target in targets.values() if target["dongqiudi_id"] or target["api_football_id"]]
    return usable, {
        "upcoming_fixture_count": len(fixture_keys),
        "provider_id_missing": missing,
        "identity_resolved": sum(1 for target in usable if target["api_football_id"]),
        "dongqiudi_identity_resolved": sum(1 for target in usable if target["dongqiudi_id"]),
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


def _is_dongqiudi_fixture(fixture: Mapping[str, Any]) -> bool:
    return str(fixture.get("source") or "").casefold() == "dongqiudi" or str(fixture.get("id") or "").startswith("dongqiudi-")


def _dongqiudi_team_ids(repository: Any, fixture: Mapping[str, Any]) -> dict[str, str | None]:
    source = fixture if _is_dongqiudi_fixture(fixture) else None
    match_id = (fixture.get("external_ids") or {}).get("dongqiudi")
    reader = getattr(repository, "fixture", None)
    if source is None and match_id not in (None, "") and callable(reader):
        source = reader(f"dongqiudi-{match_id}")
    result: dict[str, str | None] = {"home": None, "away": None}
    for side in result:
        team = source.get(f"{side}_team") if isinstance(source, Mapping) else None
        if isinstance(team, Mapping) and team.get("provider_id") not in (None, ""):
            result[side] = str(team["provider_id"])
    return result


def _same_team_id(left: Any, right: Any, source: str) -> bool:
    if source != "dongqiudi":
        return str(left or "") == str(right or "")
    return _dongqiudi_public_team_id(left) == _dongqiudi_public_team_id(right)


def _dongqiudi_public_team_id(value: Any) -> str:
    try:
        number = int(str(value or ""))
    except ValueError:
        return str(value or "")
    if 50_000_000 <= number < 60_000_000:
        number -= 50_000_000
    return str(number)


def _league_key(value: Any) -> str:
    normalized = str(value or "").strip().casefold().replace("_", "")
    return {"lal": "laliga", "laliga": "laliga", "epl": "epl", "csl": "csl", "cfacup": "cfacup"}.get(
        normalized,
        normalized,
    )


def _team_name_key(value: Any) -> str:
    return "".join(to_chinese_team_name(str(value or "")).split()).casefold()


def _start_sync_run(
    repository: Any,
    target_state: Mapping[str, int],
    *,
    provider: str = "api-football",
) -> dict[str, Any]:
    run = {
        "run_id": f"sync:{uuid.uuid4()}",
        "provider": provider,
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
