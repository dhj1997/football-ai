"""HTTP-level coverage for the assembled fixture workflow."""

import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

TEST_DATABASE = Path("test_football_ai.db")
TEST_DATABASE.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"
os.environ["USE_DEMO_DATA"] = "false"
os.environ["API_DEEPSEEK_KEY"] = ""
os.environ["API_CHATGPT_KEY"] = ""

from fastapi.testclient import TestClient

from app.data import CHINA_TZ, demo_context, demo_fixtures, unavailable_context
from app.main import app, evidence_provider, provider, repository, schedule_provider
from app.prediction import predict
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT


client = TestClient(app)


def seed_real_fixture(fixture_id: str = "api-123", provider_id: int = 123) -> dict:
    """Seed one provider-like fixture into the test cache."""

    fixture = demo_fixtures(datetime.now(CHINA_TZ).date())[0]
    fixture.update(
        {
            "id": fixture_id,
            "provider_id": provider_id,
            "fixture_date": datetime.now(CHINA_TZ).date().isoformat(),
            "kickoff": (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0).isoformat(),
            "is_demo": False,
        }
    )
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    return fixture


def test_fixture_list_and_detail_are_consistent() -> None:
    seed_real_fixture()
    fixture_response = client.get("/api/fixtures", params={"date": "today", "league": "all"})
    assert fixture_response.status_code == 200
    fixture = fixture_response.json()["items"][0]

    detail_response = client.get(f"/api/fixtures/{fixture['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["fixture"]["id"] == fixture["id"]
    assert detail["context"]["odds"] is None
    assert detail["context"]["teams"]["home"]["name"] == fixture["home_team"]["name"]
    assert detail["capabilities"]["evidence_sync"] is provider.configured
    assert detail["prediction"] is None
    assert fixture_response.json()["mode"] == "cached"


def test_public_fixture_payload_removes_supplier_player_names() -> None:
    fixture = seed_real_fixture("api-player-boundary", 127)
    fixture["status"] = "finished"
    context = unavailable_context()
    context["source"] = "espn-evidence"
    context["squads"]["home"] = [
        {
            "id": "supplier-9",
            "name": "Unknown Prospect",
            "original_name": "Unknown Prospect",
            "position": "Forward",
        }
    ]
    context["availability"]["players"] = [
        {
            "team": "home",
            "provider_player_id": "supplier-9",
            "name": "Unknown Prospect",
            "original_name": "Unknown Prospect",
            "reason": "伤病",
        }
    ]
    fixture["evidence"] = context
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        datetime.now(UTC).replace(microsecond=0).isoformat(),
    )

    detail = client.get(f"/api/fixtures/{fixture['id']}").json()
    serialized = str(detail)
    injury = detail["context"]["availability"]["players"][0]

    assert "original_name" not in serialized
    assert "Unknown Prospect" not in serialized
    assert injury["name"].startswith("待核验球员")
    assert injury["name"].endswith("）")
    assert injury["identity_status"] == "resolved"
    assert injury["canonical_player_id"]
    assert injury["provider_player_id"] == "supplier-9"


def test_fixture_detail_auto_syncs_evidence(monkeypatch) -> None:
    fixture = seed_real_fixture("api-auto-evidence", 125)
    fixture["status"] = "scheduled"
    fixture["external_ids"] = {"api_football": 123}
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        "2026-08-24T10:00:00+00:00",
    )
    context = unavailable_context()
    context["synced_at"] = "2026-08-24T11:00:00+00:00"
    context["source"] = "test"

    async def fake_fetch(_fixture):
        return context

    monkeypatch.setattr(evidence_provider, "fetch", fake_fetch)
    response = client.get(f"/api/fixtures/{fixture['id']}")

    assert response.status_code == 200
    assert response.json()["context"]["synced_at"] == context["synced_at"]
    assert repository.fixture(fixture["id"])["evidence"]["source"] == "test"
    assert response.json()["prediction"] is None
    assert repository.latest(fixture["id"], "deepseek", response.json()["competition_id"]) is None
    second_response = client.get(f"/api/fixtures/{fixture['id']}")
    assert second_response.json()["prediction"] is None


def test_fixture_detail_enriches_incomplete_recent_form_from_secondary(monkeypatch) -> None:
    fixture = seed_real_fixture("api-secondary-refresh", 126)
    fixture["status"] = "scheduled"
    existing = unavailable_context()
    existing["source"] = "api-football-single-fixture"
    existing["recent_form"] = {"home": [{"result": "D"}], "away": [{"result": "D"}]}
    repository.save_fixture_evidence(fixture["id"], existing)
    incoming = unavailable_context()
    incoming["source"] = "espn-evidence"
    incoming["synced_at"] = "2026-08-26T02:00:00+00:00"
    incoming["recent_form"] = {"home": [{"result": "W"}] * 5, "away": [{"result": "L"}] * 5}

    async def fake_secondary(_fixture):
        return incoming

    monkeypatch.setattr(evidence_provider, "fetch_secondary", fake_secondary)
    response = client.get(f"/api/fixtures/{fixture['id']}")

    assert response.status_code == 200
    assert len(response.json()["context"]["recent_form"]["home"]) == 5
    assert repository.fixture(fixture["id"])["evidence"]["source"] == "api-football-single-fixture+espn-evidence"


def test_prediction_requires_admin_key() -> None:
    seed_real_fixture()
    response = client.post("/api/admin/fixtures/api-123/predictions")
    assert response.status_code == 401


def test_fixture_detail_never_falls_back_to_legacy_prediction_bet() -> None:
    fixture = seed_real_fixture("api-current-only", 128)
    fixture["status"] = "finished"
    fixture["score"] = {"home": 2, "away": 0}
    context = demo_context(fixture["id"])
    fixture["evidence"] = context
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    current = predict(fixture, context)
    current.update(
        {
            "id": "current-only-v3",
            "fixture_id": fixture["id"],
            "created_at": "2026-08-27T02:00:00+00:00",
            "model_key": "deepseek",
            "competition_id": repository.competition_id,
            "ai": {
                "status": "completed",
                "provider": "deepseek",
                "requested_model": "test",
                "returned_model": "test",
                "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
                "request_id": "current",
                "usage": None,
                "error": None,
            },
        }
    )
    legacy = deepcopy(current)
    legacy.update({"id": "current-only-v2", "created_at": "2026-08-27T01:00:00+00:00"})
    legacy["ai"] = {**legacy["ai"], "prompt_version": "football-forecast-v2", "request_id": "legacy"}
    repository.save(legacy)
    repository.save(current)
    repository.place_bet(
        {
            "id": "legacy-only-bet",
            "prediction_id": legacy["id"],
            "fixture_id": fixture["id"],
            "fixture_date": fixture["fixture_date"],
            "placed_at": "2026-08-27T01:05:00+00:00",
            "market": "1x2",
            "selection": "home",
            "handicap_line": None,
            "odds": 1.27,
            "stake": 1.0,
            "league_key": fixture["league_key"],
            "kickoff": fixture["kickoff"],
            "home_team": fixture["home_team"]["name"],
            "away_team": fixture["away_team"]["name"],
            "model_version": legacy["model_version"],
            "is_simulated": True,
            "model_key": "deepseek",
            "competition_id": repository.competition_id,
        }
    )

    response = client.get(f"/api/fixtures/{fixture['id']}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["predictions"]["deepseek"]["id"] == current["id"]
    assert detail["predictions"]["deepseek"]["decision"]["status"] == "no_bet"
    assert detail["predictions"]["deepseek"]["execution"]["status"] == "no_bet"
    assert detail["predictions"]["deepseek"]["execution"]["reason_codes"]
    assert detail["bets"]["deepseek"] is None
    assert detail["bet"] is None


def test_prediction_retention_admin_endpoints_require_key() -> None:
    assert client.get("/api/admin/prediction-retention/preview").status_code == 401
    assert client.post("/api/admin/prediction-retention/run").status_code == 401


def test_simulated_bankroll_and_empty_metrics_are_public() -> None:
    bankroll_response = client.get("/api/bankroll")
    metrics_response = client.get("/api/metrics/predictions")

    assert bankroll_response.status_code == 200
    assert bankroll_response.json()["initial_balance"] == 1000.0
    assert bankroll_response.json()["is_simulated"] is True
    assert metrics_response.status_code == 200
    assert metrics_response.json()["sample_size"] == 0


def test_unfinished_fixture_cannot_be_settled() -> None:
    seed_real_fixture()
    response = client.post(
        "/api/admin/fixtures/api-123/settle",
        headers={"x-admin-key": "dev-admin-key"},
    )

    assert response.status_code == 409


def test_real_fixture_requires_synced_evidence() -> None:
    fixture = seed_real_fixture("api-no-evidence", 124)
    response = client.post(
        f"/api/admin/fixtures/{fixture['id']}/predictions",
        headers={"x-admin-key": "dev-admin-key"},
    )
    assert response.status_code == 409
    assert "同步这场比赛的真实赛前数据" in response.json()["detail"]


def test_sync_requires_provider_key() -> None:
    original_key = schedule_provider.api_key
    schedule_provider.api_key = ""
    try:
        response = client.post("/api/admin/sync", headers={"x-admin-key": "dev-admin-key"})
        assert response.status_code == 409
    finally:
        schedule_provider.api_key = original_key


def test_sync_persists_provider_fixtures(monkeypatch) -> None:
    synced_fixture = seed_real_fixture()

    async def fake_fixtures(start_date, end_date):
        assert start_date < end_date
        return [synced_fixture]

    monkeypatch.setattr(schedule_provider, "fixtures", fake_fixtures)
    response = client.post("/api/admin/sync", headers={"x-admin-key": "dev-admin-key"})

    assert response.status_code == 200
    assert response.json()["item_count"] == 1
    assert response.json()["request_count"] == 9
    assert repository.fixture("api-123") is not None
