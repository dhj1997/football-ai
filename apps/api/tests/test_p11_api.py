"""P11 HTTP contract tests for the market intelligence API."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p11.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app, repository


client = TestClient(app)


def _seed_fixture_with_odds() -> dict:
    from app.data import demo_fixtures

    fixture = dict(demo_fixtures(datetime.now(UTC).date())[0])
    fixture["is_demo"] = False
    fixture["fixture_date"] = datetime.now(UTC).date().isoformat()
    repository.upsert_fixture(fixture)
    captured = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0).isoformat()
    repository.save_odds_snapshot(
        {
            "snapshot_id": f"snap-p11-{captured}",
            "fixture_id": fixture["id"],
            "captured_at": captured,
            "source": "dongqiudi",
            "bookmaker": "bet365",
            "quotes": [
                {"market": "1x2", "selection": "home", "line": None, "price": 2.0, "bookmaker": "bet365", "source": "dongqiudi", "captured_at": captured},
                {"market": "1x2", "selection": "draw", "line": None, "price": 3.5, "bookmaker": "bet365", "source": "dongqiudi", "captured_at": captured},
                {"market": "1x2", "selection": "away", "line": None, "price": 4.0, "bookmaker": "bet365", "source": "dongqiudi", "captured_at": captured},
            ],
        }
    )
    return fixture


def test_market_report_exposes_source_and_timestamp() -> None:
    fixture = _seed_fixture_with_odds()

    response = client.get(f"/api/fixtures/{fixture['id']}/market")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_id"] == fixture["id"]
    assert payload["quote_count"] >= 3
    section = payload["markets"]["1x2"]
    timeline = section["timelines"]["home"]
    assert timeline["current"]["source"] == "dongqiudi"
    assert timeline["current"]["captured_at"]
    assert section["consensus"]["consensus_probabilities"]
    # Without a stored prediction there is no divergence to report.
    divergence = section.get("model_vs_market")
    assert divergence is None or divergence["role"] == "research_signal"
    assert isinstance(payload["bet_clv"], list)
    assert "persisted_market_snapshots" in payload


def test_market_report_404_for_unknown_fixture() -> None:
    response = client.get("/api/fixtures/does-not-exist/market")

    assert response.status_code == 404


def test_market_snapshot_capture_requires_admin() -> None:
    response = client.post("/api/admin/fixtures/nobody/market-snapshot")
    assert response.status_code == 401


def test_market_snapshot_capture_persists_idempotent_records() -> None:
    fixture = _seed_fixture_with_odds()

    first = client.post(
        f"/api/admin/fixtures/{fixture['id']}/market-snapshot",
        headers={"x-admin-key": "dev-admin-key"},
    )
    second = client.post(
        f"/api/admin/fixtures/{fixture['id']}/market-snapshot",
        headers={"x-admin-key": "dev-admin-key"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_ids = first.json()["persisted_market_snapshot_ids"]
    second_ids = second.json()["persisted_market_snapshot_ids"]
    assert first_ids == second_ids
    persisted_ids = {row["market_snapshot_id"] for row in repository.market_snapshots(fixture["id"])}
    assert set(first_ids) <= persisted_ids
