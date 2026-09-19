"""Weather evidence: forecast ingestion onto upcoming fixtures and merge.

One sync refreshes scheduled fixtures inside the forecast horizon: the
venue location is resolved (Photon, cached per venue in ``venue_locations``)
and the Open-Meteo kickoff-hour forecast is written to the fixture payload
as ``weather``. ``attach_weather`` exposes the stored payload to the
``weather`` evidence slot that the prompt contract already reserves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .fixture_matching import canonical
from .team_names import to_chinese_team_name
from .weather_provider import WeatherProvider

WEATHER_LEAGUES: tuple[str, ...] = ("epl", "laliga", "csl", "cfa_cup")
_UNSET_VENUES = {"", "待定", "TBD", "Unknown"}


async def sync_weather(
    repository: Any,
    provider: WeatherProvider,
    *,
    leagues: tuple[str, ...] = WEATHER_LEAGUES,
    horizon_days: int = 7,
    limit: int = 30,
    stale_after_hours: int = 6,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh forecasts for up to ``limit`` upcoming fixtures per run."""

    current = now or datetime.now(UTC)
    horizon_end = current + timedelta(days=max(1, int(horizon_days)))
    stale_after = timedelta(hours=max(1, int(stale_after_hours)))
    rows = repository.list_fixtures() or []
    team_venues = _team_home_venues(rows)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("league_key") or "") not in leagues:
            continue
        if row.get("status") != "scheduled":
            continue
        kickoff = _parse_iso(row.get("kickoff"))
        if kickoff is None or not (current <= kickoff <= horizon_end):
            continue
        candidates.append(row)
    candidates.sort(key=lambda row: str(row.get("kickoff") or ""))
    enriched = 0
    skipped_fresh = 0
    unresolved = 0
    now_iso = current.replace(microsecond=0).isoformat()
    for row in candidates:
        if enriched >= max(0, int(limit)):
            break
        weather = row.get("weather") if isinstance(row.get("weather"), dict) else None
        if weather and _fresh(weather.get("captured_at"), current, stale_after):
            skipped_fresh += 1
            continue
        coords = await _resolve_location(repository, provider, row, team_venues)
        if coords is None:
            unresolved += 1
            continue
        try:
            forecast = await provider.forecast(coords[0], coords[1], str(row.get("kickoff") or ""))
        except Exception:
            continue
        if not forecast:
            continue
        merged = dict(row)
        merged["weather"] = {
            **forecast,
            "venue": str(row.get("venue") or ""),
            "source": "open-meteo",
            "captured_at": now_iso,
            "available_at": now_iso,
        }
        repository.upsert_fixture(merged, synced_at=now_iso)
        enriched += 1
    return {
        "status": "completed",
        "candidates": len(candidates),
        "enriched": enriched,
        "skipped_fresh": skipped_fresh,
        "unresolved_location": unresolved,
        "item_count": enriched,
    }


def attach_weather(fixture: Mapping, context: dict[str, Any]) -> None:
    """Expose the stored kickoff forecast to the weather evidence slot."""

    weather = fixture.get("weather") if isinstance(fixture.get("weather"), dict) else None
    if not weather:
        return
    context["weather"] = {
        "source": weather.get("source") or "open-meteo",
        "captured_at": weather.get("captured_at"),
        "available_at": weather.get("available_at"),
        "venue": weather.get("venue"),
        "kickoff": weather.get("kickoff"),
        "temperature_c": weather.get("temperature_c"),
        "wind_kmh": weather.get("wind_kmh"),
        "precipitation_mm": weather.get("precipitation_mm"),
        "condition": weather.get("condition"),
    }


async def _resolve_location(
    repository: Any,
    provider: WeatherProvider,
    row: dict[str, Any],
    team_venues: dict[str, str] | None = None,
) -> tuple[float, float] | None:
    queries = _location_queries(row, team_venues)
    if not queries:
        return None
    for query in queries:
        cached = repository.venue_location(query)
        if cached is not None:
            return cached
        coords = await provider.geocode(query)
        if coords is not None:
            repository.save_venue_location(query, coords[0], coords[1])
            return coords
    return None


def _team_home_venues(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Learn each home team's usual venue from finished matches.

    Upcoming fixtures often carry ``待定`` venues until near kickoff; the
    last finished home match's venue is a reliable stand-in.
    """

    venues: dict[str, tuple[str, str]] = {}
    for row in rows or []:
        if row.get("status") != "finished":
            continue
        venue_name = str(row.get("venue") or "").strip()
        if not venue_name or venue_name in _UNSET_VENUES:
            continue
        kickoff = str(row.get("kickoff") or "")
        home_key = canonical(str(((row.get("home_team") or {}).get("name")) or ""), to_chinese_team_name)
        if not home_key:
            continue
        previous = venues.get(home_key)
        if previous is None or kickoff > previous[1]:
            venues[home_key] = (venue_name, kickoff)
    return {team: venue for team, (venue, _) in venues.items()}


def _location_queries(row: dict[str, Any], team_venues: dict[str, str] | None = None) -> list[str]:
    """Geocode queries: evidence address, fixture venue, home team's usual venue, team name."""

    queries: list[str] = []
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    venue = evidence.get("venue") if isinstance(evidence.get("venue"), dict) else {}
    city = str(venue.get("city") or "").strip()
    country = str(venue.get("country") or "").strip()
    if city and city not in _UNSET_VENUES:
        queries.append(f"{city} {country}".strip())
    venue_name = str(row.get("venue") or "").strip()
    if venue_name and venue_name not in _UNSET_VENUES:
        queries.append(venue_name)
    home = row.get("home_team") if isinstance(row.get("home_team"), dict) else {}
    home_key = canonical(str(home.get("name") or ""), to_chinese_team_name)
    learned = (team_venues or {}).get(home_key)
    if learned:
        queries.append(learned)
    for field in ("original_name", "name"):
        team_name = str(home.get(field) or "").strip()
        if team_name and team_name not in _UNSET_VENUES:
            queries.append(team_name)
    return queries


def _fresh(captured_at: Any, current: datetime, stale_after: timedelta) -> bool:
    captured = _parse_iso(captured_at)
    return captured is not None and current - captured < stale_after


def _parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None
