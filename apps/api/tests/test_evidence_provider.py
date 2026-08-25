"""API-Football evidence mapping tests."""

from app.evidence_provider import _availability, _lineup, _odds, _recent_form, _squad, _team_profile


def test_odds_maps_nested_bookmakers_and_asian_handicap() -> None:
    context = _odds(
        {
            "response": [
                {
                    "bookmakers": [
                        {
                            "name": "Test Book",
                            "bets": [
                                {
                                    "id": 1,
                                    "values": [
                                        {"value": "Home", "odd": "2.68"},
                                        {"value": "Draw", "odd": "3.30"},
                                        {"value": "Away", "odd": "2.52"},
                                    ],
                                },
                                {
                                    "id": 4,
                                    "values": [{"value": "Home -0.5", "odd": "2.62"}],
                                },
                            ],
                        }
                    ]
                }
            ]
        },
        "2026-08-25T09:00:00+00:00",
    )

    assert context == {
        "bookmaker": "Test Book",
        "home": 2.68,
        "draw": 3.3,
        "away": 2.52,
        "asian_handicap": -0.5,
        "updated_at": "2026-08-25T09:00:00+00:00",
        "is_demo": False,
    }


def test_recent_form_maps_public_event_scores_to_team_results() -> None:
    context = _recent_form(
        {"response": [{"teams": {"home": {"league": {}}, "away": {"league": {}}}}]},
        {
            "home": [
                {
                    "dateEvent": "2026-08-22",
                    "idHomeTeam": "10",
                    "strHomeTeam": "Valencia",
                    "strAwayTeam": "Celta Vigo",
                    "intHomeScore": "2",
                    "intAwayScore": "1",
                }
            ],
            "away": [],
        },
        "10",
        "20",
    )

    assert context["home"][0]["result"] == "W"
    assert context["home"][0]["score"] == "2 - 1"
    assert context["home"][0]["team_is_home"] is True


def test_lineup_and_availability_keep_player_details() -> None:
    lineup = _lineup(
        {
            "response": [
                {
                    "team": {"id": 10},
                    "formation": "4-3-3",
                    "startXI": [{"player": {"name": "Home Player", "number": 9, "pos": "F"}}],
                    "substitutes": [],
                },
                {
                    "team": {"id": 20},
                    "formation": "4-4-2",
                    "startXI": [{"player": {"name": "Away Player", "number": 1, "pos": "G"}}],
                    "substitutes": [],
                },
            ]
        },
        10,
        20,
        "2026-08-25T09:00:00+00:00",
    )
    availability = _availability(
        {"response": [{"team": {"id": 10}, "player": {"name": "Hugo Duro", "reason": "Injury"}}]},
        10,
        20,
        "2026-08-25T09:00:00+00:00",
    )

    assert lineup["confirmed"] is True
    assert lineup["home_players"][0]["name"] == "Home Player"
    assert availability["players"][0]["name"] == "乌戈·杜罗"


def test_squad_merges_chinese_aliases_and_keeps_value_unknown() -> None:
    squad = _squad(
        {"response": [{"players": [{"id": 47264, "name": "Hugo Duro", "age": 26, "number": 9, "position": "Attacker", "nationality": "Spain", "photo": "photo"}]}]},
        [{"idAPIfootball": "47264", "strPlayer": "Hugo Duro", "idTransferMkt": "123"}],
    )
    assert squad[0]["name"] == "乌戈·杜罗"
    assert squad[0]["market_value"] is None
    assert squad[0]["transfermarkt_id"] == "123"


def test_team_profile_maps_stadium_and_capacity() -> None:
    profile = _team_profile(
        {"team": {"strBadge": "badge", "strStadium": "Mestalla", "intStadiumCapacity": "55000"}},
        {"name": "Valencia", "logo": "logo", "country": "Spain", "founded": 1919, "venue": {"name": "Estadio de Mestalla", "capacity": 55000, "city": "Valencia"}},
        {"name": "瓦伦西亚"},
    )
    assert profile["name"] == "瓦伦西亚"
    assert profile["capacity"] == 55000
