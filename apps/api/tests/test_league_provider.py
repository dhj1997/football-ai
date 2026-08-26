from app.league_provider import EspnLeagueProvider


def test_espn_standings_map_current_season_and_table_fields() -> None:
    payload = {
        "season": {
            "year": 2026,
            "displayName": "2026-27 English Premier League",
            "startDate": "2026-06-01T04:00Z",
            "endDate": "2027-06-01T03:59Z",
        },
        "children": [
            {
                "standings": {
                    "entries": [
                        {
                            "team": {
                                "id": "359",
                                "displayName": "Arsenal",
                                "abbreviation": "ARS",
                                "logos": [{"href": "https://example.test/arsenal.png"}],
                            },
                            "stats": [
                                {"name": "rank", "value": 1.0},
                                {"name": "gamesPlayed", "value": 3.0},
                                {"name": "wins", "value": 2.0},
                                {"name": "ties", "value": 1.0},
                                {"name": "losses", "value": 0.0},
                                {"name": "pointsFor", "value": 7.0},
                                {"name": "pointsAgainst", "value": 2.0},
                                {"name": "pointDifferential", "value": 5.0},
                                {"name": "points", "value": 7.0},
                            ],
                            "note": {"description": "Champions League"},
                        }
                    ]
                }
            }
        ],
    }

    result = EspnLeagueProvider._map_standings(
        payload,
        "epl",
        "2026-08-26T00:00:00+00:00",
    )

    assert result["season"]["year"] == 2026
    assert result["season"]["name"] == "2026-27 English Premier League"
    assert result["team_count"] == 1
    assert result["standings"][0] == {
        "rank": 1,
        "team": {
            "provider_id": "359",
            "name": "阿森纳",
            "original_name": "Arsenal",
            "code": "ARS",
            "logo": "https://example.test/arsenal.png",
        },
        "played": 3,
        "wins": 2,
        "draws": 1,
        "losses": 0,
        "goals_for": 7,
        "goals_against": 2,
        "goal_difference": 5,
        "points": 7,
        "note": "Champions League",
    }


def test_espn_standings_reject_empty_current_table() -> None:
    try:
        EspnLeagueProvider._map_standings(
            {"season": {"year": 2026}, "children": []},
            "epl",
            "2026-08-26T00:00:00+00:00",
        )
    except RuntimeError as error:
        assert "no current standings" in str(error)
    else:
        raise AssertionError("empty standings should fail")

