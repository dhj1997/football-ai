"""API-Football mapping and season rules."""

from datetime import date

from app.provider import ApiFootballProvider


def test_season_year_matches_league_calendar() -> None:
    assert ApiFootballProvider.season_for("epl", date(2026, 2, 1)) == 2025
    assert ApiFootballProvider.season_for("laliga", date(2026, 8, 1)) == 2026
    assert ApiFootballProvider.season_for("csl", date(2026, 2, 1)) == 2026


def test_fixture_mapping_preserves_provider_identity_and_status() -> None:
    item = {
        "fixture": {
            "id": 456,
            "date": "2026-08-24T19:30:00+08:00",
            "status": {"short": "NS"},
            "venue": {"name": "Test Stadium"},
        },
        "league": {"id": 39, "name": "Premier League", "country": "England"},
        "teams": {
            "home": {"id": 10, "name": "Home FC", "code": "HOM"},
            "away": {"id": 20, "name": "Away FC", "code": "AWY"},
        },
        "goals": {"home": None, "away": None},
    }

    result = ApiFootballProvider._map_fixture(item, "epl")

    assert result["id"] == "api-456"
    assert result["fixture_date"] == "2026-08-24"
    assert result["status"] == "scheduled"
    assert result["home_team"]["provider_id"] == 10
    assert result["home_team"]["name"] == "Home FC"
    assert result["is_demo"] is False
