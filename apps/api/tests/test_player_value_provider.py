from datetime import UTC, datetime, timedelta

import pytest

from app.database import PredictionRepository
from app.player_value_provider import (
    NullPlayerValueProvider,
    PlayerValueService,
    parse_dongqiudi_player_value,
)
from app.team_names import to_chinese_player_name


def context() -> dict:
    return {
        "source": "dongqiudi",
        "squads": {
            "home": [
                {
                    "id": "50222265",
                    "provider_player_id": "50222265",
                    "name": "Wei Shihao",
                    "original_name": "Wei Shihao",
                }
            ],
            "away": [],
        },
        "lineup": {"home_players": [], "away_players": []},
        "availability": {"players": []},
    }


@pytest.mark.asyncio
async def test_null_provider_keeps_market_value_missing(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "null-values.db"))
    repository.initialize()
    evidence = context()

    await PlayerValueService(NullPlayerValueProvider(), repository).enrich(evidence, "epl")
    player = evidence["squads"]["home"][0]

    assert player["market_value_eur"] is None
    assert player["market_value_freshness"] == "missing"
    assert evidence["player_value"]["status"] == "unavailable"
    assert evidence["player_value"]["reason"]


def test_dongqiudi_history_is_normalized_with_chinese_name() -> None:
    result = parse_dongqiudi_player_value(
        {
            "base_info": {"person_id": "50222265", "person_name": "Wei Shihao"},
            "history_market_values": {
                "2025": [
                    {
                        "record_date": "2025-06-19",
                        "market_value": 850000,
                        "person_info": {"id": "222265"},
                    },
                    {"record_date": "bad-date", "market_value": 900000},
                ],
                "2026": [{"record_date": "2026-06-08", "market_value": 750000}],
            },
        },
        canonical_player_id="player-1",
        provider_player_id="50222265",
        source_url="https://www.dongqiudi.com/player/50222265",
        captured_at="2026-09-20T00:00:00+00:00",
    )

    assert result is not None
    assert result["player_name"] == to_chinese_player_name("Wei Shihao")
    assert result["market_value_eur"] == 750000
    assert result["market_value_as_of"] == "2026-06-08"
    assert result["provider_player_id"] == "50222265"
    assert result["history"][0]["provider_person_id"] == "222265"
    assert len(result["history"]) == 2


@pytest.mark.asyncio
async def test_enrichment_is_cache_only_and_respects_prediction_cutoff(tmp_path) -> None:
    class Provider:
        configured = True
        source_name = "dongqiudi"
        supported_leagues = frozenset({"epl", "laliga", "csl"})

        def __init__(self) -> None:
            self.calls = 0

        async def fetch_player_value(self, player):
            self.calls += 1
            raise AssertionError("prediction enrichment must not call Dongqiudi")

    repository = PredictionRepository(str(tmp_path / "cutoff-values.db"))
    repository.initialize()
    provider = Provider()
    evidence = context()
    await PlayerValueService(NullPlayerValueProvider(), repository).enrich(evidence, "epl")
    player_id = evidence["squads"]["home"][0]["canonical_player_id"]
    repository.save_player_values(
        [
            {
                "canonical_player_id": player_id,
                "provider_player_id": "50222265",
                "market_value_eur": 20_000_000,
                "market_value_source": "dongqiudi",
                "market_value_as_of": "2026-08-01",
                "cached_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "history": [
                    {
                        "market_value_eur": 10_000_000,
                        "market_value_currency": "EUR",
                        "market_value_source": "dongqiudi",
                        "market_value_as_of": "2026-01-01",
                        "captured_at": "2026-09-20T00:00:00+00:00",
                    },
                    {
                        "market_value_eur": 20_000_000,
                        "market_value_currency": "EUR",
                        "market_value_source": "dongqiudi",
                        "market_value_as_of": "2026-08-01",
                        "captured_at": "2026-09-20T00:00:00+00:00",
                    },
                ],
            }
        ]
    )

    await PlayerValueService(provider, repository).enrich(
        evidence,
        "epl",
        cutoff_at="2026-03-01T00:00:00+00:00",
    )

    player = evidence["squads"]["home"][0]
    assert player["market_value_eur"] == 10_000_000
    assert player["market_value_as_of"] == "2026-01-01"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_stale_cache_does_not_hide_value(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "stale-values.db"))
    repository.initialize()
    evidence = context()
    await PlayerValueService(NullPlayerValueProvider(), repository).enrich(evidence, "epl")
    player_id = evidence["squads"]["home"][0]["canonical_player_id"]
    repository.save_player_values(
        [
            {
                "canonical_player_id": player_id,
                "market_value_eur": 1_000_000,
                "market_value_source": "dongqiudi",
                "market_value_as_of": "2026-01-01",
                "cached_at": (datetime.now(UTC) - timedelta(days=45)).isoformat(),
            }
        ]
    )

    await PlayerValueService(NullPlayerValueProvider(), repository).enrich(evidence, "epl")

    player = evidence["squads"]["home"][0]
    assert player["market_value_eur"] == 1_000_000
    assert player["market_value_status"] == "stale"
