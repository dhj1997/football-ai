"""As-of team stat profiles from Football-Data historical matches.

Profiles are per-team averages (shots / shots on target / corners / goals,
for and against) computed only from finished matches strictly before the
reference time, keyed by localized team name. One scan per calendar day is
cached in-process to bound read cost.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from .historical_validation import parse_timestamp
from .recent_form import result_available_at

_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
SUPPORTED_LEAGUES: tuple[str, ...] = ("epl", "laliga")


def team_stat_profiles(
    repository: Any,
    *,
    before_iso: str,
    leagues: tuple[str, ...] = SUPPORTED_LEAGUES,
    min_matches: int = 8,
    fixtures_rows: list | None = None,
) -> dict[str, dict[str, Any]]:
    """Profiles for every team with enough history before ``before_iso``."""

    before = parse_timestamp(before_iso)
    cache_cutoff = before.isoformat() if before else str(before_iso)
    cache_key = f"{cache_cutoff}|{','.join(leagues)}|{min_matches}"
    cached = _CACHE.get(cache_key)
    if cached is None:
        cached = _scan(repository, before_iso, leagues, min_matches, fixtures_rows)
        _CACHE.clear()
        _CACHE[cache_key] = cached
    return cached


def attach_team_stats(
    repository: Any,
    fixture: Mapping[str, Any],
    context: dict[str, Any],
    *,
    prediction_timestamp: Any = None,
    min_matches: int = 8,
    fixtures_rows: list | None = None,
) -> None:
    """Inject the two teams' stat profiles into the prediction context.

    Guards everything: any failure leaves the context untouched (the
    dimension is additive research context, never a prediction input gate).
    """

    try:
        if fixture.get("is_demo"):
            return
        if str(fixture.get("league_key") or "") not in SUPPORTED_LEAGUES:
            return
        before = parse_timestamp(prediction_timestamp) or datetime.now(UTC)
        profiles = team_stat_profiles(
            repository,
            before_iso=before.isoformat(),
            min_matches=min_matches,
            fixtures_rows=fixtures_rows,
        )
        home_name = str(((fixture.get("home_team") or {}).get("name")) or "")
        away_name = str(((fixture.get("away_team") or {}).get("name")) or "")
        home = profiles.get(home_name)
        away = profiles.get(away_name)
        if home and away:
            context["team_stats"] = {
                "home": home,
                "away": away,
                "as_of": before.isoformat(),
                "available_at": max(
                    str(home.get("available_at") or ""),
                    str(away.get("available_at") or ""),
                ) or None,
                "source": "football-data",
                "source_record_ids": sorted(
                    set((home.get("source_record_ids") or []) + (away.get("source_record_ids") or []))
                ),
            }
    except Exception:
        return


def _scan(
    repository: Any,
    before_iso: str,
    leagues: tuple[str, ...],
    min_matches: int,
    fixtures_rows: list | None = None,
) -> dict[str, dict[str, Any]]:
    before = parse_timestamp(before_iso) or datetime.now(UTC)
    if fixtures_rows is not None:
        rows = fixtures_rows
    else:
        reader = getattr(repository, "list_fixtures", None)
        rows = reader() if callable(reader) else []
    accumulated: dict[str, dict[str, list[float]]] = {}
    available_times: dict[str, list[datetime]] = {}
    source_record_ids: dict[str, set[str]] = {}
    for row in rows or []:
        if row.get("status") != "finished" or row.get("source") != "football-data":
            continue
        if str(row.get("league_key") or "") not in leagues:
            continue
        available_at = result_available_at(row)
        if available_at is None or available_at > before:
            continue
        stats = row.get("match_stats") if isinstance(row.get("match_stats"), Mapping) else None
        if not stats:
            continue
        for side in ("home", "away"):
            team = str(((row.get(f"{side}_team") or {}).get("name")) or "")
            if not team:
                continue
            available_times.setdefault(team, []).append(available_at)
            source_record_ids.setdefault(team, set()).add(
                str(row.get("canonical_fixture_id") or row.get("id") or "")
            )
            bucket = accumulated.setdefault(
                team,
                {"shots_for": [], "shots_against": [], "shots_on_target_for": [], "shots_on_target_against": [], "corners_for": [], "corners_against": [], "goals_for": [], "goals_against": []},
            )
            opponent = "away" if side == "home" else "home"
            for key, value in (
                ("shots_for", stats.get(f"{side}_shots")),
                ("shots_against", stats.get(f"{opponent}_shots")),
                ("shots_on_target_for", stats.get(f"{side}_shots_on_target")),
                ("shots_on_target_against", stats.get(f"{opponent}_shots_on_target")),
                ("corners_for", stats.get(f"{side}_corners")),
                ("corners_against", stats.get(f"{opponent}_corners")),
                ("goals_for", (row.get("score") or {}).get(side) if isinstance(row.get("score"), Mapping) else None),
                ("goals_against", (row.get("score") or {}).get(opponent) if isinstance(row.get("score"), Mapping) else None),
            ):
                if value is not None:
                    bucket[key].append(float(value))
    profiles: dict[str, dict[str, Any]] = {}
    for team, bucket in accumulated.items():
        if len(bucket["goals_for"]) < min_matches:
            continue
        profile: dict[str, Any] = {"matches": float(len(bucket["goals_for"]))}
        for key, values in bucket.items():
            profile[key] = round(sum(values) / len(values), 3) if values else 0.0
        profile["available_at"] = max(available_times.get(team) or []).isoformat()
        profile["source"] = "football-data"
        profile["source_record_ids"] = sorted(value for value in source_record_ids.get(team, set()) if value)
        profiles[team] = profile
    return profiles
