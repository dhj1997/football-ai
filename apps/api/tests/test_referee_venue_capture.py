"""Referee and venue capture from ESPN / API-Football evidence payloads."""

from app.espn_evidence_provider import _referee as espn_referee
from app.espn_evidence_provider import _venue_info as espn_venue
from app.evidence_provider import _referee as apifootball_referee


def test_espn_referee_picks_the_referee_official() -> None:
    game_info = {
        "officials": [
            {"fullName": "Assistant One", "position": {"name": "Assistant"}},
            {"fullName": "Jarred Gillett", "position": {"name": "Referee"}},
        ]
    }

    referee = espn_referee(game_info, "2026-09-19T00:00:00+00:00")

    assert referee == {"name": "Jarred Gillett", "source": "espn", "captured_at": "2026-09-19T00:00:00+00:00"}
    assert espn_referee({"officials": []}, "2026-09-19T00:00:00+00:00") is None


def test_espn_venue_info_maps_address_for_geocoding() -> None:
    venue = espn_venue(
        {
            "venue": {
                "fullName": "Vitality Stadium",
                "address": {"city": "Bournemouth", "country": "England"},
            }
        }
    )

    assert venue == {"name": "Vitality Stadium", "city": "Bournemouth", "country": "England", "source": "espn"}
    assert espn_venue({}) is None


def test_apifootball_referee_maps_fixture_field() -> None:
    item = {"fixture": {"referee": "Michael Oliver"}}
    referee = apifootball_referee(item, "2026-09-19T00:00:00+00:00")

    assert referee == {"name": "Michael Oliver", "source": "api-football", "captured_at": "2026-09-19T00:00:00+00:00"}
    assert apifootball_referee({"fixture": {}}, "2026-09-19T00:00:00+00:00") is None
