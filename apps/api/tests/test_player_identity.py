from app.player_identity import link_evidence_players, public_payload


def test_availability_links_to_squad_by_provider_id_and_inherits_evidence() -> None:
    context = {
        "source": "api-football-single-fixture",
        "squads": {
            "home": [
                {
                    "id": 42,
                    "name": "Hugo Duro",
                    "original_name": "Hugo Duro",
                    "position": "Attacker",
                    "age": 26,
                    "statistics": {"appearances": 20, "goals": 9},
                    "market_value_eur": None,
                }
            ],
            "away": [],
        },
        "lineup": {"home_players": [], "away_players": []},
        "availability": {
            "players": [
                {
                    "team": "home",
                    "provider_player_id": "42",
                    "name": "H. Duro",
                    "original_name": "H. Duro",
                    "reason": "伤病",
                }
            ]
        },
    }

    result = link_evidence_players(context)
    injury = result["availability"]["players"][0]

    assert injury["identity_status"] == "resolved"
    assert injury["canonical_player_id"] == result["squads"]["home"][0]["canonical_player_id"]
    assert injury["name"] == "乌戈·杜罗"
    assert injury["position"] == "Attacker"
    assert injury["statistics"]["goals"] == 9


def test_reviewed_abbreviation_links_to_full_squad_name_without_provider_id() -> None:
    context = {
        "source": "api-football-single-fixture",
        "squads": {
            "home": [{"name": "Raúl Asencio", "original_name": "Raúl Asencio", "position": "Defender"}],
            "away": [],
        },
        "lineup": {"home_players": [], "away_players": []},
        "availability": {
            "players": [{"team": "home", "name": "R. Asencio", "original_name": "R. Asencio", "reason": "停赛"}]
        },
    }

    result = link_evidence_players(context)

    assert result["availability"]["players"][0]["identity_status"] == "resolved"
    assert result["availability"]["players"][0]["name"] == "劳尔·阿森西奥"
    assert result["availability"]["unresolved_count"] == 0


def test_unresolved_supplier_name_is_explicit_and_removed_from_public_payload() -> None:
    context = {
        "source": "espn-evidence",
        "squads": {"home": [], "away": []},
        "lineup": {"home_players": [], "away_players": []},
        "availability": {
            "notes": ["Unknown Prospect：Injury"],
            "players": [{"team": "home", "name": "Unknown Prospect", "original_name": "Unknown Prospect", "reason": "伤病"}],
        },
    }

    result = link_evidence_players(context)
    public = public_payload(result)
    injury = public["availability"]["players"][0]

    assert injury["name"].startswith("待核验球员")
    assert injury["identity_status"] == "unresolved"
    assert public["player_identity"]["unresolved_count"] == 1
    assert public["availability"]["notes"] == [f"{injury['name']}：伤病"]
    assert "original_name" not in str(public)
    assert "Unknown Prospect" not in str(public)
