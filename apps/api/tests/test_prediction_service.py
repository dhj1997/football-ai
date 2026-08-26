from app.data import demo_context, demo_fixtures
from app.prediction_service import PredictionService
import pytest


pytestmark = pytest.mark.asyncio


class FakeRepository:
    def __init__(self) -> None:
        self.snapshots: list[dict] = []
        self.predictions: list[dict] = []

    def save_evidence_snapshot(self, snapshot: dict) -> None:
        self.snapshots.append(snapshot)

    def save(self, prediction: dict) -> None:
        self.predictions.append(prediction)

    def league_snapshots(self, league_key: str) -> list[dict]:
        return [
            {
                "source": "espn",
                "season": {"year": 2026, "name": "2026-27"},
                "updated_at": "2026-08-26T00:00:00+00:00",
                "standings": [
                    {"team": {"name": "曼彻斯特城", "original_name": "Manchester City"}, "rank": 1, "points": 3},
                    {"team": {"name": "托特纳姆热刺", "original_name": "Tottenham Hotspur"}, "rank": 2, "points": 3},
                ],
            }
        ]


class FakeDeepSeek:
    model = "deepseek-v4-flash"

    def __init__(self, configured: bool = True) -> None:
        self.configured = configured

    async def assess(self, model_input: dict) -> dict:
        assert model_input["fixture"]["home_team"]
        return {
            "assessment": {
                "probabilities": {"home": 0.56, "draw": 0.25, "away": 0.19},
                "predicted_outcome": "home",
                "asian_handicap_assessment": {
                    "available": False,
                    "line": None,
                    "selection": "none",
                    "confidence": 0.0,
                    "reason": "No Asian handicap line is available.",
                },
                "recommendation": {
                    "market": "no_bet",
                    "selection": "none",
                    "confidence": 0.6,
                    "recommended_stake_fraction": 0.0,
                    "reason": "No real market odds are available.",
                },
                "analysis_summary": "Home evidence is stronger, but market data is absent.",
                "risk_factors": ["No market odds"],
                "missing_evidence": ["Market odds"],
            },
            "requested_model": self.model,
            "returned_model": self.model,
            "prompt_version": "deepseek-football-v1",
            "request_id": "request-1",
            "usage": {"total_tokens": 30},
        }


def real_fixture_and_context() -> tuple[dict, dict]:
    fixture = demo_fixtures()[0]
    fixture = {**fixture, "id": "api-123", "is_demo": False}
    context = demo_context(fixture["id"])
    context["source"] = "test"
    context["synced_at"] = "2026-08-26T00:00:00+00:00"
    context["odds"] = None
    return fixture, context


async def test_successful_ai_prediction_links_immutable_evidence() -> None:
    fixture, context = real_fixture_and_context()
    repository = FakeRepository()
    result = await PredictionService(FakeDeepSeek(), repository).create(fixture, context)

    assert result["ai"]["status"] == "completed"
    assert result["model_version"] == "deepseek:deepseek-v4-flash"
    assert result["probabilities"] == {"home": 0.56, "draw": 0.25, "away": 0.19}
    assert result["evidence_snapshot_id"] == repository.snapshots[0]["id"]
    assert result["evidence_hash"] == repository.snapshots[0]["content_hash"]
    assert repository.snapshots[0]["payload"]["standings"]["home"]["rank"] == 1
    assert result["evidence_fields"]["standings"] is True
    assert repository.predictions == [result]


async def test_unconfigured_ai_saves_explicit_degraded_prediction() -> None:
    fixture, context = real_fixture_and_context()
    repository = FakeRepository()
    result = await PredictionService(FakeDeepSeek(configured=False), repository).create(fixture, context)

    assert result["ai"]["status"] == "unconfigured"
    assert result["recommendation"]["market"] == "no_bet"
    assert len(repository.snapshots) == 1
    assert len(repository.predictions) == 1
