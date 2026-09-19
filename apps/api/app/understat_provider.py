"""Understat.com per-match xG and xPoints ingestion for finished fixtures.

Free JSON endpoint (``getLeagueData``) provides every match of a league
season with both sides' xG, plus each team's per-match xPoints. One sync
enriches already-finished canonical fixtures with ``xg`` / ``xpoints``
home/away pairs; ``available_at`` mirrors the result-availability policy in
``recent_form`` so the point-in-time contract of Feature Engine v2 holds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

import httpx

from .fixture_matching import find_fixture_rows, kickoff_utc
from .recent_form import result_available_at

UNDERSTAT_LEAGUE_MAP: dict[str, str] = {"epl": "EPL", "laliga": "La_Liga"}
BASE_URL = "https://understat.com/getLeagueData"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# getLeagueData 是 AJAX-only 端点，缺少该头会返回 404。
FETCH_HEADERS = {"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"}


class UnderstatProviderError(ValueError):
    """Raised when the Understat league payload cannot be parsed."""


async def fetch_league_data(league_key: str, season_year: int) -> dict[str, Any] | None:
    """Fetch one league-season payload; None when the season is unavailable."""

    slug = UNDERSTAT_LEAGUE_MAP[league_key]
    url = f"{BASE_URL}/{slug}/{season_year}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers=FETCH_HEADERS)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def parse_league_data(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten finished matches into normalized rows with per-side xG/xPoints."""

    if not isinstance(payload, Mapping):
        raise UnderstatProviderError("Understat payload must be an object")
    xpts_by_team_date = _xpts_index(payload.get("teams"))
    matches: list[dict[str, Any]] = []
    for match in payload.get("dates") or []:
        if not isinstance(match, Mapping) or not match.get("isResult"):
            continue
        xg = match.get("xG") if isinstance(match.get("xG"), Mapping) else {}
        goals = match.get("goals") if isinstance(match.get("goals"), Mapping) else {}
        home_xg = _float(xg.get("h"))
        away_xg = _float(xg.get("a"))
        kickoff = kickoff_utc(match.get("datetime"))
        if home_xg is None or away_xg is None or kickoff is None:
            continue
        home = match.get("h") if isinstance(match.get("h"), Mapping) else {}
        away = match.get("a") if isinstance(match.get("a"), Mapping) else {}
        home_id = str(home.get("id") or "")
        away_id = str(away.get("id") or "")
        date_key = kickoff.date().isoformat()
        matches.append(
            {
                "understat_id": str(match.get("id") or ""),
                "kickoff": kickoff.isoformat(),
                "date": date_key,
                "home_id": home_id,
                "home_title": str(home.get("title") or ""),
                "away_id": away_id,
                "away_title": str(away.get("title") or ""),
                "home_goals": _int(goals.get("h")),
                "away_goals": _int(goals.get("a")),
                "home_xg": home_xg,
                "away_xg": away_xg,
                "home_xpts": xpts_by_team_date.get((home_id, date_key)),
                "away_xpts": xpts_by_team_date.get((away_id, date_key)),
            }
        )
    return matches


def sync_understat_xg(
    repository: Any,
    payload: Mapping[str, Any],
    league_key: str,
    *,
    localize: Any = None,
) -> dict[str, Any]:
    """Enrich finished league fixtures with Understat xG/xPoints (idempotent)."""

    if league_key not in UNDERSTAT_LEAGUE_MAP:
        raise UnderstatProviderError(f"Unsupported league: {league_key}")
    matches = parse_league_data(payload)
    localize = localize or _identity
    rows = repository.list_fixtures(league_key=league_key) or []
    matched = 0
    xg_enriched = 0
    xpoints_enriched = 0
    unmatched_titles: set[str] = set()
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for match in matches:
        fixtures = _find_fixtures(rows, match, localize)
        if not fixtures:
            unmatched_titles.update(title for title in (match["home_title"], match["away_title"]) if title)
            continue
        matched += len(fixtures)
        available_at = _xg_available_at(fixtures[0], match["kickoff"])
        for fixture in fixtures:
            merged = dict(fixture)
            merged["xg"] = {
                "home": match["home_xg"],
                "away": match["away_xg"],
                "source": "understat",
                "available_at": available_at,
            }
            xg_enriched += 1
            if match["home_xpts"] is not None and match["away_xpts"] is not None:
                merged["xpoints"] = {
                    "home": match["home_xpts"],
                    "away": match["away_xpts"],
                    "source": "understat",
                    "available_at": available_at,
                }
                xpoints_enriched += 1
            repository.upsert_fixture(merged, synced_at=now)
    return {
        "status": "completed",
        "league": league_key,
        "source_matches": len(matches),
        "fixtures_matched": matched,
        "xg_enriched": xg_enriched,
        "xpoints_enriched": xpoints_enriched,
        "unmatched_titles": sorted(unmatched_titles),
        "item_count": xg_enriched,
    }


def _xpts_index(teams: Any) -> dict[tuple[str, str], float]:
    """Index each team's per-match xPoints by (team id, UTC date)."""

    index: dict[tuple[str, str], float] = {}
    if not isinstance(teams, Mapping):
        return index
    for team in teams.values():
        if not isinstance(team, Mapping):
            continue
        team_id = str(team.get("id") or "")
        for row in team.get("history") or []:
            if not isinstance(row, Mapping):
                continue
            value = _float(row.get("xpts"))
            date = str(row.get("date") or "")
            if value is None or len(date) < 10:
                continue
            index[(team_id, date[:10])] = value
    return index


def _find_fixtures(
    rows: list[dict[str, Any]],
    match: Mapping[str, Any],
    localize: Any,
) -> list[dict[str, Any]]:
    """Match one Understat match to candidate fixtures by date window and names."""

    return find_fixture_rows(
        rows,
        kickoff=match["kickoff"],
        home_title=match["home_title"],
        away_title=match["away_title"],
        localize=localize,
        home_goals=match["home_goals"],
        away_goals=match["away_goals"],
    )


def _xg_available_at(fixture: Mapping[str, Any], kickoff: str) -> str | None:
    """xG is public at result time; fall back to kickoff + 3h like results do."""

    known_at = result_available_at(fixture)
    if known_at is not None:
        return known_at.isoformat()
    parsed = kickoff_utc(kickoff)
    return (parsed + timedelta(hours=3)).isoformat() if parsed else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
