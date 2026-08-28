"""Focused mapping checks for the free team enrichment layer."""

from app.schedule_provider import TheSportsDbProvider


def test_free_team_profile_and_player_mapping_preserves_provenance() -> None:
    profile = TheSportsDbProvider._map_team_profile(
        {
            "strTeam": "Osasuna",
            "strCountry": "Spain",
            "intFormedYear": "1920",
            "strStadium": "Estadio El Sadar",
            "intStadiumCapacity": "18761",
            "strLocation": "Pamplona",
            "strBadge": "https://example.test/osasuna.png",
        }
    )
    player = TheSportsDbProvider._map_player(
        {
            "idPlayer": "123",
            "strPlayer": "Sample Player",
            "strAge": "24",
            "strNumber": "9",
            "strPosition": "Forward",
            "strNationality": "Spain",
        }
    )

    assert profile["original_name"] == "Osasuna"
    assert profile["name"]
    assert profile["founded"] == 1920
    assert profile["capacity"] == 18761
    assert profile["logo"] == "https://example.test/osasuna.png"
    assert player["id"] == 123
    assert player["provider_player_id"] == "123"
    assert player["name"] == "待核验球员"
    assert player["age"] == 24
    assert player["number"] == 9
    assert player["market_value"] is None
