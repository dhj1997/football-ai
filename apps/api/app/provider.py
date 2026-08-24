"""API-Football adapter for scheduled fixtures and pre-match evidence."""

from datetime import UTC, date, datetime, timedelta, timezone

import httpx

from .team_names import to_chinese_team_name


class ApiFootballProvider:
    """Fetch API-Football data only during explicit operator actions."""

    LEAGUE_IDS = {"epl": 39, "laliga": 140, "csl": 169}
    CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        """Return whether an API key is available."""

        return bool(self.api_key)

    @staticmethod
    def season_for(league_key: str, fixture_date: date) -> int:
        """Return the provider season year for a supported league."""

        if league_key == "csl":
            return fixture_date.year
        return fixture_date.year if fixture_date.month >= 7 else fixture_date.year - 1

    async def fixtures(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch one date window using one request per supported league."""

        if not self.configured:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        results: list[dict] = []
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key},
            timeout=15,
        ) as client:
            for league_key, league_id in self.LEAGUE_IDS.items():
                response = await client.get(
                    "/fixtures",
                    params={
                        "from": start_date.isoformat(),
                        "to": end_date.isoformat(),
                        "league": league_id,
                        "season": self.season_for(league_key, end_date),
                        "timezone": "Asia/Shanghai",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("errors"):
                    raise RuntimeError(f"API-Football error for {league_key}: {payload['errors']}")
                for item in payload.get("response", []):
                    results.append(self._map_fixture(item, league_key))
        return results

    @staticmethod
    def _map_fixture(item: dict, league_key: str) -> dict:
        fixture = item["fixture"]
        league = item["league"]
        teams = item["teams"]
        goals = item.get("goals") or {}
        status_code = fixture["status"]["short"]
        finished_codes = {"FT", "AET", "PEN"}
        cancelled_codes = {"CANC", "ABD", "AWD", "WO"}
        postponed_codes = {"PST", "SUSP", "INT"}
        if status_code in finished_codes:
            status = "finished"
        elif status_code in cancelled_codes:
            status = "cancelled"
        elif status_code in postponed_codes:
            status = "postponed"
        elif status_code in {"NS", "TBD"}:
            status = "scheduled"
        else:
            status = "live"
        kickoff = datetime.fromisoformat(fixture["date"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
        return {
            "id": f"api-{fixture['id']}",
            "provider_id": fixture["id"],
            "league_key": league_key,
            "league": {"id": league["id"], "name": league["name"], "country": league["country"], "mark": league["name"][:3].upper()},
            "fixture_date": kickoff.astimezone(ApiFootballProvider.CHINA_TZ).date().isoformat(),
            "kickoff": fixture["date"],
            "status": status,
            "provider_status": status_code,
            "home_team": {"provider_id": teams["home"]["id"], "name": to_chinese_team_name(teams["home"]["name"]), "code": teams["home"].get("code") or teams["home"]["name"][:3].upper()},
            "away_team": {"provider_id": teams["away"]["id"], "name": to_chinese_team_name(teams["away"]["name"]), "code": teams["away"].get("code") or teams["away"]["name"][:3].upper()},
            "score": {"home": goals.get("home"), "away": goals.get("away")} if goals.get("home") is not None else None,
            "venue": (fixture.get("venue") or {}).get("name") or "待定",
            "lineup_confirmed": bool(item.get("lineups")),
            "is_demo": False,
        }
