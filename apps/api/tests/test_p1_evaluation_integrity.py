"""Focused P1 CLV, calibration, paired evaluation, and quality-gate tests."""

from datetime import UTC, datetime

import pytest

from app.database import PredictionRepository
from app.settlement import (
    SettlementService,
    _quality_gate,
    calculate_calibration,
    calculate_clv,
)


def _fixture(status: str = "finished") -> dict:
    return {
        "id": "p1-fixture",
        "fixture_id": "p1-fixture",
        "provider_id": 1001,
        "fixture_date": "2099-08-27",
        "kickoff": "2099-08-27T18:00:00+00:00",
        "status": status,
        "league_key": "epl",
        "home_team": {"name": "主队"},
        "away_team": {"name": "客队"},
        "score": {"home": 2, "away": 0} if status == "finished" else None,
    }


def _prediction(prediction_id: str, model_key: str, fixture_id: str = "p1-fixture") -> dict:
    probabilities = {"home": 0.6, "draw": 0.25, "away": 0.15}
    return {
        "id": prediction_id,
        "fixture_id": fixture_id,
        "created_at": "2099-08-27T09:00:00+00:00",
        "phase": "preliminary",
        "model_version": f"{model_key}:test",
        "model_key": model_key,
        "competition_id": "p1",
        "prompt_version": "football-forecast-v5",
        "probabilities": probabilities,
        "model_probabilities": probabilities,
        "baseline": {"probabilities": {"home": 0.55, "draw": 0.25, "away": 0.20}},
        "predicted_outcome": "home",
        "evidence_snapshot_id": "evidence-p1",
        "evidence_hash": "a" * 64,
        "odds_snapshot_id": "odds-p1",
        "ai": {"status": "completed", "provider": model_key, "prompt_version": "football-forecast-v5"},
        "market_assessment": {
            "markets": [
                {"market": "1x2", "selection": "home", "market_probability": 0.50, "de_vig_probability": 0.50},
                {"market": "1x2", "selection": "draw", "market_probability": 0.28, "de_vig_probability": 0.28},
                {"market": "1x2", "selection": "away", "market_probability": 0.22, "de_vig_probability": 0.22},
            ]
        },
        "decision": {"status": "bet", "market": "1x2", "selection": "home", "expected_edge": 0.2},
    }


def _odds_snapshot(snapshot_id: str, captured_at: str, price: float, line: float | None = None) -> dict:
    market = "asian_handicap" if line is not None else "1x2"
    selection = "home_handicap" if line is not None else "home"
    return {
        "id": snapshot_id,
        "fixture_id": "p1-fixture",
        "captured_at": captured_at,
        "source_updated_at": captured_at,
        "source": "test-book",
        "bookmaker": "Test Book",
        "quotes": [
            {
                "market": market,
                "selection": selection,
                "line": line,
                "price": price,
                "bookmaker": "Test Book",
                "source": "test-book",
                "captured_at": captured_at,
                "source_updated_at": captured_at,
            }
        ],
    }


def test_decimal_clv_formula_and_missing_close() -> None:
    assert calculate_clv(2.0, 1.8) == pytest.approx(0.1111)
    assert calculate_clv(1.8, 2.0) == pytest.approx(-0.1)
    assert calculate_clv(2.0, None) is None


def test_closing_odds_are_latest_valid_capture_before_kickoff(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "clv.db"))
    repository.initialize()
    repository.save_odds_snapshot(_odds_snapshot("p1-early", "2099-08-27T09:00:00+00:00", 2.0))
    repository.save_odds_snapshot(_odds_snapshot("p1-close", "2099-08-27T17:00:00+00:00", 1.8))
    repository.save_odds_snapshot(_odds_snapshot("p1-after", "2099-08-27T19:00:00+00:00", 1.7))

    close = repository.closing_odds_for_bet(
        "p1-fixture",
        "2099-08-27T18:00:00+00:00",
        {"market": "1x2", "selection": "home", "odds": 2.0, "bookmaker": "Test Book"},
    )

    assert close["price"] == 1.8
    assert close["snapshot_id"] == "p1-close"


def test_asian_handicap_line_matching_and_line_change_flag(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "ah-clv.db"))
    repository.initialize()
    repository.save_odds_snapshot(_odds_snapshot("ah-old", "2099-08-27T09:00:00+00:00", 1.9, -0.25))
    repository.save_odds_snapshot(_odds_snapshot("ah-close", "2099-08-27T17:00:00+00:00", 1.8, -0.5))

    strict = repository.closing_odds_for_bet(
        "p1-fixture", "2099-08-27T18:00:00+00:00", {"market": "asian_handicap", "selection": "home_handicap", "line_at_bet": -0.75, "bookmaker": "Test Book"}
    )
    changed = repository.closing_odds_for_bet(
        "p1-fixture", "2099-08-27T18:00:00+00:00", {"market": "asian_handicap", "selection": "home_handicap", "line_at_bet": -0.75, "bookmaker": "Test Book"}, allow_line_change=True
    )

    assert strict is None
    assert changed["line"] == -0.5
    assert changed["line"] != -0.75


def test_calibration_bins_outcomes_and_ece() -> None:
    rows = [
        {"model_probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}, "actual_outcome": "home"},
        {"model_probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}, "actual_outcome": "away"},
    ]
    report = calculate_calibration(rows)

    assert report["status"] == "insufficient_sample"
    assert report["bins"]["home"][6]["sample_count"] == 2
    assert report["bins"]["home"][6]["actual_frequency"] == 0.5
    assert report["ece"]["home"] == pytest.approx(0.1)
    assert report["bins"]["draw"][2]["sample_count"] == 2
    assert report["bins"]["away"][2]["sample_count"] == 2


def test_calibration_zero_samples_returns_null_ece() -> None:
    report = calculate_calibration([])
    assert report["sample_size"] == 0
    assert report["ece"] == {"home": None, "draw": None, "away": None}


def test_settlement_persists_clv_and_uses_pure_model_metrics(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "settlement-clv.db"), "p1", ("deepseek", "chatgpt"))
    repository.initialize()
    fixture = _fixture()
    repository.replace_fixtures("2099-08-27", "2099-08-27", [fixture], "2099-08-27T00:00:00+00:00")
    prediction = _prediction("p1-prediction", "deepseek")
    repository.save(prediction)
    repository.save_odds_snapshot(_odds_snapshot("odds-p1", "2099-08-27T17:00:00+00:00", 1.8))
    repository.place_bet(
        {
            "id": "p1-bet",
            "prediction_id": prediction["id"],
            "fixture_id": fixture["id"],
            "fixture_date": fixture["fixture_date"],
            "placed_at": "2099-08-27T10:00:00+00:00",
            "market": "1x2",
            "selection": "home",
            "odds": 2.0,
            "stake": 10.0,
            "league_key": "epl",
            "kickoff": fixture["kickoff"],
            "home_team": "主队",
            "away_team": "客队",
            "model_version": prediction["model_version"],
            "model_key": "deepseek",
            "competition_id": "p1",
            "bookmaker": "Test Book",
            "odds_snapshot_id": "odds-p1",
        }
    )

    result = SettlementService(repository, "p1").settle_fixture(fixture)
    settled_bet = result["items"][0]["bet"]
    report = SettlementService(repository, "p1").metrics()

    assert settled_bet["clv"] == pytest.approx(0.1111)
    assert settled_bet["closing_odds"] == 1.8
    assert report["clv_samples"] == 1
    assert report["average_clv"] == pytest.approx(0.1111)
    assert report["quality_gate"]["checks"]["clv_samples"]["value"] == 1


def test_metrics_report_paired_models_and_poisson_baseline(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "paired.db"), "p1", ("deepseek", "chatgpt"))
    repository.initialize()
    fixture = _fixture()
    repository.replace_fixtures("2099-08-27", "2099-08-27", [fixture], "2099-08-27T00:00:00+00:00")
    repository.save(_prediction("p1-deepseek", "deepseek"))
    repository.save(_prediction("p1-chatgpt", "chatgpt"))
    report = SettlementService(repository, "p1").settle_fixture(fixture)
    metrics = SettlementService(repository, "p1").metrics()

    assert report["settled_count"] == 2
    assert metrics["paired_samples"] == 1
    assert {"deepseek", "chatgpt", "gpt", "poisson", "market"}.issubset(metrics["models"])
    assert metrics["models"]["poisson"]["samples"] == 1
    assert metrics["models"]["market"]["samples"] == 1
    assert metrics["models"]["market"]["ece"] is None


def test_quality_gate_exposes_structured_state_without_threshold_relaxation() -> None:
    gate = _quality_gate(
        settled_fixtures=20,
        prediction_samples=20,
        market_comparison_samples=20,
        clv_samples=10,
        roi=0.01,
        average_clv=0.01,
        brier_improvement=0.01,
        max_drawdown=0.1,
    )

    assert gate["quality_state"] == "VALIDATED"
    assert gate["passed"] is True
    assert all(item["passed"] for item in gate["checks"].values())
