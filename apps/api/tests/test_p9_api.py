"""P9 HTTP contract tests for competitions and provider health."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p9.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

from app.competition_registry import COMPETITION_REGISTRY
from app.league_sync import LeagueSyncService
from app.main import app, repository


client = TestClient(app)


def test_competitions_contract_exposes_six_competitions_with_capabilities() -> None:
    response = client.get("/api/competitions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 6
    by_key = {item["key"]: item for item in payload["items"]}
    assert set(by_key) == {"csl", "epl", "laliga", "cfa_cup", "ucl", "acl"}
    assert by_key["csl"]["competition_type"] == "league"
    assert by_key["cfa_cup"]["competition_type"] == "knockout"
    assert by_key["ucl"]["competition_type"] == "continental"
    assert by_key["csl"]["capabilities"]["standings"] == "supported"
    assert by_key["cfa_cup"]["capabilities"]["standings"] == "unavailable"
    assert by_key["ucl"]["capabilities"]["historical"] == "unavailable"
    assert by_key["csl"]["capabilities"]["prediction"] == "supported"
    assert by_key["acl"]["capabilities"]["prediction"] == "unavailable"
    for item in payload["items"]:
        assert "fixture_count" in item
        assert "latest_kickoff" in item
        assert "season_policy" in item


def test_provider_health_requires_admin() -> None:
    assert client.get("/api/admin/provider-health").status_code == 401


def test_provider_health_contract_reports_freshness_errors_and_conflicts() -> None:
    started_at = "2026-09-01T08:00:00+00:00"
    repository.save_data_sync_run(
        {
            "run_id": "sync:p9-health-1",
            "provider": "thesportsdb",
            "league": "epl",
            "entity_type": "fixture",
            "started_at": started_at,
            "status": "running",
            "records_seen": 3,
            "records_inserted": 0,
            "records_updated": 0,
            "records_rejected": 0,
        }
    )
    repository.update_data_sync_run(
        "sync:p9-health-1",
        {
            "finished_at": "2026-09-01T08:00:30+00:00",
            "status": "completed",
            "records_inserted": 3,
        },
    )
    repository.save_fixture_conflict(
        {
            "conflict_id": "conflict:p9-health-1",
            "canonical_fixture_id": "fixture:p9health",
            "competition_key": "epl",
            "conflict_type": "kickoff",
            "source_a": "thesportsdb",
            "source_b": "dongqiudi",
            "value_a": "2026-09-01T19:30:00+08:00",
            "value_b": "2026-09-01T21:30:00+08:00",
            "resolution": "configured_source_priority_then_manual_review",
            "resolved": False,
            "detected_at": "2026-09-01T09:00:00+00:00",
        }
    )

    response = client.get("/api/admin/provider-health", headers={"x-admin-key": "dev-admin-key"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_at"]
    assert {item["key"] for item in payload["competitions"]} == {"csl", "epl", "laliga", "cfa_cup", "ucl", "acl"}
    rows = [item for item in payload["providers"] if item["provider"] == "thesportsdb" and item["competition"] == "epl"]
    assert rows and rows[0]["capability"] == "fixture"
    assert rows[0]["success_rate"] == 1.0
    assert rows[0]["avg_latency_seconds"] == 30.0
    assert rows[0]["freshness"] == "2026-09-01T08:00:30+00:00"
    assert rows[0]["conflict_count"] >= 1
    assert payload["conflict_count"] >= 1
    conflict = next(item for item in payload["conflicts"] if item["conflict_id"] == "conflict:p9-health-1")
    assert conflict["conflict_type"] == "kickoff"
    assert conflict["resolved"] is False


class _GateRepository:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def league_snapshots(self) -> list[dict]:
        return self.rows

    def save_league_snapshots(self, rows: list[dict]) -> None:
        self.rows = rows


class _CountingStandingsProvider:
    LEAGUE_SLUGS = {"epl": "eng.1", "laliga": "esp.1", "csl": "chn.1"}
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    async def standings(self) -> list[dict]:
        self.calls += 1
        return [
            {"league_key": key, "updated_at": "2026-09-01T00:00:00+00:00", "season": {"year": 2026}}
            for key in ("epl", "laliga", "csl")
        ]


def test_standings_sync_is_gated_by_competition_capability() -> None:
    import asyncio

    provider = _CountingStandingsProvider()
    service = LeagueSyncService(provider, _GateRepository(), ttl_minutes=360)

    cup = asyncio.run(service.sync_competition("cfa_cup"))
    continental = asyncio.run(service.sync_competition("ucl"))

    assert cup["status"] == "unsupported_capability"
    assert continental["status"] == "unsupported_capability"
    assert provider.calls == 0

    league = asyncio.run(service.sync_competition("csl"))

    assert league["status"] == "updated"
    assert provider.calls == 1


def test_standings_refresh_only_keeps_supported_competitions() -> None:
    import asyncio

    provider = _CountingStandingsProvider()
    gate_repository = _GateRepository()
    service = LeagueSyncService(provider, gate_repository, ttl_minutes=360)

    asyncio.run(service.force_refresh())

    assert sorted(row["league_key"] for row in gate_repository.rows) == ["csl", "epl", "laliga"]
