from app.team_provider import EspnTeamProvider


def test_maps_current_team_roster_statistics_and_match_record() -> None:
    roster = {
        "season": {"year": 2026, "displayName": "2026-27 English Premier League"},
        "team": {
            "id": "359",
            "displayName": "Arsenal",
            "abbreviation": "ARS",
            "logo": "https://example.test/arsenal.png",
            "standingSummary": "2nd in English Premier League",
        },
        "coach": [{"firstName": "Mikel", "lastName": "Arteta"}],
        "athletes": [
            {
                "id": "42",
                "fullName": "Test Player",
                "jersey": "9",
                "age": 24,
                "citizenship": "England",
                "position": {"displayName": "Forward", "abbreviation": "F"},
                "status": {"name": "Active"},
                "injuries": [],
                "statistics": {
                    "splits": {
                        "categories": [
                            {
                                "stats": [
                                    {"name": "appearances", "value": 3},
                                    {"name": "totalGoals", "value": 2},
                                    {"name": "goalAssists", "value": 1},
                                ]
                            }
                        ]
                    }
                },
            }
        ],
    }
    schedule = {
        "events": [
            {
                "id": "match-1",
                "date": "2026-08-22T14:00Z",
                "competitions": [
                    {
                        "competitors": [
                            {
                                "id": "359",
                                "homeAway": "home",
                                "team": {"id": "359", "displayName": "Arsenal"},
                                "score": {"value": 3},
                            },
                            {
                                "id": "388",
                                "homeAway": "away",
                                "team": {"id": "388", "displayName": "Coventry City"},
                                "score": {"value": 0},
                            },
                        ],
                        "status": {"type": {"state": "post", "completed": True, "shortDetail": "FT"}},
                    }
                ],
            }
        ]
    }

    result = EspnTeamProvider._map_team(
        roster,
        schedule,
        "epl",
        "359",
        "2026-08-26T00:00:00+00:00",
    )

    assert result["season"]["year"] == 2026
    assert result["coach"]["name"] == "Mikel Arteta"
    assert result["roster_count"] == 1
    assert result["roster"][0]["statistics"] == {
        "appearances": 3,
        "substitute_appearances": 0,
        "starts": None,
        "minutes": None,
        "goals": 2,
        "assists": 1,
        "yellow_cards": 0,
        "red_cards": 0,
        "saves": 0,
        "goals_conceded": 0,
    }
    assert result["matches"][0]["result"] == "W"
    assert result["matches"][0]["home_score"] == 3


def test_rejects_incomplete_team_payload() -> None:
    try:
        EspnTeamProvider._map_team({}, {}, "epl", "359", "2026-08-26T00:00:00+00:00")
    except RuntimeError as error:
        assert "incomplete team data" in str(error)
    else:
        raise AssertionError("incomplete team data should fail")
