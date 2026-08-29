from datetime import UTC, datetime, timedelta

import pytest

from app.prediction_intelligence import (
    FEATURE_VERSION,
    build_feature_snapshot,
    build_performance_profiles,
    evaluate_probabilities,
    fit_temperature,
    resolve_model_weights,
    run_backtest,
    split_time_ordered,
    weighted_ensemble,
)


def _fixture() -> dict:
    return {
        "id": "p3-fixture",
        "fixture_date": "2026-08-10",
        "kickoff": "2026-08-10T18:00:00+00:00",
    }


def _evidence() -> dict:
    return {
        "captured_at": "2026-08-09T12:00:00+00:00",
        "synced_at": "2026-08-09T12:00:00+00:00",
        "recent_form": {
            "home": [
                {"date": "2026-08-09", "result": "W", "score": "2 - 0", "team_is_home": True},
                {"date": "2026-08-11", "result": "W", "score": "3 - 0", "team_is_home": True},
            ],
            "away": [
                {"date": "2026-08-08", "result": "D", "score": "1 - 1", "team_is_home": False},
            ],
        },
        "availability": {"updated_at": "2026-08-09T11:00:00+00:00"},
        "lineup": {"confirmed": False, "updated_at": "2026-08-09T11:00:00+00:00"},
        "odds": {"home": 2.0, "draw": 3.2, "away": 4.0, "updated_at": "2026-08-09T11:00:00+00:00"},
    }


def _evaluation_row(index: int, model_key: str = "deepseek") -> dict:
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return {
        "fixture_id": f"fixture-{index}",
        "prediction_created_at": created.isoformat(),
        "settled_at": (created + timedelta(days=1)).isoformat(),
        "league_key": "epl",
        "model_key": model_key,
        "model_probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "actual_outcome": "home" if index % 2 == 0 else "away",
        "clv": 0.01,
    }


def test_feature_snapshot_rejects_future_rows_and_is_versioned() -> None:
    snapshot = build_feature_snapshot(
        _fixture(),
        _evidence(),
        "2026-08-10T00:00:00+00:00",
        standings={
            "home": {"played": 10, "goals_for": 20, "goals_against": 10, "points": 24},
            "away": {"played": 10, "goals_for": 12, "goals_against": 15, "points": 15},
        },
    )

    assert snapshot["feature_version"] == FEATURE_VERSION
    assert snapshot["recent_form"]["home"]["sample_size"] == 1
    assert snapshot["leakage_check"]["passed"] is False
    assert "recent_form.home" in snapshot["leakage_check"]["rejected_future_fields"]
    assert snapshot["market_context"]["used_for_probability"] is False


def test_feature_snapshot_rejects_future_standings() -> None:
    snapshot = build_feature_snapshot(
        _fixture(),
        _evidence(),
        "2026-08-10T00:00:00+00:00",
        standings={
            "updated_at": "2026-08-10T01:00:00+00:00",
            "home": {"played": 10, "goals_for": 20, "goals_against": 10, "points": 24},
            "away": {"played": 10, "goals_for": 12, "goals_against": 15, "points": 15},
        },
    )

    assert snapshot["team_strength"]["home"]["status"] == "missing"
    assert "standings" in snapshot["leakage_check"]["rejected_future_fields"]


def test_weighted_ensemble_matches_documented_weighted_average() -> None:
    result = weighted_ensemble(
        {
            "deepseek": {"home": 0.60, "draw": 0.20, "away": 0.20},
            "chatgpt": {"home": 0.70, "draw": 0.20, "away": 0.10},
            "poisson": {"home": 0.50, "draw": 0.30, "away": 0.20},
        },
        weights={"deepseek": 0.4, "chatgpt": 0.4, "poisson": 0.2},
    )

    assert result["ensemble_probabilities"]["home"] == pytest.approx(0.62)
    assert result["weights"] == {"deepseek": 0.4, "chatgpt": 0.4, "poisson": 0.2}


def test_league_profile_falls_back_to_global_and_low_sample_shrinks() -> None:
    rows = [_evaluation_row(index) for index in range(30)]
    profiles = build_performance_profiles(rows)
    resolved = resolve_model_weights(
        ["deepseek"],
        profiles=profiles,
        league_key="laliga",
    )
    assert profiles["deepseek|global"]["sample_size"] == 30
    assert resolved["deepseek"] > 0

    low_sample = {
        "deepseek|global": {
            "sample_size": 1,
            "raw_weight": 100.0,
            "drift_factor": 1.0,
        }
    }
    assert resolve_model_weights(["deepseek"], profiles=low_sample)["deepseek"] < 100.0


def test_temperature_calibration_uses_only_calibration_slice() -> None:
    rows = [_evaluation_row(index) for index in range(150)]
    train, calibration, evaluation = split_time_ordered(rows)
    calibration_state = fit_temperature(calibration)

    assert len(train) == 90
    assert len(calibration) == 30
    assert len(evaluation) == 30
    assert {row["fixture_id"] for row in calibration}.isdisjoint({row["fixture_id"] for row in evaluation})
    assert calibration_state["status"] == "ok"
    assert calibration_state["sample_size"] == 30


def test_backtest_reports_leakage_safe_insufficient_calibration_without_fabricating_gain() -> None:
    result = run_backtest([_evaluation_row(index) for index in range(20)])

    assert result["status"] == "ok"
    assert result["leakage_check"] == {"passed": True, "future_rows_used": 0}
    assert result["calibration"]["status"] == "calibration_unavailable"
    assert result["ablation"]["baseline_plus_form"]["status"] == "unavailable"
    assert result["baseline"]["samples"] == result["p3_ensemble"]["samples"]


def test_evaluation_returns_explicit_empty_state() -> None:
    assert evaluate_probabilities([], lambda row: row.get("model_probabilities"))["status"] == "insufficient_sample"
