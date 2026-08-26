import pytest

from app.espn_evidence_provider import EspnEvidenceProvider, _head_to_head, _matches_fixture, _odds, _recent_form


def fixture() -> dict:
    return {
        "fixture_date": "2026-08-26",
        "kickoff": "2026-08-25T19:00:00+00:00",
        "league_key": "laliga",
        "home_team": {"name": "瓦伦西亚", "original_name": "Valencia"},
        "away_team": {"name": "皇家贝蒂斯", "original_name": "Real Betis"},
        "external_ids": {},
    }


def event() -> dict:
    return {
        "id": "401882917",
        "date": "2026-08-25T19:00Z",
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"id": "94", "displayName": "Valencia"}},
                    {"homeAway": "away", "team": {"id": "244", "displayName": "Real Betis"}},
                ]
            }
        ],
    }


def test_event_matching_accepts_espn_team_names() -> None:
    assert _matches_fixture(event(), fixture()) is True


def test_recent_form_and_h2h_map_espn_summary_shapes() -> None:
    blocks = [
        {
            "team": {"id": "94", "displayName": "Valencia"},
            "events": [
                {
                    "gameDate": "2026-05-17T17:00Z",
                    "homeTeamId": "89",
                    "awayTeamId": "94",
                    "homeTeamScore": "3",
                    "awayTeamScore": "4",
                    "gameResult": "W",
                    "opponent": {"displayName": "Real Sociedad"},
                }
            ],
        },
        {
            "team": {"id": "244", "displayName": "Real Betis"},
            "events": [
                {
                    "gameDate": "2026-05-16T17:00Z",
                    "homeTeamId": "244",
                    "awayTeamId": "89",
                    "homeTeamScore": "2",
                    "awayTeamScore": "0",
                    "gameResult": "W",
                    "opponent": {"displayName": "Real Sociedad"},
                }
            ],
        },
    ]
    form = _recent_form(blocks, "94", "244", "2026-08-26T00:00:00+00:00")
    h2h = _head_to_head([{"type": "head-to-head", "events": [
        {"date": "2026-02-01T19:00Z", "competitors": [
            {"homeAway": "home", "team": {"displayName": "Valencia"}, "score": "1"},
            {"homeAway": "away", "team": {"displayName": "Real Betis"}, "score": "0"},
        ]}
    ]}])

    assert form["home"][0]["result"] == "W"
    assert form["home"][0]["team_is_home"] is False
    assert form["home_points_per_game"] == 3.0
    assert h2h[0]["score"] == "1 - 0"


def test_espn_odds_convert_american_lines_to_decimal() -> None:
    result = _odds(
        [{
            "provider": {"name": "Test Book"},
            "spread": -0.5,
            "homeTeamOdds": {"moneyLine": 170, "spreadOdds": 155},
            "drawOdds": {"moneyLine": 225},
            "awayTeamOdds": {"moneyLine": 170, "spreadOdds": -215},
        }],
        "2026-08-26T00:00:00+00:00",
    )

    assert result["bookmaker"] == "Test Book"
    assert result["home"] == 2.7
    assert result["draw"] == 3.25
    assert result["away"] == 2.7
    assert result["asian_handicap"] == -0.5


@pytest.mark.asyncio
async def test_espn_fetch_maps_summary_and_roster_payloads(monkeypatch) -> None:
    provider = EspnEvidenceProvider("https://example.test")
    summary = {
        "header": {
            "id": "401882917",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "id": "94", "team": {"id": "94", "displayName": "Valencia"}},
                    {"homeAway": "away", "id": "244", "team": {"id": "244", "displayName": "Real Betis"}},
                ]
            }],
        },
        "lastFiveGames": [],
        "seasonseries": [],
        "rosters": [
            {"homeAway": "home", "roster": [{"starter": True, "jersey": "9", "athlete": {"id": "1", "displayName": "Home Player"}, "position": {"abbreviation": "F"}}]},
            {"homeAway": "away", "roster": [{"starter": True, "jersey": "1", "athlete": {"id": "2", "displayName": "Away Player"}, "position": {"abbreviation": "G"}}]},
        ],
        "odds": [],
    }

    async def fake_find(_client, _fixture, _slug):
        return event()

    async def fake_get(_client, path, params=None):
        if path.endswith("/summary"):
            return summary
        raise AssertionError(f"unexpected required endpoint: {path}")

    async def fake_optional(_client, path):
        if path.endswith("/94/roster"):
            return {"team": {"id": "94", "displayName": "Valencia"}, "athletes": [{"id": "1", "displayName": "Home Player", "position": {"abbreviation": "F"}}]}, None
        return {"team": {"id": "244", "displayName": "Real Betis"}, "athletes": [{"id": "2", "displayName": "Away Player", "position": {"abbreviation": "G"}}]}, None

    monkeypatch.setattr(provider, "_find_event", fake_find)
    monkeypatch.setattr(provider, "_get", fake_get)
    monkeypatch.setattr(provider, "_optional_get", fake_optional)

    result = await provider.fetch(fixture())

    assert result["source"] == "espn-evidence"
    assert result["espn_event_id"] == "401882917"
    assert result["lineup"]["confirmed"] is True
    assert len(result["squads"]["home"]) == 1
    assert result["availability"]["players"] == []
