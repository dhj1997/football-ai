"""P16 HTTP contract tests for correlation ids and the observability endpoint."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p16.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

from app.main import app, request_metrics


client = TestClient(app)

_ADMIN = {"x-admin-key": "dev-admin-key"}


def test_every_response_carries_a_correlation_id() -> None:
    generated = client.get("/health")
    assert generated.status_code == 200
    assert generated.headers.get("x-correlation-id", "").startswith("req:")

    incoming = client.get("/health", headers={"x-correlation-id": "req:test-123"})
    assert incoming.headers.get("x-correlation-id") == "req:test-123"


def test_request_metrics_window_records_traffic() -> None:
    before = request_metrics.snapshot()["window_size"]
    client.get("/health")
    after = request_metrics.snapshot()["window_size"]

    assert after >= min(before + 1, request_metrics.snapshot()["window_cap"])


def test_observability_endpoint_requires_admin() -> None:
    assert client.get("/api/admin/observability").status_code == 401


def test_observability_endpoint_returns_state_alerts_and_slos() -> None:
    response = client.get("/api/admin/observability", headers=_ADMIN)

    assert response.status_code == 200
    payload = response.json()
    assert payload["observability_version"].startswith("p16-")
    assert payload["api"]["window_cap"] == 500
    assert isinstance(payload["providers"], list)
    assert isinstance(payload["alerts"], list)
    assert {slo["tier"] for slo in payload["slo_catalog"]} == {"tier1", "tier2"}
    assert payload["runbook"] == "docs/RUNBOOKS.md"
    # No secrets may leak through the observability payload.
    assert "dev-admin-key" not in response.text
