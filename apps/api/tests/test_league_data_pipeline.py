import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.database import PredictionRepository
from app.league_data_pipeline import (
    HistoricalLeagueDataService,
    P5ProviderRegistry,
    ProviderCapabilities,
    SUPPORTED_LEAGUES,
    build_default_provider_registry,
    canonical_fixture_id,
    canonical_team_id,
    fixture_source_conflicts,
    normalize_fixture_status,
    normalize_league_code,
)
from app.historical_validation import build_raw_data_record


class FakeHistoricalProvider:
    configured = True

    def __init__(self, *, conflict: bool = False, other_league: bool = False, kickoff_shift_minutes: int = 0) -> None:
        self.calls: list[dict] = []
        self.conflict = conflict
        self.other_league = other_league
        self.kickoff_shift_minutes = kickoff_shift_minutes

    async def historical_fixtures(self, league, season, page=1, limit=20, **kwargs):
        self.calls.append({"league": league, "season": season, "page": page, "limit": limit, **kwargs})
        base = (int(page) - 1) * int(limit)
        rows = []
        for index in range(base, base + int(limit)):
            code = "bundesliga" if self.other_league and index == 0 else league
            kickoff = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=index, minutes=self.kickoff_shift_minutes)
            rows.append(
                {
                    "id": f"fixture-{index}",
                    "provider_id": index,
                    "league_key": code,
                    "season": season,
                    "kickoff": kickoff.isoformat(),
                    "home_team": {"provider_id": 100 + index, "name": "FC Barcelona"},
                    "away_team": {"provider_id": 200 + index, "name": "Sevilla"},
                    "status": "FT",
                    "score": {"home": 1, "away": 0},
                    "captured_at": "2024-12-31T00:00:00+00:00",
                }
            )
        return {"items": rows, "has_more": page < 8}

    async def historical_results(self, league, season, page=1, limit=20, **kwargs):
        response = await self.historical_fixtures(league, season, page=page, limit=limit, **kwargs)
        return response

    async def historical_odds(self, **kwargs):
        return {"items": [], "has_more": False}


def _registry(provider: FakeHistoricalProvider, name: str = "fake") -> P5ProviderRegistry:
    registry = P5ProviderRegistry()
    registry.register(
        name,
        provider,
        ProviderCapabilities(tuple(SUPPORTED_LEAGUES), True, True, True, False, False, False, True, True),
        {"fixture": ("fake",)},
    )
    return registry


def test_p5_league_whitelist_and_status_contract() -> None:
    assert set(SUPPORTED_LEAGUES) == {"CSL", "EPL", "LAL"}
    assert normalize_league_code("CSL") == "CSL"
    assert normalize_league_code("Premier League") == "EPL"
    assert normalize_league_code("La Liga") == "LAL"
    assert normalize_league_code("Bundesliga") is None
    assert normalize_fixture_status("PST") == "postponed"
    assert normalize_fixture_status("FT", score={"home": 1, "away": 0}) == "finished"


def test_canonical_fixture_and_team_identity_is_stable_across_aliases() -> None:
    home_a = {"provider_id": 1, "name": "FC Barcelona"}
    home_b = {"provider_id": 9, "name": "Barcelona"}
    team_a = canonical_team_id(home_a, "LAL", 2025)
    team_b = canonical_team_id(home_b, "LAL", 2025)
    assert team_a == team_b
    fixture = {"kickoff": "2025-01-01T18:00:00+00:00"}
    assert canonical_fixture_id(fixture, "LAL", 2025, team_a, canonical_team_id({"provider_id": 2, "name": "Sevilla"}, "LAL", 2025))


def test_fixture_source_conflict_is_recorded() -> None:
    conflicts = fixture_source_conflicts(
        [
            {"source": "a", "league_key": "epl", "season": 2025, "home_team": "A", "away_team": "B", "kickoff": "2025-01-01T10:00:00+00:00", "score": {"home": 1, "away": 0}},
            {"source": "b", "league_key": "epl", "season": 2025, "home_team": "A", "away_team": "B", "kickoff": "2025-01-01T10:30:00+00:00", "score": {"home": 1, "away": 0}},
        ]
    )
    assert conflicts[0]["conflict_type"] == "kickoff_or_result"
    assert conflicts[0]["resolved_value"] is None


def test_raw_payload_hash_is_idempotent_and_versions_changed_payload(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "raw-hash.db"))
    repository.initialize()
    first = build_raw_data_record("fixture", "fake", "fixture-1", {"home": "A"}, "2025-01-01T00:00:00+00:00")
    same = {**first, "captured_at": "2025-01-02T00:00:00+00:00"}
    changed = build_raw_data_record("fixture", "fake", "fixture-1", {"home": "B"}, "2025-01-02T00:00:00+00:00")
    repository.save_raw_data_record(first)
    repository.save_raw_data_record(same)
    repository.save_raw_data_record(changed)
    rows = repository.raw_data_records("fixture")
    assert len(rows) == 2
    assert {row["payload_hash"] for row in rows} == {first["payload_hash"], changed["payload_hash"]}


def test_bounded_fixture_sync_enforces_per_league_and_global_caps(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "caps.db"))
    repository.initialize()
    provider = FakeHistoricalProvider()
    service = HistoricalLeagueDataService(repository, _registry(provider), max_per_league=3, max_total=5, page_size=2)
    first = asyncio.run(service.sync_fixtures("fake", "EPL", 2025, limit=100))
    second = asyncio.run(service.sync_fixtures("fake", "CSL", 2025, limit=100))
    third = asyncio.run(service.sync_fixtures("fake", "LAL", 2025, limit=100))
    coverage = service.coverage()
    assert first["records_inserted"] == 3
    assert second["records_inserted"] == 2
    assert third["status"] == "capped"
    assert coverage["leagues"] == {"CSL": 2, "EPL": 3, "LAL": 0}
    assert coverage["total"] == 3 + 2
    assert all(call["limit"] <= 2 for call in provider.calls)


def test_unsupported_provider_data_is_rejected_without_persistence(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "reject.db"))
    repository.initialize()
    provider = FakeHistoricalProvider(other_league=True)
    service = HistoricalLeagueDataService(repository, _registry(provider), max_per_league=2, page_size=2)
    result = asyncio.run(service.sync_fixtures("fake", "EPL", 2025, limit=2))
    assert result["records_rejected"] == 1
    assert service.coverage()["total"] == 1


def test_multiple_providers_share_one_canonical_fixture_and_record_conflict(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "cross-provider.db"))
    repository.initialize()
    first = HistoricalLeagueDataService(repository, _registry(FakeHistoricalProvider(), "provider-a"), max_per_league=2, page_size=2)
    second = HistoricalLeagueDataService(repository, _registry(FakeHistoricalProvider(kickoff_shift_minutes=30), "provider-b"), max_per_league=2, page_size=2)

    asyncio.run(first.sync_fixtures("provider-a", "EPL", 2025, limit=1))
    asyncio.run(second.sync_fixtures("provider-b", "EPL", 2025, limit=1))

    assert len(repository.list_fixtures(league_key="epl")) == 1
    identities = repository.fixture_identities("EPL")
    assert len(identities) == 2
    assert len({item["canonical_fixture_id"] for item in identities}) == 1
    assert any(item["conflict"] for item in identities)


def test_provider_without_historical_capability_is_unavailable(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "unavailable.db"))
    repository.initialize()
    registry = P5ProviderRegistry()
    registry.register("empty", object(), ProviderCapabilities(tuple(SUPPORTED_LEAGUES), False, False, False, False))
    result = asyncio.run(HistoricalLeagueDataService(repository, registry).sync_fixtures("empty", "EPL", 2025, limit=2))
    assert result["status"] == "unavailable"


def test_default_registry_exposes_real_provider_capabilities() -> None:
    registry = build_default_provider_registry(object(), object(), object())
    names = {item.name for item in registry.descriptors()}
    assert names == {"api-football", "espn", "thesportsdb"}
    assert all(set(item.capabilities.supports_leagues) == set(SUPPORTED_LEAGUES) for item in registry.descriptors())


def test_sync_runs_and_identity_maps_are_idempotent(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "runs.db"))
    repository.initialize()
    provider = FakeHistoricalProvider()
    service = HistoricalLeagueDataService(repository, _registry(provider), max_per_league=2, max_total=10, page_size=2)
    asyncio.run(service.sync_fixtures("fake", "EPL", 2025, limit=2))
    asyncio.run(service.sync_fixtures("fake", "EPL", 2025, limit=2))
    runs = repository.data_sync_runs(provider="fake", league="EPL")
    assert len(runs) == 2
    assert len(repository.fixture_identities("EPL")) == 2
    assert len(repository.team_identities("EPL")) == 4


def test_three_league_history_pipeline_builds_snapshots_without_fake_odds(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "pipeline.db"))
    repository.initialize()
    provider = FakeHistoricalProvider()
    service = HistoricalLeagueDataService(repository, _registry(provider), max_per_league=1, max_total=3, page_size=1)
    results = [
        asyncio.run(service.sync_league_history("fake", code, 2025, start_date="2025-01-01", end_date="2025-01-02", limit=1))
        for code in ("CSL", "EPL", "LAL")
    ]
    assert [item["league"] for item in results] == ["CSL", "EPL", "LAL"]
    assert all(item["odds"]["status"] == "unavailable" for item in results)
    assert repository.historical_snapshots(limit=10)
    assert service.coverage()["total"] == 3
