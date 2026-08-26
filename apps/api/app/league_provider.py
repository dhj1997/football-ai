"""Current-season league tables from ESPN's public soccer feed."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from .team_names import to_chinese_team_name


class EspnLeagueProvider:
    """Fetch and normalize complete current tables for the supported leagues."""

    LEAGUE_SLUGS = {"epl": "eng.1", "laliga": "esp.1", "csl": "chn.1"}
    LEAGUE_NAMES = {"epl": "英超", "laliga": "西甲", "csl": "中超"}

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

