"""P0 architecture regression tests for forecast and snapshot integrity."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.database import PredictionRepository
from app.data import demo_context, demo_fixtures
from app.dual_prediction_service import DualPredictionService
from app.market_decision import apply_market_decision
from app.prediction import predict
from app.prediction_service import PredictionService, _odds_snapshot
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT
from app.settlement import SettlementService


def _fixture(fixture_id: str = "p0-fixture", status: str = "scheduled") -> dict:
    fixture = deepcopy(demo_fixtures()[0])
    fixture.update(
        {
            "id": fixture_id,
            "is_demo": False,
            "status": status,
            "fixture_date": "2099-08-27",
            "kickoff": "2099-08-27T12:00:00+00:00",
            "score": {"home": 2, "away": 0} if status == "finished" else None,
        }
    )
    return fixture


def _prediction(prediction_id: str = "p0-prediction", fixture_id: str = "p0-fixture") -> dict:
    return {
        "id": prediction_id,
        "fixture_id": fixture_id,
        "created_at": "2099-08-27T01:00:00+00:00",
        "phase": "preliminary",
        "model_version": "test:model-v1",
        "model_key": "deepseek",
        "competition_id": "legacy",
        "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "model_probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "forecast": {"probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15}},
        "evidence_snapshot_id": "evidence-p0",
        "evidence_hash": "a" * 64,
        "odds_snapshot_id": "odds-p0",
        "ai": {"status": "completed", "provider": "deepseek", "prompt_version": DEFAULT_PROMPT_CONTRACT.version},
        "decision": {"status": "no_bet", "market": "no_bet", "selection": "none"},
    }


def _odds_snapshot_input(snapshot_id: str, price: float) -> dict:
    return {
        "id": snapshot_id,
        "fixture_id": "p0-fixture",
        "captured_at": f"2099-08-27T{9 if price == 1.90 else 12:02d}:00:00+00:00",
        "source": "test-book",
        "bookmaker": "Test Book",
        "quotes": [
            {
                "market": "1x2",
                "selection": "home",
                "line": None,
                "price": price,
                "bookmaker": "Test Book",
                "source": "test-book",
                "captured_at": f"2099-08-27T{9 if price == 1.90 else 12:02d}:00:00+00:00",
            }
        ],
    }


def test_market_odds_never_change_pure_model_forecast() -> None:
    fixture = _fixture()
    with_odds = demo_context(fixture["id"])
    without_odds = deepcopy(with_odds)
    without_odds["odds"] = None

    assert predict(fixture, with_odds)["probabilities"] == predict(fixture, without_odds)["probabilities"]


def test_evidence_snapshot_is_append_only_and_same_id_cannot_change(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "evidence-p0.db"))
    repository.initialize()
    snapshot = {
        "id": "evidence-a",
        "fixture_id": "p0-fixture",
        "created_at": "2099-08-27T09:00:00+00:00",
        "captured_at": "2099-08-27T09:00:00+00:00",
        "evidence_version": "fixture-evidence-v3",
        "content_hash": "a" * 64,
        "payload": {"context": {"source": "a"}},
    }
    repository.save_evidence_snapshot(snapshot)
    repository.save_evidence_snapshot(deepcopy(snapshot))
    with pytest.raises(ValueError, match="immutable"):
        repository.save_evidence_snapshot({**snapshot, "payload": {"context": {"source": "tampered"}}})
    repository.save_evidence_snapshot({**snapshot, "id": "evidence-b", "payload": {"context": {"source": "b"}}})

    assert repository.evidence_snapshot("evidence-a")["payload"] == {"context": {"source": "a"}}
    assert repository.evidence_snapshot("evidence-b")["payload"] == {"context": {"source": "b"}}


def test_odds_snapshots_keep_multiple_captures(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "odds-p0.db"))
    repository.initialize()
    repository.save_odds_snapshot(_odds_snapshot_input("odds-a", 1.90))
    repository.save_odds_snapshot(_odds_snapshot_input("odds-b", 1.85))

    snapshots = repository.odds_snapshots("p0-fixture")
    assert [item["id"] for item in snapshots] == ["odds-a", "odds-b"]
    assert [item["quotes"][0]["price"] for item in snapshots] == [1.90, 1.85]


def test_evidence_refresh_appends_odds_snapshot_history(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "odds-refresh-p0.db"))
    repository.initialize()
    repository.replace_fixtures(
        "2099-08-27",
        "2099-08-27",
        [_fixture()],
        "2099-08-27T00:00:00+00:00",
    )
    first = demo_context("p0-fixture")
    first["odds"]["updated_at"] = "2099-08-27T09:00:00+00:00"
    second = deepcopy(first)
    second["odds"]["home"] = 1.85
    second["odds"]["updated_at"] = "2099-08-27T12:00:00+00:00"

    repository.save_fixture_evidence("p0-fixture", first)
    repository.save_fixture_evidence("p0-fixture", second)

    snapshots = repository.odds_snapshots("p0-fixture")
    assert len(snapshots) == 2
    assert [item["payload"]["home"] for item in snapshots] == [first["odds"]["home"], 1.85]


def test_prediction_freeze_allows_lifecycle_only_updates(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "freeze-p0.db"))
    repository.initialize()
    repository.save(_prediction())
    with pytest.raises(ValueError, match="immutable"):
        repository.update_prediction("p0-prediction", {"model_probabilities": {"home": 1.0}})
    updated = repository.update_prediction("p0-prediction", {"status": "settled", "metadata": {"source": "test"}})

    assert updated["status"] == "settled"
    saved = repository.latest("p0-fixture", "deepseek", "legacy")
    assert saved["model_probabilities"] == {"home": 0.6, "draw": 0.25, "away": 0.15}
    assert saved["evidence_snapshot_id"] == "evidence-p0"
    assert saved["odds_snapshot_id"] == "odds-p0"


def test_settlement_does_not_modify_prediction_or_snapshots(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "settlement-p0.db"))
    repository.initialize()
    fixture = _fixture(status="finished")
    repository.replace_fixtures("2099-08-27", "2099-08-27", [fixture], "2099-08-27T00:00:00+00:00")
    repository.save(_prediction())
    before = deepcopy(repository.latest("p0-fixture", "deepseek", "legacy"))

    SettlementService(repository).settle_fixture(fixture)

    after = repository.latest("p0-fixture", "deepseek", "legacy")
    assert after == before


def test_market_assessment_is_a_derived_copy() -> None:
    original = _prediction()
    before = deepcopy(original)
    context = demo_context("p0-fixture")

    derived = apply_market_decision(original, context)

    assert original == before
    assert derived is not original
    assert derived["model_probabilities"] == before["model_probabilities"]


class _ModelProvider:
    configured = True
    model = "test-model"

    def __init__(self, provider_name: str, probabilities: dict[str, float]) -> None:
        self.provider_name = provider_name
        self.probabilities = probabilities

    async def assess(self, _model_input: dict) -> dict:
        return {
            "assessment": {
                "probabilities": self.probabilities,
                "predicted_outcome": max(self.probabilities, key=self.probabilities.get),
                "forecast_confidence": 0.8,
                "asian_handicap_forecast": {"available": False, "line": None, "home_cover_probability": None, "away_cover_probability": None, "confidence": 0.0, "reason": "无让球盘口"},
                "player_analysis": {"key_available_players": [], "key_absent_players": [], "replacement_gap": "", "attack_impact": "", "defense_impact": ""},
                "bet_recommendation": {"status": "no_bet", "market": "no_bet", "selection": "none", "reason": "测试"},
                "analysis_summary": "测试",
                "risk_factors": [],
                "missing_evidence": [],
            },
            "provider": self.provider_name,
            "requested_model": self.model,
            "returned_model": self.model,
            "prompt_version": DEFAULT_PROMPT_CONTRACT.version,
            "evidence_version": "fixture-evidence-v3",
            "request_id": self.provider_name,
            "usage": None,
        }


def test_dual_models_share_one_evidence_and_odds_snapshot(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "dual-p0.db"), "dual", ("deepseek", "chatgpt"))
    repository.initialize()
    fixture = _fixture()
    context = demo_context(fixture["id"])
    services = {
        key: PredictionService(
            _ModelProvider(key, {"home": 0.6, "draw": 0.25, "away": 0.15}),
            repository,
            key,
            "dual",
        )
        for key in ("deepseek", "chatgpt")
    }

    results = asyncio.run(DualPredictionService(services, "dual").create(fixture, context))

    assert len(results) == 2
    assert len({item["evidence_snapshot_id"] for item in results}) == 1
    assert len({item["evidence_hash"] for item in results}) == 1
    assert len({item["odds_snapshot_id"] for item in results}) == 1
    assert len(repository.odds_snapshots(fixture["id"])) == 1


def test_forecast_metrics_use_model_probabilities_not_market_adjusted_values(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "metrics-p0.db"))
    repository.initialize()
    fixture = _fixture(status="finished")
    repository.replace_fixtures("2099-08-27", "2099-08-27", [fixture], "2099-08-27T00:00:00+00:00")
    repository.save(_prediction())

    result = SettlementService(repository).settle_fixture(fixture)

    assert result["items"][0]["prediction"]["brier_score"] == 0.245
