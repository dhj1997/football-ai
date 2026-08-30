"""Current-season league tables from ESPN's public soccer feed."""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx

from .team_names import to_chinese_team_name


class EspnLeagueProvider:
    """Fetch and normalize complete current tables for the supported leagues."""

    LEAGUE_SLUGS = {"epl": "eng.1", "laliga": "esp.1", "csl": "chn.1"}
    LEAGUE_NAMES = {"epl": "英超", "laliga": "西甲", "csl": "中超"}
    LEAGUE_IDS = {"epl": 4328, "laliga": 4335, "csl": 4359}
    LEAGUE_COUNTRIES = {"epl": "英格兰", "laliga": "西班牙", "csl": "中国"}
    CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def standings(self) -> list[dict[str, Any]]:
        """Fetch all supported current-season tables concurrently."""

        if not self.configured:
            raise RuntimeError("ESPN standings provider is not configured")
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
            responses = await asyncio.gather(
                *(
                    client.get(f"/apis/v2/sports/soccer/{slug}/standings")
                    for slug in self.LEAGUE_SLUGS.values()
                )
            )
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        snapshots: list[dict[str, Any]] = []
        for league_key, response in zip(self.LEAGUE_SLUGS, responses, strict=True):
            response.raise_for_status()
            snapshots.append(self._map_standings(response.json(), league_key, updated_at))
        return snapshots

    async def fixtures(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        """Fetch a bounded scoreboard window for status and score reconciliation."""

        if not self.configured:
            raise RuntimeError("ESPN scoreboard provider is not configured")
        dates = f"{start_date:%Y%m%d}-{end_date:%Y%m%d}"
        headers = {"User-Agent": "football-ai/0.1 (+score-sync)"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20, headers=headers) as client:
            responses = await asyncio.gather(
                *(
                    client.get(
                        f"/apis/site/v2/sports/soccer/{slug}/scoreboard",
                        params={"dates": dates, "limit": 100},
                    )
                    for slug in self.LEAGUE_SLUGS.values()
                )
            )
        captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        fixtures: list[dict[str, Any]] = []
        for league_key, response in zip(self.LEAGUE_SLUGS, responses, strict=True):
            response.raise_for_status()
            fixtures.extend(
                self._map_scoreboard_event(event, league_key, captured_at)
                for event in (response.json().get("events") or [])
            )
        return sorted(fixtures, key=lambda item: (item["kickoff"], item["id"]))

    @classmethod
    def _map_scoreboard_event(
        cls,
        event: dict[str, Any],
        league_key: str,
        captured_at: str,
    ) -> dict[str, Any]:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        home = next((item for item in competitors if item.get("homeAway") == "home"), {})
        away = next((item for item in competitors if item.get("homeAway") == "away"), {})
        status_type = (event.get("status") or {}).get("type") or {}
        state = str(status_type.get("state") or "").casefold()
        description = " ".join(
            str(status_type.get(key) or "") for key in ("name", "description", "shortDetail")
        ).casefold()
        if bool(status_type.get("completed")) or state == "post":
            status = "finished"
        elif "postpon" in description or "suspend" in description:
            status = "postponed"
        elif "cancel" in description or "abandon" in description:
            status = "cancelled"
        elif state == "in":
            status = "live"
        else:
            status = "scheduled"
        kickoff = datetime.fromisoformat(str(event.get("date") or "").replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
        home_score = _optional_score(home.get("score"))
        away_score = _optional_score(away.get("score"))
        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        venue = competition.get("venue") or {}
        return {
            "id": f"espn-{event['id']}",
            "provider_id": event.get("id"),
            "league_key": league_key,
            "league": {
                "id": cls.LEAGUE_IDS[league_key],
                "name": cls.LEAGUE_NAMES[league_key],
                "country": cls.LEAGUE_COUNTRIES[league_key],
                "mark": {"epl": "PL", "laliga": "LL", "csl": "CSL"}[league_key],
            },
            "fixture_date": kickoff.astimezone(cls.CHINA_TZ).date().isoformat(),
            "kickoff": kickoff.isoformat(),
            "status": status,
            "provider_status": status_type.get("shortDetail") or status_type.get("name"),
            "home_team": _scoreboard_team(home_team),
            "away_team": _scoreboard_team(away_team),
            "score": {"home": home_score, "away": away_score}
            if status in {"live", "finished"} and home_score is not None and away_score is not None
            else None,
            "venue": venue.get("fullName") or venue.get("name") or "待定",
            "lineup_confirmed": False,
            "captured_at": captured_at,
            "is_demo": False,
        }

    @classmethod
    def _map_standings(
        cls,
        payload: dict[str, Any],
        league_key: str,
        updated_at: str,
    ) -> dict[str, Any]:
        season = payload.get("season") or {}
        groups = payload.get("children") or []
        entries: list[dict[str, Any]] = []
        for group in groups:
            entries.extend(((group.get("standings") or {}).get("entries") or []))
        if not season.get("year") or not entries:
            raise RuntimeError(f"ESPN returned no current standings for {league_key}")

        table = []
        for entry in entries:
            team = entry.get("team") or {}
            stats = {
                stat.get("name"): stat.get("value")
                for stat in entry.get("stats") or []
                if stat.get("name")
            }
            original_name = team.get("displayName") or team.get("name") or "未知球队"
            logos = team.get("logos") or []
            table.append(
                {
                    "rank": _as_int(stats.get("rank")),
                    "team": {
                        "provider_id": team.get("id"),
                        "name": to_chinese_team_name(original_name),
                        "original_name": original_name,
                        "code": team.get("abbreviation") or original_name[:3].upper(),
                        "logo": (logos[0].get("href") if logos else None),
                    },
                    "played": _as_int(stats.get("gamesPlayed")),
                    "wins": _as_int(stats.get("wins")),
                    "draws": _as_int(stats.get("ties")),
                    "losses": _as_int(stats.get("losses")),
                    "goals_for": _as_int(stats.get("pointsFor")),
                    "goals_against": _as_int(stats.get("pointsAgainst")),
                    "goal_difference": _as_int(stats.get("pointDifferential")),
                    "points": _as_int(stats.get("points")),
                    "note": (entry.get("note") or {}).get("description"),
                }
            )
        table.sort(key=lambda row: row["rank"])
        return {
            "league_key": league_key,
            "league_name": cls.LEAGUE_NAMES[league_key],
            "season": {
                "year": _as_int(season.get("year")),
                "name": season.get("displayName") or str(season.get("year")),
                "start_date": season.get("startDate"),
                "end_date": season.get("endDate"),
            },
            "standings": table,
            "team_count": len(table),
            "source": "espn",
            "updated_at": updated_at,
        }


def _as_int(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_score(value: object) -> int | None:
    raw = value.get("value") if isinstance(value, dict) else value
    try:
        return int(float(raw)) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _scoreboard_team(team: dict[str, Any]) -> dict[str, Any]:
    original_name = team.get("displayName") or team.get("name") or "未知球队"
    return {
        "provider_id": str(team.get("id")) if team.get("id") is not None else None,
        "name": to_chinese_team_name(original_name),
        "original_name": original_name,
        "code": team.get("abbreviation") or original_name[:3].upper(),
        "logo": team.get("logo"),
    }
