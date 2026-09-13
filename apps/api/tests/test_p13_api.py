"""P13 HTTP contract tests for the explanation endpoint."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p13.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app, repository


client = TestClient(app)


def test_explanation_requires_known_fixture() -> None:
    assert client.get("/api/fixtures/does-not-exist/explanation").status_code == 404


def test_explanation_requires_a_current_prediction() -> None:
    from app.data import demo_fixtures

    fixture = dict(demo_fixtures(datetime.now(UTC).date())[0])
    fixture["is_demo"] = False
    fixture["fixture_date"] = datetime.now(UTC).date().isoformat()
    repository.upsert_fixture(fixture)

    response = client.get(f"/api/fixtures/{fixture['id']}/explanation")

    assert response.status_code == 404
    assert "暂无当前版本预测" in response.json()["detail"]
