"""Cutoff-safe Elo ratings computed from finished fixtures."""

from typing import Any, Iterable, Mapping

from .league_data_pipeline import normalize_league_code
from .prediction_intelligence import parse_timestamp
from .recent_form import result_available_at

K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
INITIAL_RATING = 1500.0


def compute_elo(
    fixtures: Iterable[dict[str, Any]],
    *,
    as_of: Any | None = None,
) -> dict[str, float]:
    """Iterate finished fixtures (kickoff ascending) and return team -> Elo rating.

    Team identity uses the Chinese display name; teams outside the provided
    history start at INITIAL_RATING and are simply absent from the result until
    they play a match in the window.
    """

    cutoff = parse_timestamp(as_of)
    finished = [
        fixture
        for fixture in fixtures
        if fixture.get("status") == "finished" and (fixture.get("score") or {}).get("home") is not None
        and (
            cutoff is None
            or (
                (available_at := result_available_at(fixture)) is not None
                and available_at <= cutoff
            )
        )
    ]
    finished.sort(key=lambda item: str(item.get("kickoff") or item.get("fixture_date") or ""))
    ratings: dict[str, float] = {}
    for fixture in finished:
        score = fixture["score"]
        home = str(((fixture.get("home_team") or {}).get("name")) or "")
        away = str(((fixture.get("away_team") or {}).get("name")) or "")
        if not home or not away:
            continue
        home_rating = ratings.get(home, INITIAL_RATING)
        away_rating = ratings.get(away, INITIAL_RATING)
        expected_home = 1.0 / (1.0 + 10 ** ((away_rating - home_rating - HOME_ADVANTAGE) / 400.0))
        actual_home = 1.0 if score["home"] > score["away"] else 0.0 if score["home"] < score["away"] else 0.5
        delta = K_FACTOR * (actual_home - expected_home)
        ratings[home] = home_rating + delta
        ratings[away] = away_rating - delta
    return ratings


def expected_goal_shift(home_rating: float, away_rating: float) -> tuple[float, float]:
    """Convert an Elo differential (home advantage included) into xG adjustments."""

    diff = (home_rating + HOME_ADVANTAGE) - away_rating
    shift = max(-1.0, min(1.0, diff / 400.0)) * 0.35
    return (shift, -shift)


def compute_elo_feature_state(
    fixtures: Iterable[Mapping[str, Any]],
    *,
    as_of: Any,
    league: str | None = None,
) -> dict[str, Any]:
    """Return overall/context Elo plus per-fixture pre-match ratings."""

    cutoff = parse_timestamp(as_of)
    if cutoff is None:
        raise ValueError("as_of must be an ISO timestamp")
    target_league = normalize_league_code(league) if league else None
    eligible: list[tuple[Any, str, Mapping[str, Any], Any]] = []
    for fixture in fixtures:
        code = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
        if target_league and code != target_league:
            continue
        status = str(fixture.get("status") or fixture.get("provider_status") or "").casefold()
        score = fixture.get("score") if isinstance(fixture.get("score"), Mapping) else {}
        available_at = result_available_at(fixture)
        kickoff = parse_timestamp(fixture.get("kickoff"))
        fixture_id = str(fixture.get("canonical_fixture_id") or fixture.get("id") or "")
        if (
            status not in {"finished", "ft", "aet", "pen"}
            or score.get("home") is None
            or score.get("away") is None
            or available_at is None
            or available_at > cutoff
            or kickoff is None
            or not fixture_id
        ):
            continue
        eligible.append((kickoff, fixture_id, fixture, available_at))
    eligible.sort(key=lambda item: (item[0], item[1]))

    overall: dict[str, float] = {}
    home_context: dict[str, float] = {}
    away_context: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    available: dict[str, Any] = {}
    pre_match: dict[str, dict[str, float]] = {}
    for _, fixture_id, fixture, available_at in eligible:
        home_id = _team_identifier(fixture.get("home_team"))
        away_id = _team_identifier(fixture.get("away_team"))
        if not home_id or not away_id:
            continue
        home_rating = overall.get(home_id, INITIAL_RATING)
        away_rating = overall.get(away_id, INITIAL_RATING)
        contextual_home = home_context.get(home_id, INITIAL_RATING)
        contextual_away = away_context.get(away_id, INITIAL_RATING)
        pre_match[fixture_id] = {
            "home": home_rating,
            "away": away_rating,
            "home_context": contextual_home,
            "away_context": contextual_away,
        }
        home_score = float(fixture["score"]["home"])
        away_score = float(fixture["score"]["away"])
        actual_home = 1.0 if home_score > away_score else 0.0 if home_score < away_score else 0.5
        delta = K_FACTOR * (actual_home - _expected_home(home_rating, away_rating))
        overall[home_id] = home_rating + delta
        overall[away_id] = away_rating - delta
        context_delta = K_FACTOR * (
            actual_home - _expected_home(contextual_home, contextual_away)
        )
        home_context[home_id] = contextual_home + context_delta
        away_context[away_id] = contextual_away - context_delta
        for team_id in (home_id, away_id):
            sources.setdefault(team_id, []).append(fixture_id)
            previous = available.get(team_id)
            available[team_id] = max(previous, available_at) if previous else available_at

    teams = {
        team_id: {
            "team_elo": round(overall[team_id], 6),
            "home_elo": round(home_context.get(team_id, INITIAL_RATING), 6),
            "away_elo": round(away_context.get(team_id, INITIAL_RATING), 6),
            "source_record_ids": sources.get(team_id, []),
            "available_at": available[team_id].isoformat(),
        }
        for team_id in sorted(overall)
    }
    return {"teams": teams, "pre_match": pre_match, "calculation_version": "elo-feature-v1"}


def _expected_home(home_rating: float, away_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((away_rating - home_rating - HOME_ADVANTAGE) / 400.0))


def _team_identifier(team: Any) -> str | None:
    if not isinstance(team, Mapping):
        return None
    for key in ("canonical_team_id", "provider_id", "id", "source_team_id", "team_id", "code"):
        if team.get(key) not in (None, ""):
            return str(team[key])
    return None
