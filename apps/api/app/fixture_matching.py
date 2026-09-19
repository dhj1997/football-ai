"""Cross-source fixture matching: one physical match across parallel provider rows.

Used by ingestion flows (Understat xG, API-Football match statistics) that
must attach per-match metrics onto every canonical row of the same physical
match. Matching is date-window plus canonicalized team names, with an
optional score cross-check that only disambiguates, never fabricates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

MATCH_WINDOW_SECONDS = 36 * 3600


def kickoff_utc(value: Any) -> datetime | None:
    """Parse provider kickoffs (naive UTC or ISO) into aware UTC datetimes."""

    text = str(value or "")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None


def canonical(value: str, localize: Any) -> str:
    """Collapse provider spellings (English or Chinese) to one match key."""

    first = localize(str(value or "").strip())
    return norm(localize(first)) if first else ""


def norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def team_matches(team: Any, key: str, localize: Any) -> bool:
    if not isinstance(team, Mapping):
        return False
    return any(
        canonical(str(team.get(field) or ""), localize) == key
        for field in ("name", "original_name", "code")
        if team.get(field)
    )


def score_conflicts(row: Mapping[str, Any], home_goals: int | None, away_goals: int | None) -> bool | None:
    """True when both scores exist and disagree; None when unknown."""

    if home_goals is None or away_goals is None:
        return None
    score = row.get("score") if isinstance(row.get("score"), Mapping) else {}
    fixture_home = score.get("home")
    fixture_away = score.get("away")
    if fixture_home is None or fixture_away is None:
        return None
    return not (int(fixture_home) == home_goals and int(fixture_away) == away_goals)


def find_fixture_rows(
    rows: list[dict[str, Any]],
    *,
    kickoff: Any,
    home_title: str,
    away_title: str,
    localize: Any,
    home_goals: int | None = None,
    away_goals: int | None = None,
) -> list[dict[str, Any]]:
    """Every candidate row of one physical match within the date window.

    The same match can exist as parallel rows per provider; callers attach
    metrics to all of them so each canonical history row carries the value.
    """

    start = kickoff_utc(kickoff)
    if start is None:
        return []
    home_key = canonical(home_title, localize)
    away_key = canonical(away_title, localize)
    if not home_key or not away_key:
        return []
    candidates = [
        row
        for row in rows
        if (row_kickoff := kickoff_utc(row.get("kickoff"))) is not None
        and abs((row_kickoff - start).total_seconds()) <= MATCH_WINDOW_SECONDS
        and team_matches(row.get("home_team"), home_key, localize)
        and team_matches(row.get("away_team"), away_key, localize)
    ]
    return [row for row in candidates if score_conflicts(row, home_goals, away_goals) is not True]
