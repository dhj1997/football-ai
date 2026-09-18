"""As-of recent-form features built from the canonical fixture store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping

from .league_data_pipeline import SUPPORTED_LEAGUES, normalize_league_code
from .prediction_intelligence import parse_timestamp
from .team_names import to_chinese_team_name


RECENT_FORM_WINDOW = 15
ROLLING_WINDOWS = (3, 5, 8, 10)
RESULT_AVAILABILITY_FALLBACK = timedelta(hours=3)
FINISHED_STATUSES = frozenset({"finished", "ft", "aet", "pen"})


class RecentFormService:
    """Reconstruct one team's recent results without reading future fixtures."""

    def __init__(self, repository: Any, *, max_matches: int = RECENT_FORM_WINDOW) -> None:
        self.repository = repository
        self.max_matches = max(1, min(int(max_matches), RECENT_FORM_WINDOW))

    def team_form(
        self,
        team_id: str,
        *,
        as_of: Any | None = None,
        league: str | None = None,
    ) -> dict[str, Any]:
        code = normalize_league_code(league) if league else None
        if league and code is None:
            raise ValueError("仅支持 CSL、EPL、LAL")
        cutoff = parse_timestamp(as_of) if as_of is not None else datetime.now(UTC)
        if cutoff is None:
            raise ValueError("as_of must be an ISO timestamp")
        matches = self._recent_matches(str(team_id), self._fixtures(code), cutoff, code)
        return self._form_result(str(team_id), cutoff, code, matches)

    def team_matches(
        self,
        team_id: str,
        *,
        as_of: Any,
        league: str | None = None,
        season: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all cutoff-safe team observations for feature calculators."""

        code = normalize_league_code(league) if league else None
        cutoff = parse_timestamp(as_of)
        if cutoff is None:
            raise ValueError("as_of must be an ISO timestamp")
        return self._recent_matches(
            str(team_id),
            self._fixtures(code),
            cutoff,
            code,
            season=season,
        )

    def _form_result(
        self,
        team_id: str,
        cutoff: datetime,
        code: str | None,
        matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        recent_matches = matches[: self.max_matches]
        overall = _aggregate(recent_matches, self.max_matches)
        home = [item for item in recent_matches if item["team_is_home"]]
        away = [item for item in recent_matches if not item["team_is_home"]]
        available_times = [
            parsed
            for item in recent_matches
            if (parsed := parse_timestamp(item.get("available_at"))) is not None
        ]
        season_available_times = [
            parsed
            for item in matches
            if (parsed := parse_timestamp(item.get("available_at"))) is not None
        ]
        return {
            "team_id": team_id,
            "league": code or _single_league(matches),
            "as_of": cutoff.isoformat(),
            "matches_used": len(recent_matches),
            "sample_count": len(recent_matches),
            "sample_status": _sample_status(len(recent_matches), self.max_matches),
            "matches": recent_matches,
            "form": overall,
            "home_form": _aggregate(home, self.max_matches),
            "away_form": _aggregate(away, self.max_matches),
            "rolling": {
                f"last_{window}": _aggregate(matches, window)
                for window in ROLLING_WINDOWS
            },
            "season_average": _aggregate(matches, len(matches)),
            "season_matches_used": len(matches),
            "available_at": max(available_times).isoformat() if available_times else None,
            "source_record_ids": [item["canonical_fixture_id"] for item in recent_matches],
            "season_available_at": max(season_available_times).isoformat() if season_available_times else None,
            "season_source_record_ids": [item["canonical_fixture_id"] for item in matches],
        }

    def context_for_fixture(
        self,
        fixture: Mapping[str, Any],
        *,
        as_of: Any | None = None,
    ) -> dict[str, Any] | None:
        """Return the existing evidence shape backed by one shared as-of snapshot."""

        cutoff = parse_timestamp(as_of) if as_of is not None else datetime.now(UTC)
        if cutoff is None:
            raise ValueError("as_of must be an ISO timestamp")
        code = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
        if code is None:
            return None
        home_team = fixture.get("home_team") or {}
        away_team = fixture.get("away_team") or {}
        home_id = _team_identifier(home_team)
        away_id = _team_identifier(away_team)
        if not home_id or not away_id:
            return None
        fixtures = self._fixtures(code)
        season = _season_key(fixture, code)
        home = self._form_result(
            home_id,
            cutoff,
            code,
            self._recent_matches(home_id, fixtures, cutoff, code, season=season),
        )
        away = self._form_result(
            away_id,
            cutoff,
            code,
            self._recent_matches(away_id, fixtures, cutoff, code, season=season),
        )
        if not home["matches"] or not away["matches"]:
            # A one-sided snapshot carries None points-per-game for the missing
            # side and would crash the Poisson baseline; keep evidence instead.
            return None
        return {
            "home": home["matches"],
            "away": away["matches"],
            "home_points_per_game": home["form"]["points_per_game"],
            "away_points_per_game": away["form"]["points_per_game"],
            "updated_at": _latest_available_at(home, away),
            "available_at": _latest_available_at(home, away),
            "as_of": cutoff.isoformat(),
            "source": "fixtures-recent-form",
            "source_record_ids": sorted(
                set(home["source_record_ids"] + away["source_record_ids"])
            ),
            "snapshot": {"home": home, "away": away},
        }

    def _fixtures(self, code: str | None) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "list_fixtures", None)
        if not callable(reader):
            return []
        try:
            rows = reader()
        except TypeError:
            rows = reader(league_key=code.casefold()) if code else reader()
        normalized = [dict(row) for row in rows if isinstance(row, Mapping)]
        if code:
            normalized = [
                row
                for row in normalized
                if normalize_league_code(row.get("canonical_league") or row.get("league_key")) == code
            ]
        return normalized

    def _recent_matches(
        self,
        team_id: str,
        fixtures: Iterable[Mapping[str, Any]],
        cutoff: datetime,
        league: str | None,
        *,
        season: str | None = None,
    ) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for fixture in fixtures:
            fixture_league = normalize_league_code(
                fixture.get("canonical_league") or fixture.get("league_key")
            )
            if fixture_league not in SUPPORTED_LEAGUES or (league and fixture_league != league):
                continue
            fixture_season = _season_key(fixture, fixture_league)
            if season and fixture_season and fixture_season != season:
                continue
            if not _finished_fixture(fixture):
                continue
            kickoff = parse_timestamp(fixture.get("kickoff"))
            available_at = result_available_at(fixture)
            if kickoff is None or available_at is None or available_at > cutoff:
                continue
            home = fixture.get("home_team") or {}
            away = fixture.get("away_team") or {}
            home_match = _matches_team(home, team_id)
            away_match = _matches_team(away, team_id)
            if home_match == away_match:
                continue
            score = _score_pair(fixture.get("score"))
            if score is None:
                continue
            home_score, away_score = score
            team_is_home = home_match
            team_score, opponent_score = (
                (home_score, away_score) if team_is_home else (away_score, home_score)
            )
            opponent = away if team_is_home else home
            result = "W" if team_score > opponent_score else "D" if team_score == opponent_score else "L"
            fixture_id = str(
                fixture.get("canonical_fixture_id") or fixture.get("id") or ""
            )
            if not fixture_id:
                continue
            candidates[fixture_id] = {
                "date": kickoff.isoformat(),
                "completed_at": available_at.isoformat(),
                "available_at": available_at.isoformat(),
                "availability_basis": result_availability_basis(fixture),
                "fixture_id": str(fixture.get("id") or fixture_id),
                "canonical_fixture_id": fixture.get("canonical_fixture_id") or fixture_id,
                "league": fixture_league,
                "season": fixture_season,
                "source": fixture.get("result_source") or fixture.get("source") or "canonical-fixtures",
                "home": to_chinese_team_name(_team_name(home)),
                "away": to_chinese_team_name(_team_name(away)),
                "score": f"{home_score} - {away_score}",
                "result": result,
                "team_is_home": team_is_home,
                "opponent_id": _team_identifier(opponent),
                "goals_for": team_score,
                "goals_against": opponent_score,
                **_team_source_metrics(fixture, team_is_home),
            }
        ordered = sorted(
            candidates.values(),
            key=lambda item: (str(item["date"]), str(item["fixture_id"])),
            reverse=True,
        )
        return ordered


def result_available_at(fixture: Mapping[str, Any]) -> datetime | None:
    """Return when a final result became knowable, never merely its kickoff."""

    kickoff = parse_timestamp(fixture.get("kickoff"))
    for key in ("result_captured_at", "completed_at"):
        if parsed := parse_timestamp(fixture.get(key)):
            if kickoff is not None and parsed < kickoff:
                return None
            return parsed
    if kickoff is not None and fixture.get("kickoff_date_only"):
        return kickoff.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return kickoff + RESULT_AVAILABILITY_FALLBACK if kickoff else None


def result_availability_basis(fixture: Mapping[str, Any]) -> str:
    if fixture.get("result_captured_at"):
        return "result_captured_at"
    if fixture.get("completed_at"):
        return "completed_at"
    if fixture.get("kickoff_date_only"):
        return "inferred_next_day_from_date_only_kickoff"
    return "inferred_kickoff_plus_3h"


def _season_key(fixture: Mapping[str, Any], league: str | None = None) -> str | None:
    season = fixture.get("season_id") or fixture.get("season")
    if isinstance(season, Mapping):
        season = season.get("id") or season.get("year") or season.get("name")
    if season not in (None, ""):
        return str(season)
    kickoff = parse_timestamp(fixture.get("kickoff"))
    code = normalize_league_code(
        league or fixture.get("canonical_league") or fixture.get("league_key")
    )
    if kickoff is None or code is None:
        return None
    if code == "CSL":
        return str(kickoff.year)
    return str(kickoff.year if kickoff.month >= 7 else kickoff.year - 1)


def _latest_available_at(*forms: Mapping[str, Any]) -> str | None:
    values = [
        parsed
        for form in forms
        if (parsed := parse_timestamp(form.get("available_at"))) is not None
    ]
    return max(values).isoformat() if values else None


def _team_identifier(team: Any) -> str | None:
    if not isinstance(team, Mapping):
        return None
    for key in ("canonical_team_id", "provider_id", "id", "source_team_id", "team_id"):
        value = team.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _team_identifiers(team: Any) -> set[str]:
    if not isinstance(team, Mapping):
        return set()
    return {
        str(team[key])
        for key in ("canonical_team_id", "provider_id", "id", "source_team_id", "team_id")
        if team.get(key) not in (None, "")
    }


def _matches_team(team: Any, team_id: str) -> bool:
    return str(team_id) in _team_identifiers(team)


def _team_name(team: Any) -> str:
    if isinstance(team, Mapping):
        return str(team.get("name") or team.get("original_name") or team.get("display_name") or "待核验球队")
    return str(team or "待核验球队")


def _finished_fixture(fixture: Mapping[str, Any]) -> bool:
    status = str(fixture.get("status") or fixture.get("provider_status") or "").casefold()
    return status in FINISHED_STATUSES and _score_pair(fixture.get("score")) is not None


def _score_pair(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        home = int(value.get("home"))
        away = int(value.get("away"))
    except (TypeError, ValueError):
        return None
    return home, away


def source_metric_pair(fixture: Mapping[str, Any], metric: str) -> tuple[float | None, float | None]:
    """Read an explicitly supplied home/away metric without estimating it."""

    aliases = (metric, "expected_points") if metric == "xpoints" else (metric,)
    containers = [
        fixture,
        fixture.get("match_stats") if isinstance(fixture.get("match_stats"), Mapping) else {},
        fixture.get("statistics") if isinstance(fixture.get("statistics"), Mapping) else {},
        fixture.get("stats") if isinstance(fixture.get("stats"), Mapping) else {},
    ]
    for alias in aliases:
        nested = fixture.get(alias)
        if isinstance(nested, Mapping):
            pair = (_optional_float(nested.get("home")), _optional_float(nested.get("away")))
            if pair != (None, None):
                return pair
        for container in containers:
            pair = (
                _optional_float(container.get(f"home_{alias}")),
                _optional_float(container.get(f"away_{alias}")),
            )
            if pair != (None, None):
                return pair
    return None, None


def _team_source_metrics(fixture: Mapping[str, Any], team_is_home: bool) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric in ("xg", "xpoints", "shots_on_target", "shots"):
        home, away = source_metric_pair(fixture, metric)
        own, opponent = (home, away) if team_is_home else (away, home)
        if metric == "xg":
            metrics["xg_for"] = own
            metrics["xg_against"] = opponent
        elif metric == "xpoints":
            metrics["xpoints"] = own
        else:
            metrics[f"{metric}_for"] = own
            metrics[f"{metric}_against"] = opponent
        if metric in {"xg", "xpoints"}:
            available_at = fixture.get(f"{metric}_available_at")
            if available_at is None and isinstance(fixture.get(metric), Mapping):
                available_at = fixture[metric].get("available_at")
            metrics[f"{metric}_available_at"] = available_at
    return metrics


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _sample_status(count: int, limit: int) -> str:
    if count <= 0:
        return "unavailable"
    return "ok" if count >= limit else "insufficient"


def _aggregate(rows: list[Mapping[str, Any]], limit: int) -> dict[str, Any]:
    selected = rows[:limit]
    count = len(selected)
    wins = sum(item.get("result") == "W" for item in selected)
    draws = sum(item.get("result") == "D" for item in selected)
    losses = sum(item.get("result") == "L" for item in selected)
    goals_for = sum(int(item.get("goals_for") or 0) for item in selected)
    goals_against = sum(int(item.get("goals_against") or 0) for item in selected)
    points = wins * 3 + draws
    return {
        "sample_count": count,
        "sample_status": _sample_status(count, limit),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_difference": goals_for - goals_against,
        "points": points,
        "points_per_game": round(points / count, 4) if count else None,
        "goals_for_per_game": round(goals_for / count, 4) if count else None,
        "goals_against_per_game": round(goals_against / count, 4) if count else None,
        "goal_difference_per_game": round((goals_for - goals_against) / count, 4) if count else None,
        "win_rate": round(wins / count, 4) if count else None,
        "draw_rate": round(draws / count, 4) if count else None,
        "loss_rate": round(losses / count, 4) if count else None,
    }


def _single_league(matches: Iterable[Mapping[str, Any]]) -> str | None:
    values = {str(item.get("league")) for item in matches if item.get("league")}
    return sorted(values)[0] if len(values) == 1 else None


__all__ = [
    "RECENT_FORM_WINDOW",
    "RESULT_AVAILABILITY_FALLBACK",
    "ROLLING_WINDOWS",
    "RecentFormService",
    "result_availability_basis",
    "result_available_at",
]
