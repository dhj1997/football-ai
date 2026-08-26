"""Fetch fixture evidence from ESPN's public soccer feeds."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from .data import CHINA_TZ
from .league_provider import EspnLeagueProvider
from .team_names import to_chinese_player_name, to_chinese_team_name
from .team_provider import _map_player


class EspnEvidenceProvider:
    """Map ESPN event summaries and team rosters to the shared evidence contract."""

    LEAGUE_SLUGS = EspnLeagueProvider.LEAGUE_SLUGS

    def __init__(self, base_url: str, timeout_seconds: float = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def fetch(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Fetch a summary and best-effort team rosters for one fixture."""

        if not self.configured:
            raise RuntimeError("ESPN evidence provider is not configured")
        league_key = str(fixture.get("league_key") or "")
        slug = self.LEAGUE_SLUGS.get(league_key)
        if not slug:
            raise RuntimeError(f"ESPN does not support league {league_key}")
        async with self._client() as client:
            event = await self._find_event(client, fixture, slug)
            event_id = str(event.get("id") or "")
            if not event_id:
                raise RuntimeError("ESPN event has no ID")
            summary = await self._get(
                client,
                f"/apis/site/v2/sports/soccer/{slug}/summary",
                {"event": event_id},
            )
            header = summary.get("header") or {}
            competition = (header.get("competitions") or [{}])[0]
            competitors = competition.get("competitors") or []
            home = next((item for item in competitors if item.get("homeAway") == "home"), {})
            away = next((item for item in competitors if item.get("homeAway") == "away"), {})
            home_id = str(home.get("id") or (home.get("team") or {}).get("id") or "")
            away_id = str(away.get("id") or (away.get("team") or {}).get("id") or "")
            roster_results = await asyncio.gather(
                self._optional_get(client, f"/apis/site/v2/sports/soccer/{slug}/teams/{home_id}/roster") if home_id else _empty_result(),
                self._optional_get(client, f"/apis/site/v2/sports/soccer/{slug}/teams/{away_id}/roster") if away_id else _empty_result(),
            )
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        home_roster, away_roster = roster_results
        context = {
            "recent_form": _recent_form(summary.get("lastFiveGames") or [], home_id, away_id, updated_at),
            "head_to_head": _head_to_head(summary.get("seasonseries") or []),
            "availability": _availability(home_roster[0], away_roster[0]),
            "lineup": _lineup(summary.get("rosters") or [], home_id, away_id, updated_at),
            "teams": {
                "home": _team_profile(home_roster[0].get("team") or home.get("team") or {}, fixture.get("home_team") or {}),
                "away": _team_profile(away_roster[0].get("team") or away.get("team") or {}, fixture.get("away_team") or {}),
            },
            "squads": {
                "home": _squad(home_roster[0]),
                "away": _squad(away_roster[0]),
            },
            "odds": _odds(summary.get("odds") or [], updated_at),
            "source": "espn-evidence",
            "synced_at": updated_at,
            "espn_event_id": event_id,
        }
        failures = [
            {"provider": "espn", "error": f"{side}_roster: {error}"}
            for side, (_, error) in zip(("home", "away"), roster_results, strict=True)
            if error
        ]
        if failures:
            context["provider_failures"] = failures
        return context

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"User-Agent": "football-ai/0.1 (+espn-evidence)"},
            timeout=self.timeout_seconds,
        )

    async def _find_event(self, client: httpx.AsyncClient, fixture: dict[str, Any], slug: str) -> dict[str, Any]:
        external_id = (fixture.get("external_ids") or {}).get("espn") or (
            (fixture.get("evidence") or {}).get("espn_event_id")
        )
        if external_id:
            return {"id": str(external_id)}
        dates: list[str] = []
        kickoff = str(fixture.get("kickoff") or "")
        try:
            dates.append(datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(UTC).date().strftime("%Y%m%d"))
        except ValueError:
            pass
        fixture_date = str(fixture.get("fixture_date") or "").replace("-", "")
        if fixture_date and fixture_date not in dates:
            dates.append(fixture_date)
        for date_value in dates:
            payload = await self._get(
                client,
                f"/apis/site/v2/sports/soccer/{slug}/scoreboard",
                {"dates": date_value},
            )
            for event in payload.get("events") or []:
                if _matches_fixture(event, fixture):
                    return event
        raise RuntimeError("ESPN event was not found for fixture")

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await client.get(path, params=params or {})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("ESPN returned a non-object response")
        if payload.get("error"):
            raise RuntimeError(f"ESPN error: {payload['error']}")
        return payload

    async def _optional_get(self, client: httpx.AsyncClient, path: str) -> tuple[dict[str, Any], str | None]:
        try:
            return await self._get(client, path), None
        except Exception as error:
            return {}, _bounded_error(error)


async def _empty_result() -> tuple[dict[str, Any], str | None]:
    return {}, None


def _matches_fixture(event: dict[str, Any], fixture: dict[str, Any]) -> bool:
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((item.get("team") or {} for item in competitors if item.get("homeAway") == "home"), {})
    away = next((item.get("team") or {} for item in competitors if item.get("homeAway") == "away"), {})
    fixture_home = fixture.get("home_team") or {}
    fixture_away = fixture.get("away_team") or {}
    return _team_matches(home, fixture_home) and _team_matches(away, fixture_away) or (
        _team_matches(home, fixture_away) and _team_matches(away, fixture_home)
    )


def _team_matches(provider_team: dict[str, Any], fixture_team: dict[str, Any]) -> bool:
    provider_names = [provider_team.get("displayName"), provider_team.get("name"), provider_team.get("shortDisplayName")]
    fixture_names = [fixture_team.get("name"), fixture_team.get("original_name"), fixture_team.get("short_name")]
    normalized = [_normalize(value) for value in provider_names if value]
    targets = [_normalize(value) for value in fixture_names if value]
    return any(item == target or item in target or target in item for item in normalized for target in targets)


def _normalize(value: object) -> str:
    return "".join(char for char in str(value).lower() if char.isalnum())


def _recent_form(blocks: list[dict[str, Any]], home_id: str, away_id: str, updated_at: str) -> dict[str, Any]:
    mapped: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for block in blocks:
        team_id = str((block.get("team") or {}).get("id") or "")
        side = "home" if team_id == home_id else "away" if team_id == away_id else None
        if not side:
            continue
        for event in (block.get("events") or [])[:5]:
            home_score = _int(event.get("homeTeamScore"))
            away_score = _int(event.get("awayTeamScore"))
            if home_score is None or away_score is None:
                continue
            team_is_home = str(event.get("homeTeamId")) == team_id
            result = event.get("gameResult")
            if result not in {"W", "D", "L"}:
                team_score, opponent_score = (home_score, away_score) if team_is_home else (away_score, home_score)
                result = "W" if team_score > opponent_score else "D" if team_score == opponent_score else "L"
            mapped[side].append(
                {
                    "date": _date(event.get("gameDate")),
                    "home": to_chinese_team_name(((event.get("opponent") or {}).get("displayName") if not team_is_home else (block.get("team") or {}).get("displayName")) or "Unknown team"),
                    "away": to_chinese_team_name(((block.get("team") or {}).get("displayName") if not team_is_home else (event.get("opponent") or {}).get("displayName")) or "Unknown team"),
                    "score": f"{home_score} - {away_score}",
                    "result": result,
                    "team_is_home": team_is_home,
                }
            )
    return {
        "home": mapped["home"],
        "away": mapped["away"],
        "home_points_per_game": _ppg(mapped["home"]),
        "away_points_per_game": _ppg(mapped["away"]),
        "updated_at": updated_at,
    }


def _head_to_head(series: list[dict[str, Any]]) -> list[dict[str, str]]:
    events = next((item.get("events") or [] for item in series if item.get("type") == "head-to-head"), [])
    result: list[dict[str, str]] = []
    for event in events[:5]:
        competitors = event.get("competitors") or []
        home = next((item for item in competitors if item.get("homeAway") == "home"), {})
        away = next((item for item in competitors if item.get("homeAway") == "away"), {})
        result.append(
            {
                "date": _date(event.get("date")),
                "home": to_chinese_team_name((home.get("team") or {}).get("displayName") or "Unknown team"),
                "away": to_chinese_team_name((away.get("team") or {}).get("displayName") or "Unknown team"),
                "score": f"{home.get('score', '-')} - {away.get('score', '-')}",
            }
        )
    return result


def _lineup(rows: list[dict[str, Any]], home_id: str, away_id: str, updated_at: str) -> dict[str, Any]:
    mapped: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    formations: dict[str, str | None] = {"home": None, "away": None}
    for row in rows:
        side = row.get("homeAway")
        if side not in mapped:
            continue
        for player_row in row.get("roster") or []:
            athlete = player_row.get("athlete") or {}
            position = player_row.get("position") or {}
            mapped[side].append(
                {
                    "name": to_chinese_player_name(athlete.get("displayName") or athlete.get("fullName") or "Unknown player"),
                    "number": _int(player_row.get("jersey") or athlete.get("jersey")),
                    "position": position.get("abbreviation") or position.get("displayName") or "",
                    "starter": bool(player_row.get("starter")),
                }
            )
    confirmed = bool(mapped["home"] and mapped["away"])
    return {
        "confirmed": confirmed,
        "home_strength": 1.0 if confirmed else 0.88,
        "away_strength": 1.0 if confirmed else 0.86,
        "home_formation": formations["home"],
        "away_formation": formations["away"],
        "home_players": mapped["home"],
        "away_players": mapped["away"],
        "updated_at": updated_at if confirmed else None,
    }


def _availability(home_payload: dict[str, Any], away_payload: dict[str, Any]) -> dict[str, Any]:
    players: list[dict[str, str]] = []
    counts = {"home": 0, "away": 0}
    for side, payload in (("home", home_payload), ("away", away_payload)):
        for athlete in payload.get("athletes") or []:
            for injury in athlete.get("injuries") or []:
                name = to_chinese_player_name(athlete.get("displayName") or athlete.get("fullName") or "Unknown player")
                reason = injury.get("description") or injury.get("status") or injury.get("type") or "Unavailable"
                players.append({"team": side, "name": name, "reason": str(reason)})
                counts[side] += 1
    return {
        "home_missing": counts["home"],
        "away_missing": counts["away"],
        "notes": [],
        "players": players[:24],
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat() if players else None,
    }


def _team_profile(team: dict[str, Any], fixture_team: dict[str, Any]) -> dict[str, Any]:
    logos = team.get("logos") or []
    return {
        "name": to_chinese_team_name(team.get("displayName") or team.get("name") or fixture_team.get("name") or "Unknown team"),
        "original_name": team.get("displayName") or team.get("name") or fixture_team.get("original_name") or fixture_team.get("name") or "Unknown team",
        "logo": team.get("logo") or (logos[0].get("href") if logos else None),
        "country": None,
        "founded": None,
        "venue": fixture_team.get("name"),
        "capacity": None,
        "city": None,
        "website": None,
    }


def _squad(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for athlete in payload.get("athletes") or []:
        try:
            result.append(_map_player(athlete))
        except (AttributeError, TypeError):
            result.append(
                {
                    "id": str(athlete.get("id")) if athlete.get("id") is not None else None,
                    "name": to_chinese_player_name(athlete.get("displayName") or "Unknown player"),
                    "original_name": athlete.get("displayName") or "Unknown player",
                    "age": _int(athlete.get("age")),
                    "number": _int(athlete.get("jersey")),
                    "position": "Unknown",
                    "position_code": None,
                    "position_order": 4,
                    "nationality": athlete.get("citizenship"),
                    "photo": None,
                    "status": None,
                    "injuries": [],
                    "statistics": {},
                }
            )
    return result


def _odds(rows: list[dict[str, Any]], updated_at: str) -> dict[str, Any] | None:
    if not rows:
        return None
    row = rows[0]
    home = _decimal((row.get("homeTeamOdds") or {}).get("moneyLine"))
    draw = _decimal((row.get("drawOdds") or {}).get("moneyLine"))
    away = _decimal((row.get("awayTeamOdds") or {}).get("moneyLine"))
    if home is None or draw is None or away is None:
        return None
    spread = row.get("spread")
    return {
        "bookmaker": ((row.get("provider") or {}).get("name")) or "ESPN",
        "home": home,
        "draw": draw,
        "away": away,
        "asian_handicap": float(spread) if spread not in (None, "") else None,
        "asian_handicap_home_odd": _decimal((row.get("homeTeamOdds") or {}).get("spreadOdds")),
        "asian_handicap_away_odd": _decimal((row.get("awayTeamOdds") or {}).get("spreadOdds")),
        "updated_at": updated_at,
        "is_demo": False,
    }


def _decimal(value: object) -> float | None:
    number = _float(value)
    if number is None:
        return None
    return round(1 + number / 100, 3) if number >= 0 else round(1 + 100 / abs(number), 3)


def _ppg(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return round(sum(3 if row["result"] == "W" else 1 if row["result"] == "D" else 0 for row in rows) / len(rows), 2)


def _date(value: object) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(CHINA_TZ).date().isoformat()
    except ValueError:
        return str(value or "")[:10]


def _int(value: object) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _bounded_error(error: Exception) -> str:
    return str(error)[:240] or error.__class__.__name__
