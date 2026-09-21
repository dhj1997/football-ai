"""API-Football mapping and season rules."""

from datetime import date

from app.provider import ApiFootballProvider


def test_season_year_matches_league_calendar() -> None:
    assert ApiFootballProvider.season_for("epl", date(2026, 2, 1)) == 2025
    assert ApiFootballProvider.season_for("laliga", date(2026, 8, 1)) == 2026
    assert ApiFootballProvider.season_for("csl", date(2026, 2, 1)) == 2026
    assert ApiFootballProvider.season_for("cfa_cup", date(2026, 2, 1)) == 2026


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


def test_fixture_mapping_localizes_china_fa_cup_label() -> None:
    item = {
        "fixture": {
            "id": 457,
            "date": "2026-09-01T19:35:00+08:00",
            "status": {"short": "NS"},
            "venue": {"name": "Test Stadium"},
        },
        "league": {"id": 171, "name": "FA Cup", "country": "China"},
        "teams": {
            "home": {"id": 10, "name": "Home FC", "code": "HOM"},
            "away": {"id": 20, "name": "Away FC", "code": "AWY"},
        },
        "goals": {"home": None, "away": None},
    }

    result = ApiFootballProvider._map_fixture(item, "cfa_cup")

    assert result["league_key"] == "cfa_cup"
    assert result["league"]["id"] == 171
    assert result["league"]["name"] == "中国足协杯"


def test_fixture_mapping_adds_national_competition_metadata_and_source_logo() -> None:
    item = {
        "fixture": {
            "id": 458,
            "date": "2026-06-12T19:30:00+08:00",
            "status": {"short": "NS"},
            "venue": {"name": "National Stadium"},
        },
        "league": {"id": 532, "name": "AFC U23 Asian Cup", "country": "Asia"},
        "teams": {
            "home": {"id": 10, "name": "China U23", "code": "CHN"},
            "away": {"id": 20, "name": "Japan U23", "code": "JPN"},
        },
        "goals": {"home": None, "away": None},
    }

    result = ApiFootballProvider._map_fixture(item, "afc_u23_asian_cup")

    assert result["national_competition"]["gender"] == "men"
    assert result["national_competition"]["age_group"] == "u23"
    assert result["league"]["logo"] == "https://media.api-sports.io/football/leagues/532.png"
