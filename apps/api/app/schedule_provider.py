"""Free schedule provider backed by TheSportsDB's v1 JSON API."""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx

from .team_names import to_chinese_player_name, to_chinese_team_name


class TheSportsDbProvider:
    """Fetch scheduled football events without requiring a private API key."""

    LEAGUE_IDS = {"epl": 4328, "laliga": 4335, "csl": 4359}
    LEAGUE_NAMES = {"epl": "英超", "laliga": "西甲", "csl": "中超"}
    CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        """Return whether a public schedule key is available."""

        return bool(self.api_key)

    async def fixtures(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch one day and league at a time, then deduplicate event IDs."""

        if not self.configured:
            raise RuntimeError("THESPORTSDB_API_KEY is not configured")
        results: dict[str, dict] = {}
        async with httpx.AsyncClient(timeout=15) as client:
            current = start_date
            while current <= end_date:
                for league_key, league_id in self.LEAGUE_IDS.items():
                    response = await client.get(
                        f"{self.base_url}/{self.api_key}/eventsday.php",
                        params={"d": current.isoformat(), "s": "Soccer", "l": league_id},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    for item in payload.get("events") or []:
                        mapped = self._map_fixture(item, league_key)
                        results[mapped["id"]] = mapped
                current += timedelta(days=1)
        return sorted(results.values(), key=lambda fixture: fixture["kickoff"])

    async def enrich_fixtures(self, fixtures: list[dict], max_teams: int = 10) -> list[dict]:
        """Attach free team profiles and basic squad lists without evidence claims."""

        team_ids: dict[int, str] = {}
        for fixture in fixtures:
            for side in ("home", "away"):
                team_id = _optional_int((fixture.get(f"{side}_team") or {}).get("provider_id"))
                if team_id and team_id not in team_ids and len(team_ids) < max_teams:
                    team_ids[team_id] = side
        if not team_ids:
            return fixtures

        async with httpx.AsyncClient(timeout=15) as client:
            responses = await asyncio.gather(
                *(self._fetch_team_data(client, team_id) for team_id in team_ids),
                return_exceptions=True,
            )
        team_data = {
            team_id: response
            for team_id, response in zip(team_ids, responses, strict=True)
            if isinstance(response, dict)
        }
        synced_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        enriched: list[dict] = []
        for fixture in fixtures:
            copy = dict(fixture)
            free_team_data: dict[str, dict[str, Any]] = {}
            for side in ("home", "away"):
                team_id = _optional_int((fixture.get(f"{side}_team") or {}).get("provider_id"))
                if team_id in team_data:
                    free_team_data[side] = team_data[team_id]
            if free_team_data:
                copy["free_team_data"] = free_team_data
                copy["free_team_data_synced_at"] = synced_at
            enriched.append(copy)
        return enriched

    async def _fetch_team_data(self, client: httpx.AsyncClient, team_id: int) -> dict[str, Any] | None:
        """Fetch one team's public profile and roster, tolerating partial responses."""

        team_response, players_response = await asyncio.gather(
            client.get(
                f"{self.base_url}/{self.api_key}/lookupteam.php",
                params={"id": team_id},
            ),
            client.get(
                f"{self.base_url}/{self.api_key}/lookup_all_players.php",
                params={"id": team_id},
            ),
            return_exceptions=True,
        )
        team_payload = _response_json(team_response)
        players_payload = _response_json(players_response)
        team = (team_payload.get("teams") or [{}])[0]
        if not team and not players_payload.get("player"):
            return None
        return {
            "profile": self._map_team_profile(team),
            "squad": [self._map_player(player) for player in players_payload.get("player") or []],
            "source": "thesportsdb-free",
        }

    @staticmethod
    def _map_team_profile(team: dict[str, Any]) -> dict[str, Any]:
        """Map stable public team identity fields."""

        original_name = team.get("strTeam") or "未知球队"
        return {
            "name": to_chinese_team_name(original_name),
            "original_name": original_name,
            "logo": team.get("strBadge") or team.get("strTeamBadge"),
            "country": team.get("strCountry"),
            "founded": _optional_int(team.get("intFormedYear")),
            "venue": team.get("strStadium"),
            "capacity": _optional_int(team.get("intStadiumCapacity")),
            "city": team.get("strLocation"),
            "website": team.get("strWebsite"),
        }

    @staticmethod
    def _map_player(player: dict[str, Any]) -> dict[str, Any]:
        """Map the free roster response without inventing market values."""

        original_name = player.get("strPlayer") or "未知球员"
        return {
            "id": _optional_int(player.get("idPlayer")),
            "name": to_chinese_player_name(original_name),
            "original_name": original_name,
            "age": _optional_int(player.get("strAge")),
            "number": _optional_int(player.get("strNumber")),
            "position": player.get("strPosition") or "未知位置",
            "nationality": player.get("strNationality"),
            "photo": player.get("strCutout") or player.get("strThumb"),
            "market_value": None,
            "market_value_currency": "EUR",
            "market_value_source": None,
            "transfermarkt_id": player.get("idTransferMkt"),
        }

    @classmethod
    def _map_fixture(cls, item: dict, league_key: str) -> dict:
        """Map a TheSportsDB event into the application's fixture document."""

        timestamp = item.get("strTimestamp")
        if timestamp:
            kickoff = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=UTC)
            fixture_date = kickoff.astimezone(cls.CHINA_TZ).date().isoformat()
        else:
            kickoff = datetime.fromisoformat(
                f"{item['dateEvent']}T{item.get('strTime') or '00:00:00'}+00:00"
            )
            fixture_date = item["dateEvent"]
        status_text = (item.get("strStatus") or "").lower()
        if item.get("strPostponed") == "yes" or "postpon" in status_text:
            status = "postponed"
        elif "finished" in status_text or item.get("intHomeScore") is not None:
            status = "finished"
        else:
            status = "scheduled"
        home_score = _score(item.get("intHomeScore"))
        away_score = _score(item.get("intAwayScore"))
        return {
            "id": f"sportsdb-{item['idEvent']}",
            "provider_id": int(item["idEvent"]),
            "external_ids": {
                "api_football": _optional_int(item.get("idAPIfootball")),
            },
            "league_key": league_key,
            "league": {
                "id": cls.LEAGUE_IDS[league_key],
                "name": cls.LEAGUE_NAMES[league_key],
                "country": {"epl": "英格兰", "laliga": "西班牙", "csl": "中国"}[league_key],
                "mark": {"epl": "PL", "laliga": "LL", "csl": "CSL"}[league_key],
            },
            "fixture_date": fixture_date,
            "kickoff": kickoff.isoformat(),
            "status": status,
            "provider_status": item.get("strStatus"),
            "home_team": {
                "provider_id": _optional_int(item.get("idHomeTeam")),
                "name": to_chinese_team_name(item.get("strHomeTeam") or "待定"),
                "original_name": item.get("strHomeTeam") or "待定",
                "code": (item.get("strHomeTeam") or "待定")[:3].upper(),
                "logo": item.get("strHomeTeamBadge") or None,
            },
            "away_team": {
                "provider_id": _optional_int(item.get("idAwayTeam")),
                "name": to_chinese_team_name(item.get("strAwayTeam") or "待定"),
                "original_name": item.get("strAwayTeam") or "待定",
                "code": (item.get("strAwayTeam") or "待定")[:3].upper(),
                "logo": item.get("strAwayTeamBadge") or None,
            },
            "score": {"home": home_score, "away": away_score}
            if home_score is not None and away_score is not None
            else None,
            "venue": item.get("strVenue") or "待定",
            "lineup_confirmed": False,
            "is_demo": False,
        }


def _optional_int(value: object) -> int | None:
    """Convert provider IDs while preserving unknown values."""

    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _score(value: object) -> int | None:
    """Convert nullable score strings returned by TheSportsDB."""

    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _response_json(response: object) -> dict[str, Any]:
    """Read a successful JSON response and treat provider failures as empty data."""

    if isinstance(response, httpx.Response) and response.status_code == 200:
        try:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            return {}
    return {}
