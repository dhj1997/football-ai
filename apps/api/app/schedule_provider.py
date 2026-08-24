"""Free schedule provider backed by TheSportsDB's v1 JSON API."""

from datetime import UTC, date, datetime, timedelta, timezone

import httpx

from .team_names import to_chinese_team_name


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
                "code": (item.get("strHomeTeam") or "待定")[:3].upper(),
            },
            "away_team": {
                "provider_id": _optional_int(item.get("idAwayTeam")),
                "name": to_chinese_team_name(item.get("strAwayTeam") or "待定"),
                "code": (item.get("strAwayTeam") or "待定")[:3].upper(),
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
