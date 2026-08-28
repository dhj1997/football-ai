from copy import deepcopy

from app.player_impact import apply_player_impact


def player(
    player_id: str,
    name: str,
    position: str,
    appearances: int,
    substitutes: int,
    minutes: int | None,
    goals: int = 0,
    assists: int = 0,
) -> dict:
    return {
        "id": player_id,
        "provider_player_id": player_id,
        "name": name,
        "original_name": name,
        "position": position,
        "statistics": {
            "appearances": appearances,
            "substitute_appearances": substitutes,
            "minutes": minutes,
            "goals": goals,
            "assists": assists,
        },
        "market_value_eur": None,
    }


def context(absent_ids: list[str]) -> dict:
    home = [
        player("star", "明星前锋", "Forward", 20, 1, 1600, 16, 7),
        player("backup", "替补前锋", "Forward", 10, 9, 310, 1, 1),
        player("edge", "边缘前锋", "Forward", 3, 3, 45),
        player("mid-1", "主力中场一", "Midfielder", 20, 2, 1500, 3, 6),
        player("mid-2", "主力中场二", "Midfielder", 18, 3, 1280, 2, 3),
        player("def-1", "主力后卫一", "Defender", 20, 1, 1650, 1, 1),
        player("def-2", "主力后卫二", "Defender", 18, 2, 1350),
        player("gk", "主力门将", "Goalkeeper", 20, 0, 1800),
    ]
    return {
        "source": "espn-evidence",
        "squads": {"home": home, "away": deepcopy(home)},
        "lineup": {"confirmed": False, "home_players": [], "away_players": []},
        "availability": {
            "players": [
                {
                    "team": "home",
                    "provider_player_id": item,
                    "name": next(row["name"] for row in home if row["id"] == item),
                    "original_name": next(row["name"] for row in home if row["id"] == item),
                    "reason": "伤病",
                }
                for item in absent_ids
            ]
        },
    }


def test_star_forward_absence_has_more_impact_than_edge_player() -> None:
    star_result = apply_player_impact(context(["star"]))["player_impact"]["home"]
    edge_result = apply_player_impact(context(["edge"]))["player_impact"]["home"]

    assert star_result["key_absent_players"][0]["player_role"] == "明星球员"
    assert star_result["key_absent_players"][0]["absence_impact"] > edge_result["key_absent_players"][0]["absence_impact"]
    assert star_result["attack_retention"] < edge_result["attack_retention"]


def test_multiple_edge_absences_do_not_equal_a_key_starter_absence() -> None:
    edge_result = apply_player_impact(context(["backup", "edge"]))["player_impact"]["home"]
    star_result = apply_player_impact(context(["star"]))["player_impact"]["home"]

    edge_impact = sum(item["absence_impact"] for item in edge_result["key_absent_players"])
    star_impact = star_result["key_absent_players"][0]["absence_impact"]
    assert edge_impact < star_impact


def test_defensive_absence_does_not_materially_reduce_attack_when_core_is_available() -> None:
    result = apply_player_impact(context(["def-1"]))["player_impact"]["home"]

    assert result["attack_retention"] >= 0.98
    assert result["defense_retention"] < 1
    assert result["key_available_players"][0]["name"] == "明星前锋"


def test_confirmed_lineup_recomputes_expected_minutes() -> None:
    evidence = context([])
    evidence["lineup"] = {
        "confirmed": True,
        "home_players": [
            {"provider_player_id": "star", "name": "明星前锋", "starter": True},
            {"provider_player_id": "backup", "name": "替补前锋", "starter": False},
        ],
        "away_players": [],
    }

    apply_player_impact(evidence)
    players = {item["provider_player_id"]: item for item in evidence["squads"]["home"]}

    assert players["star"]["expected_start_probability"] == 1
    assert players["star"]["expected_minutes"] == 82
    assert players["backup"]["expected_start_probability"] == 0
    assert players["backup"]["expected_minutes"] == 18
    assert players["edge"]["expected_minutes"] == 0


def test_missing_market_value_stays_null_and_does_not_block_impact() -> None:
    evidence = context(["star"])
    apply_player_impact(evidence)
    star = next(item for item in evidence["squads"]["home"] if item["provider_player_id"] == "star")

    assert star["market_value_eur"] is None
    assert star["attack_contribution"] > 0
    assert evidence["player_impact"]["home"]["data_status"] in {"partial", "complete"}
