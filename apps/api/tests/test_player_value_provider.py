from datetime import UTC, datetime, timedelta

import pytest

from app.database import PredictionRepository
from app.player_value_provider import NullPlayerValueProvider, PlayerValueService


def context() -> dict:
    return {
        "source": "espn-evidence",
        "squads": {
            "home": [{"id": "1", "name": "测试球员", "original_name": "测试球员"}],
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


@pytest.mark.asyncio
async def test_provider_requires_authorized_three_league_coverage(tmp_path) -> None:
    class UnauthorizedProvider:
        configured = True
        source_name = "unlicensed-test"
        supported_leagues = frozenset({"epl", "laliga"})
        redisplay_authorized = False

        def __init__(self) -> None:
            self.calls = 0

        async def fetch_values(self, canonical_player_ids, league_key):
            self.calls += 1
            return []

    provider = UnauthorizedProvider()
    repository = PredictionRepository(str(tmp_path / "blocked-values.db"))
    repository.initialize()

    await PlayerValueService(provider, repository).enrich(context(), "epl")

    assert provider.calls == 0


@pytest.mark.asyncio
async def test_authorized_value_is_cached_and_can_be_read_without_provider(tmp_path) -> None:
    class LicensedProvider:
        configured = True
        source_name = "licensed-test"
        supported_leagues = frozenset({"epl", "laliga", "csl"})
        redisplay_authorized = True

        async def fetch_values(self, canonical_player_ids, league_key):
            return [
                {
                    "canonical_player_id": canonical_player_ids[0],
                    "market_value_eur": 25_000_000,
                    "market_value_source": self.source_name,
                    "market_value_as_of": datetime.now(UTC).replace(microsecond=0).isoformat(),
                }
            ]

    repository = PredictionRepository(str(tmp_path / "cached-values.db"))
    repository.initialize()
    first = context()
    await PlayerValueService(LicensedProvider(), repository).enrich(first, "epl")
    cached = context()
    await PlayerValueService(NullPlayerValueProvider(), repository).enrich(cached, "epl")

    player = cached["squads"]["home"][0]
    assert player["market_value_eur"] == 25_000_000
    assert player["market_value_source"] == "licensed-test"
    assert player["market_value_freshness"] == "fresh"


@pytest.mark.asyncio
async def test_stale_cached_value_does_not_break_enrichment(tmp_path) -> None:
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
                "market_value_source": "licensed-test",
                "market_value_as_of": (datetime.now(UTC) - timedelta(days=45)).isoformat(),
                "cached_at": datetime.now(UTC).isoformat(),
            }
        ]
    )

    await PlayerValueService(NullPlayerValueProvider(), repository).enrich(evidence, "epl")

    assert evidence["squads"]["home"][0]["market_value_status"] == "stale"
