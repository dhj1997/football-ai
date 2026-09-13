"""P17 HTTP contract test for the platform map endpoint."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p17.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_platform_endpoint_exposes_domain_map_and_season_audit() -> None:
    response = client.get("/api/platform")

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform_version"] == "p17-platform-v1"
    modules = {item["module"] for item in payload["domain_map"]}
    assert {"competition_registry", "model_platform", "backtest_engine", "research_engine", "observability"} <= modules
    assert all(item["contract"] and item["owner"] for item in payload["domain_map"])
    surfaces = " ".join(payload["surfaces"])
    assert "Model Lab" in surfaces and "Research Engine" in surfaces and "Competition Center" in surfaces
    assert payload["season_binding_audit"]["policy"]
    assert payload["governance"]["adrs"] == "docs/adr/"
    assert "new semantics require an ADR" in payload["governance"]["extension_rule"]
