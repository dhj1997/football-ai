"""P12 HTTP contract tests for the advanced backtest run API."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p12.db")
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
    rng = random.Random(21)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(count):
        actual = rng.choice(["home", "draw", "away"])
        settlement = {
            "id": f"p12-settle-{index}",
            "prediction_id": f"p12-pred-{index}",
            "fixture_id": f"p12-fixture-{index}",
            "fixture_date": (start + timedelta(hours=index * 6)).date().isoformat(),
            "league_key": "epl",
            "season": "2026",
            "model_version": "deepseek:deepseek-v4-flash",
            "model_key": "deepseek",
            "settled_at": (start + timedelta(hours=index * 6 + 30)).isoformat(),
            "prediction_created_at": (start + timedelta(hours=index * 6)).isoformat(),
            "actual_outcome": actual,
            "model_probabilities": {key: 0.55 if key == actual else 0.225 for key in ("home", "draw", "away")},
        }
        repository.save_fixture_settlement(settlement)


def test_advanced_backtest_requires_admin() -> None:
    assert client.post("/api/admin/backtest/runs", json={"mode": "rolling"}).status_code == 401


def test_advanced_backtest_run_is_reproducible_and_immutable() -> None:
    _seed_settlements()

    first = client.post("/api/admin/backtest/runs", headers=_ADMIN, json={"mode": "rolling", "train_days": 45, "test_days": 15, "step_days": 15})
    assert first.status_code == 200
    body = first.json()
    assert body["run_id"] and body["run_id"].startswith("backtest:")
    assert body["run"]["status"] == "ok"
    assert body["run"]["payload"]["manifest"]["random_seed"]

    second = client.post("/api/admin/backtest/runs", headers=_ADMIN, json={"mode": "rolling", "train_days": 45, "test_days": 15, "step_days": 15})
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == body["run_id"]

    stored = client.get(f"/api/backtest/runs/{body['run_id']}")
    assert stored.status_code == 200
    assert stored.json()["item"]["payload"]["manifest"]["dataset_fingerprint"]


def test_advanced_backtest_rejects_unknown_mode() -> None:
    response = client.post("/api/admin/backtest/runs", headers=_ADMIN, json={"mode": "bogus"})

    assert response.status_code == 400


def test_advanced_backtest_does_not_persist_insufficient_data() -> None:
    before = len(repository.backtest_runs())

    response = client.post(
        "/api/admin/backtest/runs",
        headers=_ADMIN,
        json={"mode": "rolling", "source": "missing-source"},
    )

    assert response.status_code == 200
    assert response.json()["run_id"] is None
    assert response.json()["status"] == "insufficient_data"
    assert len(repository.backtest_runs()) == before
