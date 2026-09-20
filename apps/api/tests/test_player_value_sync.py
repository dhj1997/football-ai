from datetime import UTC, datetime, timedelta

import pytest

from app.player_value_sync import sync_player_values


class Repository:
    def __init__(self, players, cached=None) -> None:
        kickoff = datetime(2026, 9, 21, tzinfo=UTC).isoformat()
        self.fixtures = [
            {
                "id": "fixture-1",
                "status": "scheduled",
                "league_key": "csl",
                "kickoff": kickoff,
                "free_team_data": {
                    "home": {"squad": players},
                    "away": {"squad": []},
                },
            }
        ]
        self.cached = cached or []
        self.saved = []

    def list_fixtures(self):
        return self.fixtures

    def fixture(self, fixture_id):
        return None

    def team_snapshot(self, league_key, team_id):
        return None

    def player_values(self, canonical_player_ids, as_of=None):
        return [
            item
            for item in self.cached
            if item["canonical_player_id"] in canonical_player_ids
        ]

    def save_player_values(self, values):
        self.saved.extend(values)


class Provider:
    source_name = "dongqiudi"
    request_interval_seconds = 0

    def __init__(self, failing_id=None) -> None:
        self.failing_id = failing_id
        self.calls = []

    async def fetch_player_value(self, player):
        provider_id = player["provider_player_id"]
        self.calls.append(provider_id)
        if provider_id == self.failing_id:
            raise RuntimeError("upstream failed")
        return {
            "canonical_player_id": player["canonical_player_id"],
            "provider_player_id": provider_id,
            "player_name": player["name"],
            "market_value_eur": 1_000_000,
            "market_value_source": "dongqiudi",
            "market_value_as_of": "2026-06-01",
            "cached_at": "2026-09-20T00:00:00+00:00",
        }


def player(player_id: str) -> dict:
    return {
        "id": player_id,
        "provider_player_id": player_id,
        "name": f"球员{player_id}",
        "original_name": f"球员{player_id}",
    }


@pytest.mark.asyncio
async def test_sync_is_bounded_and_keeps_partial_success() -> None:
    repository = Repository([player("1"), player("2"), player("3")])
    provider = Provider(failing_id="2")

    result = await sync_player_values(
        repository,
        provider,
        limit=2,
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert provider.calls == ["1", "2"]
    assert result["status"] == "partial"
    assert result["players_attempted"] == 2
    assert result["players_saved"] == 1
    assert result["players_failed"] == 1
    assert len(repository.saved) == 1


@pytest.mark.asyncio
async def test_sync_skips_fresh_cached_player() -> None:
    repository = Repository([player("1")])
    target_result = await sync_player_values(
        repository,
        Provider(),
        limit=1,
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )
    canonical_id = repository.saved[0]["canonical_player_id"]
    repository.cached = [
        {
            "canonical_player_id": canonical_id,
            "cached_at": (datetime(2026, 9, 20, tzinfo=UTC) - timedelta(days=1)).isoformat(),
        }
    ]
    repository.saved = []
    provider = Provider()

    result = await sync_player_values(
        repository,
        provider,
        limit=1,
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert target_result["players_saved"] == 1
    assert result["players_skipped_fresh"] == 1
    assert result["players_attempted"] == 0
    assert provider.calls == []


@pytest.mark.asyncio
async def test_sync_stops_after_transport_timeout() -> None:
    class ReadTimeout(Exception):
        pass

    class TimeoutProvider(Provider):
        async def fetch_player_value(self, player):
            self.calls.append(player["provider_player_id"])
            raise ReadTimeout("timed out")

    repository = Repository([player("1"), player("2")])
    provider = TimeoutProvider()

    result = await sync_player_values(
        repository,
        provider,
        limit=2,
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert provider.calls == ["1"]
    assert result["status"] == "failed"
    assert result["players_failed"] == 1


@pytest.mark.asyncio
async def test_sync_reuses_unique_team_id_from_other_dongqiudi_fixture() -> None:
    repository = Repository([])
    repository.fixtures.append(
        {
            "id": "dongqiudi-old",
            "status": "finished",
            "league_key": "csl",
            "kickoff": "2026-09-01T00:00:00+00:00",
            "home_team": {"name": "测试客队", "provider_id": "500001"},
            "away_team": {"name": "其他队", "provider_id": "500002"},
        }
    )
    repository.fixtures[0]["away_team"] = {"name": "测试客队"}
    repository.snapshots = {("csl", "500001"): {"roster": [player("9")]}}
    repository.team_snapshot = lambda league_key, team_id: repository.snapshots.get((league_key, team_id))
    provider = Provider()

    result = await sync_player_values(
        repository,
        provider,
        limit=2,
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result["squads_missing"] == 1
    assert result["players_saved"] == 1
    assert provider.calls == ["9"]
