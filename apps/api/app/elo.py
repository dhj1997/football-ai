"""Elo ratings computed from finished fixtures, injected into the baseline prior."""

from typing import Any, Iterable

K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
INITIAL_RATING = 1500.0


def compute_elo(fixtures: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Iterate finished fixtures (kickoff ascending) and return team -> Elo rating.

    Team identity uses the Chinese display name; teams outside the provided
    history start at INITIAL_RATING and are simply absent from the result until
    they play a match in the window.
    """

    finished = [
        fixture
        for fixture in fixtures
        if fixture.get("status") == "finished" and (fixture.get("score") or {}).get("home") is not None
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
