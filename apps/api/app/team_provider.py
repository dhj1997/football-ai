"""Current-season team rosters, player statistics, and match records from ESPN."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from .league_provider import EspnLeagueProvider
from .team_names import to_chinese_player_name, to_chinese_team_name


class EspnTeamProvider:
    """Fetch one supported team's current-season detail."""

    LEAGUE_SLUGS = EspnLeagueProvider.LEAGUE_SLUGS

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def team(self, league_key: str, team_id: str, season_year: int) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("ESPN team provider is not configured")
        slug = self.LEAGUE_SLUGS.get(league_key)
        if not slug:
            raise ValueError(f"Unsupported league: {league_key}")

        headers = {"User-Agent": "football-ai/0.1 (+team-data)"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20, headers=headers) as client:
            roster_response, schedule_response = await asyncio.gather(
                client.get(f"/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/roster"),
                client.get(
                    f"/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule",
                    params={"season": season_year},
                ),
            )
        roster_response.raise_for_status()
        schedule_response.raise_for_status()
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        return self._map_team(
            roster_response.json(),
            schedule_response.json(),
            league_key,
            str(team_id),
            updated_at,
        )

    @classmethod
    def _map_team(
        cls,
        roster_payload: dict[str, Any],
        schedule_payload: dict[str, Any],
        league_key: str,
        team_id: str,
        updated_at: str,
    ) -> dict[str, Any]:
        season = roster_payload.get("season") or schedule_payload.get("season") or {}
        team = roster_payload.get("team") or schedule_payload.get("team") or {}
        athletes = roster_payload.get("athletes") or []
        if not season.get("year") or not team.get("id"):
            raise RuntimeError(f"ESPN returned incomplete team data for {league_key}/{team_id}")

        original_name = team.get("displayName") or team.get("name") or "Unknown team"
        roster = [_map_player(item) for item in athletes]
        roster.sort(key=lambda item: (item["position_order"], item["number"] is None, item["number"] or 999, item["original_name"]))
        matches = [
            mapped
            for event in schedule_payload.get("events") or []
            if (mapped := _map_match(event, str(team_id))) is not None
        ]
        matches.sort(key=lambda item: item["date"], reverse=True)
        return {
            "league_key": league_key,
            "team_id": str(team.get("id") or team_id),
            "season": {
                "year": int(season["year"]),
                "name": season.get("displayName") or season.get("name") or str(season["year"]),
            },
            "team": {
                "name": to_chinese_team_name(original_name),
                "original_name": original_name,
                "abbreviation": team.get("abbreviation"),
                "logo": team.get("logo"),
                "color": team.get("color"),
                "record_summary": team.get("recordSummary"),
                "standing_summary": team.get("standingSummary"),
            },
            "coach": _map_coach(roster_payload.get("coach")),
            "roster": roster,
            "roster_count": len(roster),
            "matches": matches,
            "source": "espn",
            "updated_at": updated_at,
        }


def _map_player(player: dict[str, Any]) -> dict[str, Any]:
    position = player.get("position") or {}
    stats = _flatten_stats(player.get("statistics"))
    original_name = player.get("fullName") or player.get("displayName") or "Unknown player"
    number = _optional_int(player.get("jersey"))
    status = player.get("status") or {}
    return {
        "id": str(player.get("id")) if player.get("id") is not None else None,
        "provider_player_id": str(player["id"]) if player.get("id") is not None else None,
        "name": to_chinese_player_name(original_name),
        "original_name": original_name,
        "number": number,
        "position": position.get("displayName") or position.get("name") or "Unknown",
        "position_code": position.get("abbreviation"),
        "position_order": _position_order(position.get("abbreviation")),
        "age": _optional_int(player.get("age")),
        "date_of_birth": player.get("dateOfBirth"),
        "nationality": player.get("citizenship"),
        "photo": ((player.get("headshot") or {}).get("href")),
        "status": status.get("name") or status.get("type"),
        "injuries": [_map_injury(item) for item in player.get("injuries") or []],
        "statistics": {
            "appearances": _stat_int(stats, "appearances"),
            "substitute_appearances": _stat_int(stats, "subIns"),
            "starts": _stat_optional_int(stats, "starts", "gamesStarted"),
            "minutes": _stat_optional_int(stats, "minutes", "minutesPlayed"),
            "goals": _stat_int(stats, "totalGoals"),
            "assists": _stat_int(stats, "goalAssists"),
            "yellow_cards": _stat_int(stats, "yellowCards"),
            "red_cards": _stat_int(stats, "redCards"),
            "saves": _stat_int(stats, "saves"),
            "goals_conceded": _stat_int(stats, "goalsConceded"),
        },
    }


def _flatten_stats(payload: Any) -> dict[str, Any]:
    categories = (((payload or {}).get("splits") or {}).get("categories") or [])
    return {
        stat["name"]: stat.get("value")
        for category in categories
        for stat in category.get("stats") or []
        if stat.get("name")
    }


def _map_injury(injury: dict[str, Any]) -> dict[str, Any]:
    injury_type = injury.get("type") or {}
    status = injury.get("status") or {}
    return {
        "type": injury_type.get("description") or injury_type.get("name") or injury.get("description"),
        "status": status.get("description") or status.get("name") or injury.get("status"),
        "detail": injury.get("details") or injury.get("detail"),
        "date": injury.get("date"),
    }


def _map_coach(coach: Any) -> dict[str, Any] | None:
    if isinstance(coach, list):
        coach = coach[0] if coach else None
    if not isinstance(coach, dict) or not coach:
        return None
    name = (
        coach.get("fullName")
        or coach.get("displayName")
        or coach.get("name")
        or " ".join(filter(None, (coach.get("firstName"), coach.get("lastName"))))
    )
    if not name:
        return None
    return {"name": name, "nationality": coach.get("citizenship")}


def _map_match(event: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), None)
    away = next((item for item in competitors if item.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status_type = ((competition.get("status") or {}).get("type") or {})
    completed = bool(status_type.get("completed"))
    state = status_type.get("state")
    home_score = _score(home.get("score"))
    away_score = _score(away.get("score"))
    team_is_home = str(home.get("id")) == team_id
    result = None
    if completed and home_score is not None and away_score is not None:
        team_score, opponent_score = (home_score, away_score) if team_is_home else (away_score, home_score)
        result = "W" if team_score > opponent_score else "D" if team_score == opponent_score else "L"
    venue = competition.get("venue") or {}
    return {
        "id": str(event.get("id")),
        "date": event.get("date") or competition.get("date"),
        "status": "finished" if completed else "live" if state == "in" else "scheduled",
        "status_text": status_type.get("shortDetail") or status_type.get("description"),
        "home": _team_identity(home.get("team")),
        "away": _team_identity(away.get("team")),
        "home_score": home_score,
        "away_score": away_score,
        "result": result,
        "team_is_home": team_is_home,
        "venue": venue.get("fullName") or venue.get("name"),
    }


def _team_identity(team: Any) -> dict[str, Any]:
    item = team if isinstance(team, dict) else {}
    original_name = item.get("displayName") or item.get("name") or "Unknown team"
    return {
        "id": str(item.get("id")) if item.get("id") is not None else None,
        "name": to_chinese_team_name(original_name),
        "original_name": original_name,
        "logo": item.get("logo"),
    }


def _score(value: Any) -> int | None:
    raw = value.get("value") if isinstance(value, dict) else value
    try:
        return int(float(raw)) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _stat_int(stats: dict[str, Any], key: str) -> int:
    return _optional_int(stats.get(key)) or 0


def _stat_optional_int(stats: dict[str, Any], *keys: str) -> int | None:
    return next((_optional_int(stats.get(key)) for key in keys if _optional_int(stats.get(key)) is not None), None)


def _optional_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _position_order(code: Any) -> int:
    return {"G": 0, "D": 1, "M": 2, "F": 3}.get(str(code or "").upper(), 4)
