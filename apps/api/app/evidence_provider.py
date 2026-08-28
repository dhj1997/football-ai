"""Fetch single-fixture pre-match evidence from API-Football."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from .team_names import to_chinese_player_name, to_chinese_team_name


class ApiFootballEvidenceProvider:
    """Fetch evidence for one fixture without requesting a whole season."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        schedule_api_key: str = "123",
        schedule_base_url: str = "https://www.thesportsdb.com/api/v1/json",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.schedule_api_key = schedule_api_key
        self.schedule_base_url = schedule_base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        """Return whether the API-Football key is available."""

        return bool(self.api_key)

    @property
    def public_configured(self) -> bool:
        return bool(self.schedule_api_key and self.schedule_base_url)

    async def fetch_public(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Build honest partial evidence from cached team data and recent public results."""

        if not self.public_configured:
            raise RuntimeError("TheSportsDB public evidence is not configured")
        recent_events = await self._get_recent_events(fixture)
        free_team_data = fixture.get("free_team_data") or {}
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        return {
            "recent_form": _recent_form(
                {},
                recent_events,
                (fixture.get("home_team") or {}).get("provider_id"),
                (fixture.get("away_team") or {}).get("provider_id"),
            ),
            "head_to_head": [],
            "availability": {
                "home_missing": 0,
                "away_missing": 0,
                "notes": [],
                "players": [],
                "updated_at": None,
            },
            "lineup": {
                "confirmed": False,
                "home_strength": 0.88,
                "away_strength": 0.86,
                "home_formation": None,
                "away_formation": None,
                "home_players": [],
                "away_players": [],
                "updated_at": None,
            },
            "teams": {
                side: ((free_team_data.get(side) or {}).get("profile") or {})
                for side in ("home", "away")
            },
            "squads": {
                side: ((free_team_data.get(side) or {}).get("squad") or [])
                for side in ("home", "away")
            },
            "odds": None,
            "source": "thesportsdb-partial",
            "synced_at": updated_at,
        }

    async def fetch(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Fetch form, head-to-head, availability, lineup, and odds for a fixture."""

        if not self.configured:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        external_id = (fixture.get("external_ids") or {}).get("api_football")
        if not external_id:
            raise RuntimeError("当前比赛没有 API-Football fixture ID，先同步赛程")

        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key},
            timeout=20,
        ) as client:
            details = await self._get(client, "/fixtures", {"id": external_id})
            item = (details.get("response") or [None])[0]
            if not item:
                raise RuntimeError("API-Football 没有返回这场比赛")
            home_id = item["teams"]["home"]["id"]
            away_id = item["teams"]["away"]["id"]
            predictions, h2h, injuries, lineups, odds, home_squad, away_squad = await self._get_many(
                client,
                external_id,
                home_id,
                away_id,
            )
        recent_events, public_data = await asyncio.gather(
            self._get_recent_events(fixture),
            self._get_public_team_data(fixture),
        )

        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        return {
            "recent_form": _recent_form(
                predictions,
                recent_events,
                (fixture.get("home_team") or {}).get("provider_id"),
                (fixture.get("away_team") or {}).get("provider_id"),
            ),
            "head_to_head": _head_to_head(h2h),
            "availability": _availability(injuries, home_id, away_id, updated_at),
            "lineup": _lineup(lineups, home_id, away_id, updated_at),
            "teams": {
                "home": _team_profile(public_data["home"], item["teams"]["home"], fixture["home_team"]),
                "away": _team_profile(public_data["away"], item["teams"]["away"], fixture["away_team"]),
            },
            "squads": {
                "home": _squad(home_squad, public_data["home"].get("players") or []),
                "away": _squad(away_squad, public_data["away"].get("players") or []),
            },
            "odds": _odds(odds, updated_at),
            "source": "api-football-single-fixture",
            "synced_at": updated_at,
        }

    async def _get_many(
        self,
        client: httpx.AsyncClient,
        fixture_id: int,
        home_id: int,
        away_id: int,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Fetch the independent evidence endpoints concurrently."""

        requests = (
            self._get(client, "/predictions", {"fixture": fixture_id}),
            self._get(client, "/fixtures/headtohead", {"h2h": f"{home_id}-{away_id}"}),
            self._get(client, "/injuries", {"fixture": fixture_id}),
            self._get(client, "/fixtures/lineups", {"fixture": fixture_id}),
            self._get(client, "/odds", {"fixture": fixture_id}),
            self._get(client, "/players/squads", {"team": home_id}),
            self._get(client, "/players/squads", {"team": away_id}),
        )
        return tuple(await asyncio.gather(*requests))  # type: ignore[return-value]

    async def _get_public_team_data(self, fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Load team profiles and player aliases from TheSportsDB."""

        team_ids = {
            "home": (fixture.get("home_team") or {}).get("provider_id"),
            "away": (fixture.get("away_team") or {}).get("provider_id"),
        }
        if not self.schedule_api_key or not all(team_ids.values()):
            return {"home": {}, "away": {}}
        async with httpx.AsyncClient(timeout=15) as client:
            requests = tuple(
                request
                for team_id in team_ids.values()
                for request in (
                    client.get(
                        f"{self.schedule_base_url}/{self.schedule_api_key}/lookupteam.php",
                        params={"id": team_id},
                    ),
                    client.get(
                        f"{self.schedule_base_url}/{self.schedule_api_key}/lookup_all_players.php",
                        params={"id": team_id},
                    ),
                )
            )
            responses = await asyncio.gather(*requests, return_exceptions=True)
        result: dict[str, dict[str, Any]] = {}
        for index, side in enumerate(team_ids):
            team_response, players_response = responses[index * 2:index * 2 + 2]
            team_payload = team_response.json() if not isinstance(team_response, Exception) and team_response.status_code == 200 else {}
            players_payload = players_response.json() if not isinstance(players_response, Exception) and players_response.status_code == 200 else {}
            result[side] = {
                "team": (team_payload.get("teams") or [{}])[0],
                "players": players_payload.get("player") or [],
            }
        return result

    async def _get_recent_events(self, fixture: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Fetch each team's latest public match events for a readable form table."""

        team_ids = {
            "home": (fixture.get("home_team") or {}).get("provider_id"),
            "away": (fixture.get("away_team") or {}).get("provider_id"),
        }
        if not self.schedule_api_key or not all(team_ids.values()):
            return {"home": [], "away": []}
        async with httpx.AsyncClient(timeout=15) as client:
            requests = tuple(
                client.get(
                    f"{self.schedule_base_url}/{self.schedule_api_key}/eventslast.php",
                    params={"id": team_id},
                )
                for team_id in team_ids.values()
            )
            responses = await asyncio.gather(*requests, return_exceptions=True)
        result: dict[str, list[dict[str, Any]]] = {}
        for side, response in zip(team_ids, responses):
            if isinstance(response, Exception) or response.status_code != 200:
                result[side] = []
                continue
            payload = response.json()
            result[side] = payload.get("results") or []
        return result

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, object],
    ) -> dict[str, Any]:
        """Request one endpoint and raise on provider-level errors."""

        response = await client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football {path} error: {payload['errors']}")
        return payload

def _recent_form(
    payload: dict[str, Any],
    recent_events: dict[str, list[dict[str, Any]]] | None = None,
    home_team_id: object = None,
    away_team_id: object = None,
) -> dict[str, Any]:
    """Map API-Football's prediction summary into the app's form fields."""

    response = (payload.get("response") or [{}])[0]
    teams = response.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    home_last = home.get("last_5") or {}
    away_last = away.get("last_5") or {}
    recent_events = recent_events or {}
    home_matches = _recent_matches(recent_events.get("home") or [], home_team_id)
    away_matches = _recent_matches(recent_events.get("away") or [], away_team_id)
    return {
        "home": home_matches or ([home_last["form"]] if home_last.get("form") else []),
        "away": away_matches or ([away_last["form"]] if away_last.get("form") else []),
        "home_points_per_game": _points_per_game(home.get("league")) or _match_points_per_game(home_matches),
        "away_points_per_game": _points_per_game(away.get("league")) or _match_points_per_game(away_matches),
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def _recent_matches(events: list[dict[str, Any]], team_id: object) -> list[dict[str, Any]]:
    """Map public event results into the five-match form rows used by the UI."""

    matches: list[dict[str, Any]] = []
    for event in events[:5]:
        home_score = _optional_score(event.get("intHomeScore"))
        away_score = _optional_score(event.get("intAwayScore"))
        if home_score is None or away_score is None:
            continue
        home_id = str(event.get("idHomeTeam"))
        is_home = team_id is not None and home_id == str(team_id)
        team_score, opponent_score = (home_score, away_score) if is_home else (away_score, home_score)
        result = "W" if team_score > opponent_score else "D" if team_score == opponent_score else "L"
        matches.append(
            {
                "date": event.get("dateEvent") or "",
                "home": to_chinese_team_name(event.get("strHomeTeam") or "未知球队"),
                "away": to_chinese_team_name(event.get("strAwayTeam") or "未知球队"),
                "score": f"{home_score} - {away_score}",
                "result": result,
                "team_is_home": is_home,
            }
        )
    return matches


def _optional_score(value: object) -> int | None:
    """Convert a provider score without treating an empty value as zero."""

    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _match_points_per_game(matches: list[dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    points = sum(
        3 if item.get("result") == "W" else 1 if item.get("result") == "D" else 0
        for item in matches
    )
    return round(points / len(matches), 2)


def _points_per_game(league: Any) -> float:
    """Calculate points per game from the provider's league summary."""

    fixtures = (league or {}).get("fixtures") or {}
    played = ((fixtures.get("played") or {}).get("total")) or 0
    wins = ((fixtures.get("wins") or {}).get("total")) or 0
    draws = ((fixtures.get("draws") or {}).get("total")) or 0
    return round((3 * wins + draws) / played, 2) if played else 0.0


def _head_to_head(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Map recent head-to-head matches."""

    result = []
    for item in (payload.get("response") or [])[:5]:
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        result.append(
            {
                "date": str(fixture.get("date", ""))[:10],
                "home": to_chinese_team_name((teams.get("home") or {}).get("name", "")),
                "away": to_chinese_team_name((teams.get("away") or {}).get("name", "")),
                "score": f"{goals.get('home', '-')} - {goals.get('away', '-')}",
            }
        )
    return result


def _availability(payload: dict[str, Any], home_id: int, away_id: int, updated_at: str) -> dict[str, Any]:
    """Map fixture-specific injuries and suspensions."""

    home_missing = 0
    away_missing = 0
    notes: list[str] = []
    players: list[dict[str, Any]] = []
    seen: set[tuple[object, str, str]] = set()
    for item in payload.get("response") or []:
        team_id = (item.get("team") or {}).get("id")
        provider_player = item.get("player") or {}
        player = provider_player.get("name") or "未知球员"
        reason = provider_player.get("reason") or "缺阵"
        key = (team_id, player, reason)
        if key in seen:
            continue
        seen.add(key)
        if team_id == home_id:
            home_missing += 1
            team = "home"
        elif team_id == away_id:
            away_missing += 1
            team = "away"
        else:
            team = "unknown"
        localized_player = to_chinese_player_name(player)
        players.append(
            {
                "team": team,
                "provider_player_id": str(provider_player["id"]) if provider_player.get("id") is not None else None,
                "name": localized_player,
                "original_name": player,
                "reason": reason,
            }
        )
        notes.append(f"{localized_player}：{reason}")
    return {
        "home_missing": home_missing,
        "away_missing": away_missing,
        "notes": notes[:12],
        "players": players[:24],
        "updated_at": updated_at,
    }


def _lineup(payload: dict[str, Any], home_id: int, away_id: int, updated_at: str) -> dict[str, Any]:
    """Map confirmed lineups when the provider has published them."""

    rows = payload.get("response") or []
    confirmed = len(rows) >= 2
    home_players: list[dict[str, Any]] = []
    away_players: list[dict[str, Any]] = []
    formations: dict[str, str | None] = {"home": None, "away": None}
    for row in rows:
        team_id = (row.get("team") or {}).get("id")
        side = "home" if team_id == home_id else "away" if team_id == away_id else None
        if not side:
            continue
        formations[side] = (row.get("formation") or None)
        players = []
        for group, starter in (("startXI", True), ("substitutes", False)):
            for item in row.get(group) or []:
                player = item.get("player") or {}
                players.append(
                    {
                        "provider_player_id": str(player["id"]) if player.get("id") is not None else None,
                        "name": to_chinese_player_name(player.get("name") or "未知球员"),
                        "original_name": player.get("name") or "未知球员",
                        "number": player.get("number"),
                        "position": player.get("pos") or "",
                        "starter": starter,
                    }
                )
        if side == "home":
            home_players = players
        else:
            away_players = players
    return {
        "confirmed": confirmed,
        "home_strength": 1.0 if confirmed else 0.88,
        "away_strength": 1.0 if confirmed else 0.86,
        "home_formation": formations["home"],
        "away_formation": formations["away"],
        "home_players": home_players,
        "away_players": away_players,
        "updated_at": updated_at if confirmed else None,
    }


def _team_profile(
    public_data: dict[str, Any],
    api_team: dict[str, Any],
    fixture_team: dict[str, Any],
) -> dict[str, Any]:
    """Merge stable team identity fields from both providers."""

    public_team = public_data.get("team") or {}
    venue = api_team.get("venue") or {}
    return {
        "name": to_chinese_team_name(api_team.get("name") or fixture_team.get("name") or "未知球队"),
        "original_name": api_team.get("name") or fixture_team.get("name") or "未知球队",
        "logo": api_team.get("logo") or public_team.get("strBadge"),
        "country": api_team.get("country") or public_team.get("strCountry"),
        "founded": api_team.get("founded") or _optional_int(public_team.get("intFormedYear")),
        "venue": venue.get("name") or public_team.get("strStadium") or fixture_team.get("name"),
        "capacity": venue.get("capacity") or _optional_int(public_team.get("intStadiumCapacity")),
        "city": venue.get("city") or public_team.get("strLocation"),
        "website": public_team.get("strWebsite") or None,
    }


def _squad(payload: dict[str, Any], public_players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map the full current squad and preserve honest value provenance."""

    rows = (payload.get("response") or [{}])[0].get("players") if payload.get("response") else []
    aliases = {
        str(player.get("idAPIfootball")): player
        for player in public_players
        if player.get("idAPIfootball")
    }
    result: list[dict[str, Any]] = []
    for player in rows or []:
        public_player = aliases.get(str(player.get("id"))) or {}
        original_name = player.get("name") or public_player.get("strPlayer") or "未知球员"
        result.append(
            {
                "id": player.get("id"),
                "provider_player_id": str(player["id"]) if player.get("id") is not None else None,
                "name": to_chinese_player_name(public_player.get("strPlayer") or original_name),
                "original_name": original_name,
                "age": player.get("age"),
                "number": player.get("number"),
                "position": player.get("position") or public_player.get("strPosition") or "未知位置",
                "nationality": player.get("nationality") or public_player.get("strNationality"),
                "photo": player.get("photo") or public_player.get("strCutout"),
                "market_value": None,
                "market_value_currency": "EUR",
                "market_value_source": None,
                "transfermarkt_id": public_player.get("idTransferMkt"),
            }
        )
    return result


def _optional_int(value: object) -> int | None:
    """Convert an optional provider integer."""

    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _odds(payload: dict[str, Any], updated_at: str) -> dict[str, Any] | None:
    """Extract 1X2 and the first Asian handicap market."""

    responses = payload.get("response") or []
    bookmakers = (responses[0].get("bookmakers") or []) if responses else []
    if not bookmakers:
        return None
    bookmaker = bookmakers[0]
    match_winner: dict[str, float] = {}
    handicap: float | None = None
    handicap_home_odd: float | None = None
    handicap_away_odd: float | None = None
    away_handicap_values: list[tuple[float, float]] = []
    for bet in bookmaker.get("bets") or []:
        if bet.get("id") == 1:
            for value in bet.get("values") or []:
                try:
                    match_winner[value["value"]] = float(value["odd"])
                except (KeyError, TypeError, ValueError):
                    continue
        if bet.get("id") == 4:
            for value in bet.get("values") or []:
                raw_value = str(value.get("value", ""))
                side, _, raw_line = raw_value.partition(" ")
                if side not in {"Home", "Away"}:
                    continue
                try:
                    line = float(raw_line)
                    odd = float(value["odd"])
                except (KeyError, TypeError, ValueError):
                    continue
                if side == "Home" and handicap is None:
                    handicap = line
                    handicap_home_odd = odd
                elif side == "Away":
                    away_handicap_values.append((line, odd))
    if handicap is not None:
        for away_line, away_odd in away_handicap_values:
            if abs(away_line - handicap) < 1e-9 or abs(away_line + handicap) < 1e-9:
                handicap_away_odd = away_odd
                break
    if not {"Home", "Draw", "Away"}.issubset(match_winner):
        return None
    return {
        "bookmaker": bookmaker.get("name") or "API-Football",
        "home": match_winner["Home"],
        "draw": match_winner["Draw"],
        "away": match_winner["Away"],
        "asian_handicap": handicap,
        "asian_handicap_home_odd": handicap_home_odd,
        "asian_handicap_away_odd": handicap_away_odd,
        "updated_at": updated_at,
        "is_demo": False,
    }
