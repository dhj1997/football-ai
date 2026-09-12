"""HTTP-level coverage for the assembled fixture workflow."""

import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

TEST_DATABASE = Path("test_football_ai.db")
TEST_DATABASE.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"
os.environ["USE_DEMO_DATA"] = "false"
os.environ["DEEPSEEK_ENABLED"] = "true"
os.environ["API_DEEPSEEK_KEY"] = ""
os.environ["API_CHATGPT_KEY"] = ""

from fastapi.testclient import TestClient

from app.data import CHINA_TZ, demo_context, demo_fixtures, unavailable_context
from app.main import app, deepseek_provider, evidence_provider, player_name_service, repository, schedule_provider, schedule_sync, settings
from app.prediction import predict
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT


client = TestClient(app)


def test_runtime_model_config_requires_admin_and_updates_in_process() -> None:
    assert client.get("/api/admin/model-config").status_code == 401
    original_model = deepseek_provider.model
    original_min_edge = settings.portfolio_min_edge
    try:
        response = client.put(
            "/api/admin/model-config",
            headers={"x-admin-key": "dev-admin-key"},
            json={"models": {"deepseek": {"model": "deepseek-test-model"}}, "portfolio": {"min_edge": 0.12}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["deepseek"]["model"] == "deepseek-test-model"
        assert payload["portfolio"]["min_edge"] == 0.12
        assert deepseek_provider.model == "deepseek-test-model"
        assert settings.portfolio_min_edge == 0.12
    finally:
        client.put(
            "/api/admin/model-config",
            headers={"x-admin-key": "dev-admin-key"},
            json={"models": {"deepseek": {"model": original_model}}, "portfolio": {"min_edge": original_min_edge}},
        )


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
    assert detail["capabilities"]["evidence_sync"] is schedule_provider.configured
    assert detail["capabilities"]["evidence_sources"] == ["thesportsdb-partial", "dongqiudi"]
    assert detail["prediction"] is None
    assert fixture_response.json()["mode"] == "cached"


def test_fixture_list_supports_yesterday_and_upcoming_with_compact_summary(monkeypatch) -> None:
    today = datetime.now(CHINA_TZ).date()
    fixtures = []
    for offset in (-1, 0, 6, 7):
        fixture = demo_fixtures(today)[0]
        fixture_id = f"api-date-window-{offset}"
        kickoff = datetime.combine(today + timedelta(days=offset), datetime.min.time(), tzinfo=CHINA_TZ)
        context = demo_context(fixture_id)
        context["teams"] = {"home": {"name": "主队"}, "away": {"name": "客队"}}
        fixture.update(
            {
                "id": fixture_id,
                "provider_id": 8100 + offset,
                "fixture_date": (today + timedelta(days=offset)).isoformat(),
                "kickoff": kickoff.isoformat(),
                "is_demo": False,
                "evidence": context,
            }
        )
        repository.upsert_fixture(fixture)
        fixtures.append(fixture)

    requested_windows: list[tuple[str | None, str | None]] = []

    def cached_fixtures(start_date: str | None, end_date: str | None) -> list[dict]:
        requested_windows.append((start_date, end_date))
        return [
            fixture
            for fixture in fixtures
            if (start_date is None or fixture["fixture_date"] >= start_date)
            and (end_date is None or fixture["fixture_date"] <= end_date)
        ]

    monkeypatch.setattr(schedule_sync, "cached_fixtures", cached_fixtures)
    monkeypatch.setattr(schedule_sync, "cached_state", lambda: {"status": "fresh"})

    prediction = predict(fixtures[1], fixtures[1]["evidence"])
    prediction.update(
        {
            "id": "api-date-window-prediction",
            "model_key": "deepseek",
            "competition_id": repository.competition_id,
            "ai": {"status": "completed", "provider": "deepseek", "prompt_version": DEFAULT_PROMPT_CONTRACT.version},
        }
    )
    repository.save(prediction)

    yesterday = client.get("/api/fixtures", params={"date": "yesterday", "league": "all"})
    upcoming = client.get("/api/fixtures", params={"date": "upcoming", "league": "all"})

    assert yesterday.status_code == 200
    assert "api-date-window--1" in {item["id"] for item in yesterday.json()["items"]}
    assert upcoming.status_code == 200
    assert requested_windows == [
        ((today - timedelta(days=1)).isoformat(), (today - timedelta(days=1)).isoformat()),
        (today.isoformat(), (today + timedelta(days=6)).isoformat()),
    ]
    upcoming_items = {item["id"]: item for item in upcoming.json()["items"]}
    assert {"api-date-window-0", "api-date-window-6"} <= set(upcoming_items)
    assert "api-date-window-7" not in upcoming_items
    summary_item = upcoming_items["api-date-window-0"]
    assert summary_item["fixture_date"] == fixtures[1]["fixture_date"]
    assert "evidence" not in summary_item
    assert summary_item["evidence_summary"] == {
        "ready_count": 4,
        "total_count": 4,
        "missing": [],
        "updated_at": fixtures[1]["evidence"]["availability"]["updated_at"],
    }
    assert summary_item["has_prediction"] is True


def test_fixture_list_accepts_china_fa_cup_filter() -> None:
    fixture = seed_real_fixture("sportsdb-fa-cup", 124)
    fixture.update(
        {
            "league_key": "cfa_cup",
            "league": {"id": 5525, "name": "中国足协杯", "country": "中国", "mark": "CFA"},
        }
    )
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        datetime.now(UTC).replace(microsecond=0).isoformat(),
    )

    response = client.get("/api/fixtures", params={"date": "today", "league": "中国足协杯"})

    assert response.status_code == 200
    assert [item["league_key"] for item in response.json()["items"]] == ["cfa_cup"]


def test_p3_intelligence_endpoints_return_read_only_contracts() -> None:
    assert client.get("/api/model-performance").status_code == 200
    assert client.get("/api/features").status_code == 200
    assert client.get("/api/calibration").status_code == 200
    assert client.get("/api/backtest").status_code == 200
    assert client.get("/api/ensemble/missing-fixture").status_code == 404
    assert client.get("/api/data-quality").status_code == 200
    assert client.get("/api/historical-snapshots").status_code == 200
    assert client.get("/api/backtest/runs").status_code == 200
    assert client.get("/api/backtest/runs/missing-run").status_code == 404


def test_p5_data_registry_and_history_endpoints_are_read_only() -> None:
    sources = client.get("/api/data-sources")
    assert sources.status_code == 200
    assert {item["provider"] for item in sources.json()["providers"]} == {"api-football", "espn", "thesportsdb"}

    leagues_response = client.get("/api/leagues")
    assert leagues_response.status_code == 200
    assert [item["code"] for item in leagues_response.json()["items"]] == ["CSL", "EPL", "LAL"]

    assert client.get("/api/data-sync/runs").status_code == 200
    assert client.get("/api/fixtures/history", params={"league": "EPL", "season": "2025"}).status_code == 200
    assert client.get("/api/fixtures", params={"league": "EPL", "season": "2025", "date_from": "2025-01-01", "date_to": "2025-01-31"}).status_code == 200
    assert client.get("/api/data-quality", params={"league": "EPL"}).status_code == 200
    assert client.get("/api/fixtures/history", params={"league": "Bundesliga"}).status_code == 400


def test_p7_team_form_endpoint_honors_as_of_and_window() -> None:
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)
    for index in range(1, 18):
        kickoff = cutoff - timedelta(days=index)
        repository.upsert_fixture(
            {
                "id": f"p7-form-{index}",
                "canonical_fixture_id": f"p7-canonical-{index}",
                "provider_id": 9000 + index,
                "league_key": "epl",
                "canonical_league": "EPL",
                "season": "2025",
                "fixture_date": kickoff.date().isoformat(),
                "kickoff": kickoff.isoformat(),
                "status": "finished",
                "home_team": {"provider_id": 5001, "name": "Home FC"},
                "away_team": {"provider_id": 5002, "name": "Away FC"},
                "score": {"home": 1, "away": 0},
                "is_demo": False,
            }
        )
    repository.upsert_fixture(
        {
            "id": "p7-form-future",
            "canonical_fixture_id": "p7-canonical-future",
            "provider_id": 9999,
            "league_key": "epl",
            "canonical_league": "EPL",
            "season": "2025",
            "fixture_date": (cutoff + timedelta(days=1)).date().isoformat(),
            "kickoff": (cutoff + timedelta(days=1)).isoformat(),
            "status": "finished",
            "home_team": {"provider_id": 5001, "name": "Home FC"},
            "away_team": {"provider_id": 5002, "name": "Away FC"},
            "score": {"home": 9, "away": 0},
            "is_demo": False,
        }
    )

    response = client.get(
        "/api/team-form/5001",
        params={"league": "EPL", "as_of": cutoff.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches_used"] == 15
    assert payload["sample_status"] == "ok"
    assert all(item["date"] <= cutoff.isoformat() for item in payload["matches"])
    assert payload["form"]["wins"] == 15


def test_p6_evaluation_endpoints_return_frozen_insufficient_report() -> None:
    evaluation = client.get("/api/model-evaluation")
    assert evaluation.status_code == 200
    payload = evaluation.json()
    assert payload["status"] == "insufficient_sample"
    assert payload["test_set"]["frozen"] is True
    assert set(payload["reports"]) == {"CSL", "EPL", "LAL", "GLOBAL"}
    experiment_id = payload["experiment_id"]

    assert client.get(f"/api/model-evaluation/{experiment_id}").status_code == 200
    comparison = client.get("/api/model-comparison")
    assert comparison.status_code == 200
    assert comparison.json()["experiment_id"] == experiment_id
    assert client.get("/api/leagues/EPL/model-evaluation").status_code == 200
    assert client.get("/api/leakage-audit").json()["violations"] == 0
    assert client.get("/api/leagues/Bundesliga/model-evaluation").status_code == 400


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


def test_fixture_detail_only_applies_cached_player_names(monkeypatch) -> None:
    fixture = seed_real_fixture("api-player-name-resolution", 131)
    fixture["status"] = "finished"
    context = unavailable_context()
    context["source"] = "espn-evidence"
    context["squads"]["home"] = [
        {
            "id": "supplier-10",
            "name": "Unknown Forward",
            "original_name": "Unknown Forward",
            "position": "Forward",
        }
    ]
    fixture["evidence"] = context
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    calls: list[bool] = []

    async def fake_enrich(value: dict, resolve_missing: bool = False) -> dict:
        calls.append(resolve_missing)
        return value

    monkeypatch.setattr(player_name_service, "enrich", fake_enrich)

    response = client.get(f"/api/fixtures/{fixture['id']}")

    assert response.status_code == 200
    assert calls == [False]
    payload = response.json()
    assert payload["context"]["squads"]["home"][0]["name"].startswith("待核验球员")
    assert "Unknown Forward" not in str(payload)


def test_fixture_detail_does_not_sync_missing_evidence(monkeypatch) -> None:
    fixture = seed_real_fixture("api-auto-evidence", 125)
    fixture["status"] = "scheduled"
    fixture["external_ids"] = {"api_football": 123}
    repository.replace_fixtures(
        fixture["fixture_date"],
        fixture["fixture_date"],
        [fixture],
        "2026-08-24T10:00:00+00:00",
    )
    calls = 0

    async def fake_fetch(_fixture):
        nonlocal calls
        calls += 1
        raise AssertionError("fixture detail must not fetch external evidence")

    monkeypatch.setattr(evidence_provider, "fetch", fake_fetch)
    monkeypatch.setattr(evidence_provider, "fetch_public", fake_fetch)
    response = client.get(f"/api/fixtures/{fixture['id']}")

    assert response.status_code == 200
    assert calls == 0
    assert response.json()["context"]["synced_at"] is None
    assert repository.fixture(fixture["id"]).get("evidence") is None
    assert response.json()["prediction"] is None
    assert repository.latest(fixture["id"], "deepseek", response.json()["competition_id"]) is None


def test_fixture_detail_keeps_incomplete_cached_evidence_without_refresh(monkeypatch) -> None:
    fixture = seed_real_fixture("api-secondary-refresh", 126)
    fixture["status"] = "scheduled"
    existing = unavailable_context()
    existing["source"] = "api-football-single-fixture"
    existing["recent_form"] = {"home": [{"result": "D"}], "away": [{"result": "D"}]}
    repository.save_fixture_evidence(fixture["id"], existing)
    calls = 0

    async def fake_secondary(_fixture):
        nonlocal calls
        calls += 1
        raise AssertionError("fixture detail must not refresh cached evidence")

    monkeypatch.setattr(evidence_provider, "fetch_secondary", fake_secondary)
    response = client.get(f"/api/fixtures/{fixture['id']}")

    assert response.status_code == 200
    assert calls == 0
    assert len(response.json()["context"]["recent_form"]["home"]) == 1
    assert repository.fixture(fixture["id"])["evidence"]["source"] == "api-football-single-fixture"


def test_manual_evidence_sync_uses_thesportsdb_public_path(monkeypatch) -> None:
    fixture = seed_real_fixture("api-public-evidence", 127)
    calls: list[str] = []
    context = unavailable_context()
    context["source"] = "thesportsdb-partial"
    context["synced_at"] = "2026-09-08T08:00:00+00:00"

    async def fake_public(_fixture):
        calls.append("public")
        return context

    async def fail_legacy(_fixture):
        raise AssertionError("legacy evidence providers must not be called")

    monkeypatch.setattr(evidence_provider, "fetch_public", fake_public)
    monkeypatch.setattr(evidence_provider, "fetch", fail_legacy)

    response = client.post(
        f"/api/admin/fixtures/{fixture['id']}/evidence",
        headers={"x-admin-key": "dev-admin-key"},
    )

    assert response.status_code == 200
    assert calls == ["public"]
    assert response.json()["context"]["source"] == "thesportsdb-partial"


def test_prediction_requires_admin_key() -> None:
    seed_real_fixture()
    response = client.post("/api/admin/fixtures/api-123/predictions")
    assert response.status_code == 401


def test_prediction_allows_started_and_live_fixtures_but_rejects_finished() -> None:
    for fixture_id, status, kickoff_delta, expected_status in (
        ("api-started-scheduled", "scheduled", timedelta(minutes=-5), 200),
        ("api-live", "live", timedelta(minutes=-30), 200),
        ("api-finished", "finished", timedelta(hours=-2), 409),
    ):
        fixture = seed_real_fixture(fixture_id, 7000 + len(fixture_id))
        fixture.update(
            {
                "status": status,
                "kickoff": (datetime.now(UTC) + kickoff_delta).replace(microsecond=0).isoformat(),
                "score": {"home": 1, "away": 0} if status != "scheduled" else None,
                "evidence": demo_context(fixture_id),
            }
        )
        repository.upsert_fixture(fixture)

        response = client.post(
            f"/api/admin/fixtures/{fixture_id}/predictions",
            headers={"x-admin-key": "dev-admin-key"},
        )

        assert response.status_code == expected_status
        if expected_status == 200:
            payload = response.json()
            assert payload["predictions"]
            assert payload["bets"] == []
            assert all(item["fixture_status_at_prediction"] == status for item in payload["predictions"])
            assert all(item["score_at_prediction"] == fixture["score"] for item in payload["predictions"])
        else:
            assert "不能生成预测" in response.json()["detail"]


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
    assert bankroll_response.json()["initial_balance"] == 5000.0
    assert bankroll_response.json()["is_simulated"] is True
    assert metrics_response.status_code == 200
    assert metrics_response.json()["sample_size"] == 0


def test_decisions_endpoint_returns_latest_auditable_no_bet_row() -> None:
    fixture = seed_real_fixture("api-decisions", 129)
    fixture.update(
        {
            "fixture_date": "2099-08-27",
            "kickoff": "2099-08-27T12:00:00+00:00",
            "status": "scheduled",
            "is_demo": False,
        }
    )
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
            "id": "decision-current",
            "created_at": "2099-08-27T01:00:00+00:00",
            "model_key": "deepseek",
            "competition_id": repository.competition_id,
            "ai": {
                "status": "completed",
                "provider": "deepseek",
                "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
            },
            "model_recommendation": {"status": "no_bet", "market": "no_bet", "selection": "none"},
            "decision": {
                "status": "no_bet",
                "market": "no_bet",
                "selection": "none",
                "considered_market": "1x2",
                "considered_selection": "home",
                "price": 2.1,
                "expected_edge": 0.01,
                "stake_fraction": 0.0,
                "reason_codes": ["negative_edge"],
                "reason": "优势不足，保留观察",
            },
            "experiment": {
                "model_key": "deepseek",
                "strategy_id": "baseline",
                "strategy_version": "v1",
                "strategy_name": "基准",
            },
        }
    )
    repository.save(current)

    response = client.get(
        "/api/decisions",
        params={"model": "deepseek", "fixture_date": "2099-08-27"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["id"] == "decision-current"
    assert payload["items"][0]["decision_status"] == "no_bet"
    assert payload["items"][0]["execution_status"] == "no_bet"
    assert payload["items"][0]["strategy_name"] == "基准"
    assert payload["items"][0]["reason_codes"] == ["negative_edge"]
    assert payload["items"][0]["considered_selection"] == "home"


def test_decisions_endpoint_flags_a_simulation_bet_when_current_candidate_changed() -> None:
    fixture = seed_real_fixture("api-decision-mismatch", 130)
    fixture.update(
        {
            "fixture_date": "2099-08-28",
            "kickoff": "2099-08-28T12:00:00+00:00",
            "status": "scheduled",
            "is_demo": False,
        }
    )
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
            "id": "decision-mismatch",
            "created_at": "2099-08-28T01:00:00+00:00",
            "model_key": "deepseek",
            "competition_id": repository.competition_id,
            "ai": {"status": "completed", "provider": "deepseek", "prompt_version": DEFAULT_PROMPT_CONTRACT.version},
            "decision": {"status": "no_bet", "market": "no_bet", "selection": "none", "reason": "当前不下注"},
            "experiment": {"model_key": "deepseek", "strategy_id": "baseline", "strategy_version": "v1", "strategy_name": "基准"},
        }
    )
    repository.save(current)
    repository.place_bet(
        {
            "id": "mismatch-bet",
            "prediction_id": current["id"],
            "fixture_id": fixture["id"],
            "fixture_date": fixture["fixture_date"],
            "placed_at": "2099-08-28T01:01:00+00:00",
            "market": "1x2",
            "selection": "home",
            "handicap_line": None,
            "odds": 2.1,
            "stake": 10.0,
            "league_key": fixture["league_key"],
            "kickoff": fixture["kickoff"],
            "home_team": fixture["home_team"]["name"],
            "away_team": fixture["away_team"]["name"],
            "model_version": current["model_version"],
            "is_simulated": True,
            "model_key": "deepseek",
            "competition_id": repository.competition_id,
        }
    )

    response = client.get(
        "/api/decisions",
        params={"model": "deepseek", "fixture_date": "2099-08-28"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["execution_status"] == "bet"
    assert response.json()["items"][0]["execution_reason"] == "已有模拟单，但当前预测候选已变化，请核对"


def test_strategy_performance_returns_independent_model_rows() -> None:
    response = client.get("/api/strategy-performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ranking"] == "ROI_THEN_PNL"
    assert {item["model_key"] for item in payload["items"]} == {"deepseek", "chatgpt"}
    assert all(item["strategy_id"] == "baseline" for item in payload["items"])
    assert all(item["gate_mode"] == "SHADOW_ONLY" for item in payload["items"])


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
    # One lookback day plus seven lookahead days across six TheSportsDB leagues.
    assert response.json()["request_count"] == 54
    assert repository.fixture("api-123") is not None
