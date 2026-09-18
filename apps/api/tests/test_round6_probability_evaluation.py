"""Focused contracts for the pure Round 6 probability metric layer."""

from __future__ import annotations

import math

import pytest

from app.probability_evaluation import (
    LOG_LOSS_EPSILON,
    LOG_LOSS_EPSILON_VERSION,
    METRICS_VERSION,
    MIN_SAMPLES,
    PROBABILITY_SUM_TOLERANCE,
    ProbabilityEvaluationError,
    ProbabilityEvaluationService,
    normalize_probability_vector,
)


def observation(
    probabilities: dict[str, float],
    actual_outcome: str,
) -> dict[str, object]:
    return {
        "probabilities": probabilities,
        "actual_outcome": actual_outcome,
    }


def test_single_observation_uses_published_multiclass_formulas() -> None:
    result = ProbabilityEvaluationService().evaluate(
        {"home": 0.5, "draw": 0.3, "away": 0.2},
        "home",
    )

    assert result["metrics_version"] == METRICS_VERSION
    assert result["log_loss_epsilon_version"] == LOG_LOSS_EPSILON_VERSION
    assert result["log_loss"] == pytest.approx(-math.log(0.5))
    assert result["brier"] == pytest.approx(0.38)
    assert result["rps"] == pytest.approx(((0.5 - 1.0) ** 2 + (0.8 - 1.0) ** 2) / 2)
    assert result["predicted_outcome"] == "home"
    assert result["accuracy"] == 1.0


def test_zero_actual_probability_uses_fixed_epsilon() -> None:
    result = ProbabilityEvaluationService().evaluate(
        {"home": 0.0, "draw": 0.5, "away": 0.5},
        "home",
    )

    assert result["log_loss_epsilon"] == LOG_LOSS_EPSILON
    assert result["log_loss"] == pytest.approx(-math.log(LOG_LOSS_EPSILON))


@pytest.mark.parametrize(
    "probabilities",
    [
        {"home": 0.5, "draw": 0.5},
        {"home": 0.5, "draw": 0.3, "away": 0.2, "other": 0.0},
        {"home": -0.1, "draw": 0.5, "away": 0.6},
        {"home": float("nan"), "draw": 0.5, "away": 0.5},
        {"home": float("inf"), "draw": 0.0, "away": 0.0},
        {"home": True, "draw": 0.0, "away": 0.0},
        {"home": "0.5", "draw": 0.3, "away": 0.2},
        {"home": 0.5, "draw": 0.3, "away": 0.1},
    ],
)
def test_probability_vectors_fail_closed(probabilities: dict[str, object]) -> None:
    with pytest.raises(ProbabilityEvaluationError):
        normalize_probability_vector(probabilities)


def test_only_tiny_sum_drift_is_normalized() -> None:
    raw = {
        "home": 0.5,
        "draw": 0.3,
        "away": 0.2 + PROBABILITY_SUM_TOLERANCE / 2,
    }

    normalized = normalize_probability_vector(raw)

    assert math.fsum(normalized.values()) == pytest.approx(1.0)
    assert normalized["away"] != raw["away"]
    with pytest.raises(ProbabilityEvaluationError):
        normalize_probability_vector(
            {
                "home": 0.5,
                "draw": 0.3,
                "away": 0.2 + PROBABILITY_SUM_TOLERANCE * 2,
            }
        )


def test_calibration_uses_ten_one_vs_rest_bins_and_keeps_p_one_in_last_bin() -> None:
    rows = [
        observation({"home": 0.0, "draw": 0.5, "away": 0.5}, "away"),
        observation({"home": 0.1, "draw": 0.5, "away": 0.4}, "home"),
        observation({"home": 1.0, "draw": 0.0, "away": 0.0}, "home"),
    ]

    result = ProbabilityEvaluationService().calibration(rows)
    home_bins = result["bins"]["home"]

    assert result["status"] == "insufficient_data"
    assert result["sample_count"] == 3
    assert len(home_bins) == 10
    assert home_bins[0]["sample_count"] == 1
    assert home_bins[1]["sample_count"] == 1
    assert home_bins[9]["sample_count"] == 1
    assert home_bins[9]["mean_predicted_probability"] == 1.0
    assert home_bins[9]["actual_frequency"] == 1.0
    assert home_bins[9]["gap"] == 0.0
    assert result["ece"] is not None


def test_aggregate_preserves_descriptive_values_below_threshold_and_is_reproducible() -> None:
    rows = [
        observation({"home": 0.6, "draw": 0.2, "away": 0.2}, "home"),
        observation({"home": 0.2, "draw": 0.3, "away": 0.5}, "draw"),
    ]
    service = ProbabilityEvaluationService()

    first = service.aggregate(rows)
    second = service.aggregate(rows)

    assert first == second
    assert first["status"] == "insufficient_data"
    assert first["sample_count"] == 2
    assert all(first[key] is not None for key in ("log_loss", "brier", "rps", "accuracy"))
    assert first["calibration"]["status"] == "insufficient_data"

    enough = service.aggregate(rows * 15)
    assert enough["sample_count"] == 30
    assert enough["status"] == "ok"
    assert enough["calibration"]["status"] == "ok"


def test_stable_temporal_integration_names_reuse_the_metric_contract() -> None:
    probabilities = {"home": 0.6, "draw": 0.2, "away": 0.2}
    service = ProbabilityEvaluationService(min_samples=1)

    assert MIN_SAMPLES == 30
    assert service.normalize(probabilities) == normalize_probability_vector(probabilities)
    assert service.score(probabilities, "home") == service.evaluate(probabilities, "home")
    assert service.summarize([(probabilities, "home")]) == service.aggregate(
        [observation(probabilities, "home")]
    )


def test_aggregate_rejects_invalid_outcomes_and_missing_fields() -> None:
    service = ProbabilityEvaluationService()

    with pytest.raises(ProbabilityEvaluationError):
        service.aggregate(
            [observation({"home": 0.5, "draw": 0.3, "away": 0.2}, "H")]
        )
    with pytest.raises(ProbabilityEvaluationError):
        service.aggregate([{"actual_outcome": "home"}])


def test_coverage_reports_missing_rows_without_imputation() -> None:
    assert ProbabilityEvaluationService.coverage(
        eligible_count=10,
        available_count=6,
    ) == {
        "eligible_count": 10,
        "available_count": 6,
        "missing_count": 4,
        "coverage": 0.6,
    }
    assert ProbabilityEvaluationService.coverage(
        eligible_count=0,
        available_count=0,
    )["coverage"] is None
    with pytest.raises(ValueError):
        ProbabilityEvaluationService.coverage(
            eligible_count=2,
            available_count=3,
        )
