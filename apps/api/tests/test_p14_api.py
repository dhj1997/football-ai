"""P14 HTTP contract tests for research run APIs."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p14.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from datetime import UTC, datetime, timedelta
import random

from fastapi.testclient import TestClient

from app.main import app, repository


client = TestClient(app)

_ADMIN = {"x-admin-key": "dev-admin-key"}


def _seed_settlements(count: int = 300) -> None:
    rng = random.Random(31)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(count):
        actual = rng.choice(["home", "draw", "away"])
        created = start + timedelta(hours=index * 6)
        repository.save_fixture_settlement(
            {
                "id": f"p14-settle-{index}",
                "prediction_id": f"p14-pred-{index}",
                "fixture_id": f"p14-fixture-{index}",
                "fixture_date": created.date().isoformat(),
                "league_key": "epl",
                "season": "2026",
                "model_version": "deepseek:deepseek-v4-flash",
                "model_key": "deepseek",
                "settled_at": (created + timedelta(hours=30)).isoformat(),
                "prediction_created_at": created.isoformat(),
                "actual_outcome": actual,
                "model_probabilities": {key: 0.55 if key == actual else 0.225 for key in ("home", "draw", "away")},
            }
        )


def test_research_run_requires_admin() -> None:
    assert client.post("/api/admin/research/runs", json={"hypothesis": "未授权的研究尝试", "kind": "exploratory"}).status_code == 401


def test_research_run_validates_hypothesis() -> None:
    response = client.post(
        "/api/admin/research/runs",
        headers=_ADMIN,
        json={"hypothesis": "确认性研究没有选择规则", "kind": "confirmatory"},
    )

    assert response.status_code == 400


def test_research_run_creates_immutable_traceable_report() -> None:
    _seed_settlements()

    payload = {
        "hypothesis": "ensemble 在 epl 测试窗的 Brier 优于 naive baseline",
        "kind": "confirmatory",
        "selection_rule": "ensemble_brier 低者胜",
        "mode": "rolling",
        "train_days": 45,
        "test_days": 15,
        "step_days": 15,
    }
    first = client.post("/api/admin/research/runs", headers=_ADMIN, json=payload)
    assert first.status_code == 200
    run = first.json()
    assert run["run_id"].startswith("research:")
    assert run["status"] == "completed"
    assert run["exploratory"] is False
    assert run["report"]["leakage_audit"]["status"] == "passed"

    second = client.post("/api/admin/research/runs", headers=_ADMIN, json=payload)
    assert second.json()["run_id"] == run["run_id"]
    assert len(repository.research_runs()) == 1

    listed = client.get("/api/research/runs")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    detail = client.get(f"/api/research/runs/{run['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["item"]["report"]["dataset"]["fingerprint"]

    assert client.get("/api/research/runs/research:missing").status_code == 404
