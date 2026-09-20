"""Bounded Dongqiudi player-value refresh for upcoming fixture squads."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from .player_identity import localize_player_record
from .player_value_provider import SUPPORTED_LEAGUES
from .team_names import to_chinese_team_name


async def sync_player_values(
    repository: Any,
    provider: Any,
    *,
    limit: int = 120,
    lookahead_days: int = 14,
    stale_after_days: int = 14,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh stale players found in cached squads for upcoming fixtures."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    targets, missing_squads = _upcoming_players(
        repository,
        current=current,
        lookahead_days=max(1, int(lookahead_days)),
    )
    existing = {
        item["canonical_player_id"]: item
        for item in repository.player_values(list(targets))
    }
    stale_after = timedelta(days=max(1, int(stale_after_days)))
    attempted = saved = missing = failed = skipped_fresh = 0
    values: list[dict[str, Any]] = []
    errors: list[str] = []
    request_limit = max(1, int(limit))
    interval = max(0.0, float(getattr(provider, "request_interval_seconds", 0.0)))

    for player in targets.values():
        cached = existing.get(player["canonical_player_id"])
        captured_at = _as_utc((cached or {}).get("cached_at"))
        if captured_at is not None and current - captured_at < stale_after:
            skipped_fresh += 1
            continue
        if attempted >= request_limit:
            break
        attempted += 1
        try:
            value = await provider.fetch_player_value(player)
        except Exception as error:
            failed += 1
            player_id = str(player.get("provider_player_id") or "unknown")
            errors.append(f"player {player_id}: {type(error).__name__}: {str(error)[:160]}")
            if _stop_requests(error):
                break
        else:
            if value is None:
                missing += 1
            else:
                values.append(value)
                saved += 1
        if interval and attempted < request_limit:
            await asyncio.sleep(interval)

    if values:
        repository.save_player_values(values)
    status = (
        "zero_targets"
        if not targets
        else "failed"
        if failed and not saved
        else "partial"
        if failed
        else "completed"
    )
    return {
        "status": status,
        "source": getattr(provider, "source_name", "dongqiudi"),
        "players_targeted": len(targets),
        "players_attempted": attempted,
        "players_saved": saved,
        "players_missing": missing,
        "players_failed": failed,
        "players_skipped_fresh": skipped_fresh,
        "squads_missing": missing_squads,
        "errors": errors[:20],
        "item_count": saved,
    }


def _upcoming_players(
    repository: Any,
    *,
    current: datetime,
    lookahead_days: int,
) -> tuple[dict[str, dict[str, Any]], int]:
    horizon = current + timedelta(days=lookahead_days)
    fixture_reader = getattr(repository, "fixture", None)
    targets: dict[str, dict[str, Any]] = {}
    missing_squads = 0
    fixtures = repository.list_fixtures()
    team_id_index = _dongqiudi_team_id_index(fixtures)
    for fixture in fixtures:
        league_key = str(fixture.get("league_key") or "")
        kickoff = _as_utc(fixture.get("kickoff"))
        if (
            league_key not in SUPPORTED_LEAGUES
            or fixture.get("status") != "scheduled"
            or kickoff is None
            or not current <= kickoff <= horizon
        ):
            continue
        free_team_data = fixture.get("free_team_data") or {}
        twin = _dongqiudi_twin(repository, fixture, fixture_reader)
        for side in ("home", "away"):
            squad = list(((free_team_data.get(side) or {}).get("squad") or []))
            if not squad and twin:
                team_id = str(((twin.get(f"{side}_team") or {}).get("provider_id") or ""))
            else:
                team_id = ""
            if not squad and not team_id:
                team_name = (fixture.get(f"{side}_team") or {}).get("name")
                team_id = team_id_index.get((league_key, _team_name_key(team_name)), "")
            if not squad and team_id:
                snapshot = repository.team_snapshot(league_key, team_id) if team_id else None
                squad = list((snapshot or {}).get("roster") or [])
            if not squad:
                missing_squads += 1
                continue
            for raw in squad:
                player = localize_player_record(deepcopy(raw), "dongqiudi")
                provider_id = str(player.get("provider_player_id") or "")
                canonical_id = str(player.get("canonical_player_id") or "")
                if provider_id and canonical_id:
                    targets.setdefault(canonical_id, player)
    return targets, missing_squads


def _dongqiudi_team_id_index(fixtures: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    candidates: dict[tuple[str, str], set[str]] = {}
    for fixture in fixtures:
        if not str(fixture.get("id") or "").startswith("dongqiudi-"):
            continue
        league_key = str(fixture.get("league_key") or "")
        for side in ("home", "away"):
            team = fixture.get(f"{side}_team") or {}
            team_id = str(team.get("provider_id") or "")
            name_key = _team_name_key(team.get("name"))
            if league_key and team_id and name_key:
                candidates.setdefault((league_key, name_key), set()).add(team_id)
    return {
        key: next(iter(team_ids))
        for key, team_ids in candidates.items()
        if len(team_ids) == 1
    }


def _team_name_key(value: Any) -> str:
    return "".join(to_chinese_team_name(str(value or "")).split()).casefold()


def _dongqiudi_twin(repository: Any, fixture: dict[str, Any], fixture_reader: Any) -> dict[str, Any] | None:
    match_id = (fixture.get("external_ids") or {}).get("dongqiudi")
    if not match_id or not callable(fixture_reader):
        return None
    return fixture_reader(f"dongqiudi-{match_id}")


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _stop_requests(error: Exception) -> bool:
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    error_name = type(error).__name__.casefold()
    return bool(
        status_code in {403, 429}
        or (isinstance(status_code, int) and status_code >= 500)
        or "timeout" in error_name
        or "connect" in error_name
        or "transport" in error_name
    )
