"""P15 HTTP contract tests for production readiness endpoints."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p15.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

from app.main import app, repository, settings


client = TestClient(app)

_ADMIN = {"x-admin-key": "dev-admin-key"}


def test_production_endpoints_require_admin() -> None:
    for path in (
        "/api/production/readiness",
        "/api/admin/production/migrations/dry-run",
        "/api/admin/production/migrations/apply",
        "/api/admin/production/backup",
        "/api/admin/production/smoke",
        "/api/admin/activation-status",
    ):
        if path in {"/api/production/readiness", "/api/admin/activation-status"}:
            assert client.get(path).status_code == 401
        else:
            assert client.post(path).status_code == 401


def test_readiness_reports_environment_and_smoke() -> None:
    response = client.get("/api/production/readiness", headers=_ADMIN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"] == settings.environment
    assert payload["smoke"]["status"] in {"pass", "fail"}
    assert payload["migration_dry_run"]["status"] in {"validated", "not_supported"}
    assert payload["status"] in {"ready", "blocked"}


def test_migration_dry_run_and_smoke_endpoints() -> None:
    dry = client.post("/api/admin/production/migrations/dry-run", headers=_ADMIN)
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True

    smoke = client.post("/api/admin/production/smoke", headers=_ADMIN)
    assert smoke.status_code == 200
    assert smoke.json()["status"] in {"pass", "fail"}


def test_activation_status_composes_real_read_only_components() -> None:
    response = client.get("/api/admin/activation-status", headers=_ADMIN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["backend"] == "sqlite"
    assert payload["database"]["status"] == "test_only"
    assert payload["player_impact"]["active_rule_count"] >= 0
    assert payload["ensemble"]["status"] in {"ready", "pending"}
    assert "backtests" in payload["evaluation"]
    assert {
        (item["key"], item.get("reason"))
        for item in payload["providers"]["sources"]
        if item["status"] == "unavailable"
    } == {
        ("player_values", "provider_required"),
        ("prematch_news", "provider_required"),
    }


def test_activation_status_separates_exploratory_and_confirmatory_research(monkeypatch) -> None:
    monkeypatch.setattr(
        repository,
        "research_runs",
        lambda status=None, limit=100: [
            {"status": "completed", "exploratory": True, "hypothesis": {"kind": "exploratory"}},
            {"status": "completed", "exploratory": False, "hypothesis": {"kind": "confirmatory"}},
            {"status": "partial", "exploratory": True, "hypothesis": {"kind": "exploratory"}},
        ][:limit],
    )

    response = client.get("/api/admin/activation-status", headers=_ADMIN)

    assert response.status_code == 200
    research = response.json()["evaluation"]["research"]
    assert research["passing_count"] == 2
    assert research["exploratory_count"] == 1
    assert research["confirmatory_count"] == 1


def test_backup_endpoint_reports_mysql_restore_marker(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "last-verified.json"
    marker.write_text(
        '{"status":"verified","database":"football_ai","backup_file":"db.sql.gz","verified_at":"2026-09-20T00:00:00Z"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "mysql_backup_verification_file", str(marker))
    response = client.post("/api/admin/production/backup", headers=_ADMIN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "verified"
    assert payload["database"] == "football_ai"
    assert payload["backup_file"] == "db.sql.gz"
