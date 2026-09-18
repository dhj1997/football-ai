"""Focused Round 4 transparent probability engine contracts."""

from copy import deepcopy

import pytest

from app.no_ml_guard import NoMLNumericPathError
from app.probability_engine import (
    ProbabilityEngineError,
    TransparentProbabilityEngine,
    build_score_probability_matrix,
    dixon_coles_correction,
    poisson_goal_distribution,
)


CUTOFF = "2026-09-16T03:41:22+00:00"


def snapshot(*, future: bool = False, extreme_defense: bool = False, source: str = "completed_match_results") -> dict:
    rows = []
    values = {
        ("home", "attack_strength"): 1.15,
        ("away", "attack_strength"): 0.95,
        ("home", "defense_strength"): 1_703_703_703.7 if extreme_defense else 1.05,
        ("away", "defense_strength"): 0.95,
        ("home", "team_elo"): 1550.0,
        ("away", "team_elo"): 1450.0,
        ("home", "fatigue_score"): 0.1,
        ("away", "fatigue_score"): 0.0,
    }
    for (side, name), value in values.items():
        rows.append(
            {
                "feature_name": name,
                "feature_value": value,
                "source": source,
                "status": "future" if future and name == "team_elo" else "available",
                "quality_score": 0.9,
                "available_at": "2026-09-16T03:41:23+00:00" if future and name == "team_elo" else CUTOFF,
                "prediction_cutoff_at": CUTOFF,
                "feature_version": "round3-feature-engine-v2",
                "side": side,
                "entity_type": "team",
                "entity_id": f"{side}-team",
            }
        )
    for side in ("home", "away"):
        rows.append(
            {
                "feature_name": "player_impact",
                "feature_value": None,
                "source": "player_impact_rules",
                "status": "missing",
                "missing_reason": "player_impact_rule_or_evidence_unavailable",
                "quality_score": 0.0,
                "available_at": None,
                "prediction_cutoff_at": CUTOFF,
                "feature_version": "round3-feature-engine-v2",
                "side": side,
                "entity_type": "team",
                "entity_id": f"{side}-team",
            }
        )
    return {
        "snapshot_id": "feature:round4-test",
        "fixture_id": "round4-fixture",
        "prediction_cutoff_at": CUTOFF,
        "computed_at": CUTOFF,
        "feature_version": "round3-feature-engine-v2",
        "leakage_detected": False,
        "leakage_check": {"passed": True, "violations": []},
        "features": rows,
    }


def test_poisson_distribution_handles_zero_and_tail() -> None:
    zero = poisson_goal_distribution(0.0, max_goals=10)
    high = poisson_goal_distribution(8.0, max_goals=10)

    assert zero[0] == pytest.approx(1.0)
    assert sum(zero) == pytest.approx(1.0)
    assert sum(high) == pytest.approx(1.0)
    assert high[-1] > 0


def test_score_matrix_dixon_coles_is_non_negative_and_normalized() -> None:
    poisson = build_score_probability_matrix(1.5, 1.1, rho=0.0)
    corrected = build_score_probability_matrix(1.5, 1.1, rho=-0.1)

    assert sum(row["probability"] for row in poisson) == pytest.approx(1.0)
    assert sum(row["probability"] for row in corrected) == pytest.approx(1.0)
    assert all(row["probability"] >= 0 for row in corrected)
    assert corrected[0]["dixon_coles_factor"] != poisson[0]["dixon_coles_factor"]
    with pytest.raises(ProbabilityEngineError, match="safe range"):
        dixon_coles_correction(0, 0, 1.5, 1.1, rho=0.5)


def test_probability_engine_aggregates_1x2_totals_and_btts() -> None:
    result = TransparentProbabilityEngine().calculate(snapshot(), match_id="round4-fixture")

    assert result["home_expected_goals"] > 0
    assert result["away_expected_goals"] > 0
    assert result["total_expected_goals"] == pytest.approx(
        result["home_expected_goals"] + result["away_expected_goals"]
    )
    assert sum(result[key] for key in ("home_win_probability", "draw_probability", "away_win_probability")) == pytest.approx(1.0)
    for values in result["over_under_probabilities"].values():
        assert values["over"] + values["under"] == pytest.approx(1.0)
    assert result["btts_probability"]["yes"] + result["btts_probability"]["no"] == pytest.approx(1.0)
    assert sum(row["probability"] for row in result["score_probability_matrix"]) == pytest.approx(1.0)


def test_probability_engine_rejects_future_feature() -> None:
    with pytest.raises(ProbabilityEngineError, match="production-safe"):
        TransparentProbabilityEngine().calculate(snapshot(future=True), match_id="round4-fixture")


def test_probability_engine_is_reproducible_and_explanation_is_read_only() -> None:
    first = TransparentProbabilityEngine().calculate(snapshot(), match_id="round4-fixture")
    second = TransparentProbabilityEngine().calculate(deepcopy(snapshot()), match_id="round4-fixture")

    assert first == second
    first["probability_explanation"]["inputs"]["home_attack_strength"] = 999
    assert second["home_expected_goals"] != 999


def test_probability_engine_rejects_llm_numeric_feature_source() -> None:
    with pytest.raises(NoMLNumericPathError, match="source rejected"):
        TransparentProbabilityEngine().calculate(snapshot(source="deepseek_numeric"), match_id="round4-fixture")


def test_probability_engine_requires_snapshot_identity_and_clean_leakage_audit() -> None:
    missing_id = snapshot()
    missing_id.pop("snapshot_id")
    with pytest.raises(ProbabilityEngineError, match="real feature_snapshot_id"):
        TransparentProbabilityEngine().calculate(missing_id, match_id="round4-fixture", feature_snapshot_id="caller-id")

    mismatched_id = snapshot()
    with pytest.raises(ProbabilityEngineError, match="does not match"):
        TransparentProbabilityEngine().calculate(mismatched_id, match_id="round4-fixture", feature_snapshot_id="caller-id")

    for audit in (
        None,
        {"passed": False, "violations": []},
        {"passed": True, "violations": [{"reason": "future"}]},
        {"passed": True, "violations": [], "status": "WARN"},
        {"passed": True, "violations": [], "rejected_future_fields": ["team_elo"]},
    ):
        invalid = snapshot()
        invalid["leakage_check"] = audit
        with pytest.raises(ProbabilityEngineError, match="leakage"):
            TransparentProbabilityEngine().calculate(invalid, match_id="round4-fixture")


def test_probability_engine_requires_feature_cutoff_and_version() -> None:
    missing_cutoff = snapshot()
    missing_cutoff["features"][0].pop("prediction_cutoff_at")
    with pytest.raises(ProbabilityEngineError, match="prediction_cutoff_at is required"):
        TransparentProbabilityEngine().calculate(missing_cutoff, match_id="round4-fixture")

    wrong_version = snapshot()
    wrong_version["features"][0]["feature_version"] = "round3-feature-engine-old"
    with pytest.raises(ProbabilityEngineError, match="version"):
        TransparentProbabilityEngine().calculate(wrong_version, match_id="round4-fixture")


def test_dixon_coles_rejects_invalid_expected_goals() -> None:
    with pytest.raises(ProbabilityEngineError, match="finite and non-negative"):
        dixon_coles_correction(0, 0, -1.0, 1.1, rho=-0.1)


def test_extreme_strength_uses_explicit_neutral_fallback() -> None:
    result = TransparentProbabilityEngine().calculate(
        snapshot(extreme_defense=True),
        match_id="round4-fixture",
    )

    assert result["model_input_quality"]["state"] == "degraded"
    assert any(item["reason"] == "feature_value_out_of_range" for item in result["model_input_quality"]["fallbacks"])
    assert result["home_expected_goals"] < 4.5
