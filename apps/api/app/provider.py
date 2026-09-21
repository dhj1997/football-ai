"""API-Football adapter for scheduled fixtures and pre-match evidence."""

from datetime import UTC, date, datetime, timedelta, timezone

import httpx

from .national_competitions import (
    NATIONAL_COMPETITIONS,
    NATIONAL_COMPETITION_KEYS,
    national_competition_from_api_id,
)
from .team_names import to_chinese_team_name


class ApiFootballProvider:
    """Fetch API-Football data only during explicit operator actions."""

    LEAGUE_IDS = {
        "epl": 39,
        "laliga": 140,
        "csl": 169,
        "cfa_cup": 171,
        **{key: item.api_football_ids[0] for key, item in NATIONAL_COMPETITIONS.items() if item.api_football_ids},
    }
    LEAGUE_ID_GROUPS = {
        key: tuple(item.api_football_ids)
        for key, item in NATIONAL_COMPETITIONS.items()
        if item.api_football_ids
    }
    LEAGUE_NAMES = {
        "cfa_cup": "中国足协杯",
        **{key: item.name for key, item in NATIONAL_COMPETITIONS.items()},
    }
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

        if league_key in {"csl", "cfa_cup"}:
            return fixture_date.year
        if league_key in NATIONAL_COMPETITION_KEYS:
            return fixture_date.year
        return fixture_date.year if fixture_date.month >= 7 else fixture_date.year - 1

    @property
    def request_league_count(self) -> int:
        return len(self.LEAGUE_IDS) + sum(len(ids) - 1 for ids in self.LEAGUE_ID_GROUPS.values())

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
            for league_key, configured_id in self.LEAGUE_IDS.items():
                league_ids = self.LEAGUE_ID_GROUPS.get(league_key, (configured_id,))
                for league_id in league_ids:
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
                        mapped_key = league_key
                        provider_competition = national_competition_from_api_id((item.get("league") or {}).get("id"))
                        if provider_competition is not None:
                            mapped_key = provider_competition.key
                        results.append(self._map_fixture(item, mapped_key))
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

    async def fixture_statistics(self, fixture_id: int | str) -> dict[str, int] | None:
        """Return per-team shots / shots on target / corners for one fixture.

        API-Football lists the home team first in the statistics response.
        None when the fixture has no statistics yet (live or not started).
        """

        if not self.configured:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key},
            timeout=15,
        ) as client:
            response = await client.get("/fixtures/statistics", params={"fixture": fixture_id})
            response.raise_for_status()
            payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football statistics error for {fixture_id}: {payload['errors']}")
        teams = payload.get("response") or []
        if len(teams) != 2:
            return None
        mapped = [self._map_fixture_statistics(team.get("statistics") or []) for team in teams]
        home, away = mapped
        if home is None or away is None:
            return None
        return {
            "home_shots": home[0],
            "away_shots": away[0],
            "home_shots_on_target": home[1],
            "away_shots_on_target": away[1],
            "home_corners": home[2],
            "away_corners": away[2],
        }

    async def fixture_events(self, fixture_id: int | str) -> dict[str, list] | None:
        """Return raw card events of one fixture; None when none are recorded."""

        if not self.configured:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key},
            timeout=15,
        ) as client:
            response = await client.get("/fixtures/events", params={"fixture": fixture_id})
            response.raise_for_status()
            payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football events error for {fixture_id}: {payload['errors']}")
        cards = []
        for event in payload.get("response") or []:
            if not isinstance(event, dict) or event.get("type") != "Card":
                continue
            detail = str(event.get("detail") or "").strip()
            if not detail:
                continue
            cards.append(
                {
                    "team": str((event.get("team") or {}).get("name") or ""),
                    "detail": detail,
                    "player": str((event.get("player") or {}).get("name") or "") or None,
                }
            )
        return {"cards": cards} if cards else None

    async def team_transfers(self, team_id: int | str) -> list[dict]:
        """Map one team's recorded transfers (in/out) to flat rows."""

        if not self.configured:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"x-apisports-key": self.api_key},
            timeout=15,
        ) as client:
            response = await client.get("/transfers", params={"team": team_id})
            response.raise_for_status()
            payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"API-Football transfers error for team {team_id}: {payload['errors']}")
        rows: list[dict] = []
        for entry in payload.get("response") or []:
            player_name = str((entry.get("player") or {}).get("name") or "") or None
            for transfer in entry.get("transfers") or []:
                teams = transfer.get("teams") if isinstance(transfer.get("teams"), dict) else {}
                rows.append(
                    {
                        "player": player_name,
                        "date": str(transfer.get("date") or "")[:10] or None,
                        "type": str(transfer.get("type") or "") or None,
                        "in_team": str((teams.get("in") or {}).get("name") or "") or None,
                        "in_team_id": (teams.get("in") or {}).get("id"),
                        "out_team": str((teams.get("out") or {}).get("name") or "") or None,
                        "out_team_id": (teams.get("out") or {}).get("id"),
                    }
                )
        return rows

    @staticmethod
    def _map_fixture_statistics(rows: list) -> tuple[int, int, int] | None:
        """Map one team's statistics list to (shots, shots on target, corners)."""

        values: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str((row.get("type") or "")).strip().lower()
            raw = row.get("value")
            if raw is None:
                continue
            try:
                value = int(str(raw).strip().rstrip("%"))
            except ValueError:
                continue
            values[label] = value
        try:
            return values["total shots"], values["shots on goal"], values["corner kicks"]
        except KeyError:
            return None

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
        competition = NATIONAL_COMPETITIONS.get(league_key)
        provider_league_name = str(league.get("name") or "")
        league_name = ApiFootballProvider.LEAGUE_NAMES.get(league_key, provider_league_name)
        league_metadata = competition.as_dict() if competition is not None else None
        mapped_league = {
            "id": league["id"],
            "name": league_name,
            "country": competition.confederation if competition is not None else league.get("country") or "",
            "mark": competition.key.upper() if competition is not None else provider_league_name[:3].upper(),
        }
        if league_metadata is not None:
            mapped_league.update(
                {
                    "logo": league_metadata.get("logo_url"),
                    "logo_source": league_metadata.get("logo_source"),
                }
            )
        return {
            "id": f"api-{fixture['id']}",
            "provider_id": fixture["id"],
            "league_key": league_key,
            "league": mapped_league,
            "national_competition": league_metadata,
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
