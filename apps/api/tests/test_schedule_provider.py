"""TheSportsDB schedule mapping tests."""

from datetime import date

from app.schedule_provider import TheSportsDbProvider


def test_schedule_provider_maps_utc_kickoff_and_score() -> None:
    result = TheSportsDbProvider._map_fixture(
        {
            "idEvent": "789",
            "strTimestamp": "2026-08-24T11:30:00+00:00",
            "strStatus": "Match Finished",
            "strPostponed": "no",
            "strHomeTeam": "Home FC",
            "strAwayTeam": "Away FC",
            "strHomeTeamBadge": "https://r2.thesportsdb.com/home.png",
            "strAwayTeamBadge": "https://r2.thesportsdb.com/away.png",
            "idAPIfootball": "1570342",
            "idHomeTeam": "10",
            "idAwayTeam": "20",
            "intHomeScore": "2",
            "intAwayScore": "1",
            "strVenue": "Test Ground",
        },
        "epl",
    )

    assert result["id"] == "sportsdb-789"
    assert result["fixture_date"] == "2026-08-24"
    assert result["status"] == "finished"
    assert result["score"] == {"home": 2, "away": 1}
    assert result["home_team"]["provider_id"] == 10
    assert result["home_team"]["name"] == "Home FC"
    assert result["home_team"]["original_name"] == "Home FC"
    assert result["home_team"]["logo"] == "https://r2.thesportsdb.com/home.png"
    assert result["away_team"]["logo"] == "https://r2.thesportsdb.com/away.png"
    assert result["external_ids"]["api_football"] == 1570342


def test_schedule_provider_maps_postponed_event_without_score() -> None:
    result = TheSportsDbProvider._map_fixture(
        {
            "idEvent": "790",
            "dateEvent": "2026-08-25",
            "strTime": "19:00:00",
            "strStatus": "Postponed",
            "strPostponed": "yes",
            "strHomeTeam": "Home FC",
            "strAwayTeam": "Away FC",
        },
        "csl",
    )

    assert result["fixture_date"] == "2026-08-25"
    assert result["status"] == "postponed"
    assert result["score"] is None


def test_schedule_provider_groups_late_utc_kickoff_by_beijing_date() -> None:
    result = TheSportsDbProvider._map_fixture(
        {
            "idEvent": "791",
            "strTimestamp": "2026-08-24T19:30:00+00:00",
            "strStatus": "Not Started",
            "strHomeTeam": "Home FC",
            "strAwayTeam": "Away FC",
        },
        "epl",
    )

    assert result["fixture_date"] == "2026-08-25"


def test_schedule_provider_localizes_known_team_names() -> None:
    result = TheSportsDbProvider._map_fixture(
        {
            "idEvent": "792",
            "strTimestamp": "2026-08-24T19:30:00+00:00",
            "strStatus": "Not Started",
            "strHomeTeam": "Fulham",
            "strAwayTeam": "Chelsea",
        },
        "epl",
    )

    assert result["home_team"]["name"] == "富勒姆"
    assert result["away_team"]["name"] == "切尔西"
