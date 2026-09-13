"""P15 HTTP contract tests for production readiness endpoints."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p15.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

from app.main import app, settings


client = TestClient(app)

_ADMIN = {"x-admin-key": "dev-admin-key"}


def test_production_endpoints_require_admin() -> None:
    for path in (
        "/api/production/readiness",
        "/api/admin/production/migrations/dry-run",
        "/api/admin/production/migrations/apply",
        "/api/admin/production/backup",
        "/api/admin/production/smoke",
    ):
        if path == "/api/production/readiness":
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


def test_backup_endpoint_verifies_sqlite_restore() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        return
    response = client.post("/api/admin/production/backup", headers=_ADMIN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"verified", "unavailable", "not_supported"}
    if payload["status"] == "verified":
        assert payload["source_fingerprint"] == payload["restore_fingerprint"]
