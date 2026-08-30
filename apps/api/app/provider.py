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

    async def historical_fixtures(
        self,
        league: str,
        season: int,
        *,
        page: int = 1,
        limit: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        **_: object,
    ) -> dict:
        """Fetch one bounded provider page for historical validation."""

        if not self.configured:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        league_id = self.LEAGUE_IDS.get(str(league).casefold())
        if league_id is None:
            raise ValueError(f"Unsupported API-Football league: {league}")
        params = {
            "league": league_id,
            "season": season,
            "timezone": "UTC",
        }
        # Some API-Football plans expose a complete season as one page and
        # reject the otherwise documented `page` parameter. The response's
        # paging metadata still lets the ingestion service enforce its cap.
        if int(page) > 1:
            params["page"] = int(page)
        if start_date:
            params["from"] = start_date.isoformat()
        if end_date:
            params["to"] = end_date.isoformat()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key},
            timeout=15,
        ) as client:
            response = await client.get("/fixtures", params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football error for {league}: {payload['errors']}")
        captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        paging = payload.get("paging") or {}
        response_items = payload.get("response", [])
        # The current account returns the complete season as a single page;
        # let P5 apply its league/global cap instead of discarding the rest
        # before the ingestion service sees it.
        if (paging.get("total") or 1) > 1:
            response_items = response_items[: max(1, int(limit))]
        items = []
        for item in response_items:
            mapped = self._map_fixture(item, str(league).casefold())
            mapped["source"] = "api-football"
            mapped["captured_at"] = captured_at
            items.append(mapped)
        return {
            "items": items,
            "page": paging.get("current") or page,
            "has_more": bool((paging.get("current") or page) < (paging.get("total") or page)),
        }

    async def historical_results(self, **kwargs: object) -> dict:
        """Reuse the fixture endpoint for final scores without a second data shape."""

        response = await self.historical_fixtures(**kwargs)
        response["items"] = [item for item in response.get("items") or [] if item.get("score")]
        return response

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
            "home_team": {"provider_id": teams["home"]["id"], "name": to_chinese_team_name(teams["home"]["name"]), "original_name": teams["home"]["name"], "code": teams["home"].get("code") or teams["home"]["name"][:3].upper(), "logo": teams["home"].get("logo")},
            "away_team": {"provider_id": teams["away"]["id"], "name": to_chinese_team_name(teams["away"]["name"]), "original_name": teams["away"]["name"], "code": teams["away"].get("code") or teams["away"]["name"][:3].upper(), "logo": teams["away"].get("logo")},
            "score": {"home": goals.get("home"), "away": goals.get("away")} if goals.get("home") is not None else None,
            "venue": (fixture.get("venue") or {}).get("name") or "待定",
            "lineup_confirmed": bool(item.get("lineups")),
            "is_demo": False,
        }
