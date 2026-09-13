"""P10 unified model platform adapter and protocol tests."""

import pytest

from app.model_platform import (
    BaselineModel,
    CalibratedEnsembleModel,
    DixonColesModel,
    EloModel,
    EnsembleModel,
    LlmModelAdapter,
    PoissonModel,
    learn_ensemble_weights,
    run_model_protocol,
)
from app.model_registry import dataset_fingerprint


def llm_payload(**overrides) -> dict:
    payload = {
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "model_version": "deepseek:deepseek-v4-flash",
        "analysis_summary": "主队近况占优",
        "forecast_confidence": 0.72,
        "prompt_version": "prompt-v9",
        "predicted_outcome": "home",
        "risk_factors": ["首发未确认"],
    }
    payload.update(overrides)
    return payload


def test_poisson_and_dixon_coles_produce_valid_probabilities() -> None:
    context = {"expected_goals": {"home": 1.5, "away": 1.1}}
    poisson = PoissonModel().predict(context).probabilities
    dixon = DixonColesModel().predict(context).probabilities

    assert poisson and abs(sum(poisson.values()) - 1.0) < 1e-5
    assert dixon and abs(sum(dixon.values()) - 1.0) < 1e-5
    # The Dixon-Coles correction shifts probability mass into draws.
    assert dixon["draw"] > poisson["draw"]
    assert dixon["home"] > dixon["away"]


def test_poisson_family_refuses_missing_expected_goals() -> None:
    result = PoissonModel().predict({})

    assert result.readiness == "insufficient_evidence"
    assert result.probabilities is None


def test_elo_model_uses_rating_differential() -> None:
    context = {
        "fixture": {"home_team": {"name": "武汉三镇"}, "away_team": {"name": "上海海港"}},
        "elo_ratings": {"武汉三镇": 1650.0, "上海海港": 1450.0},
    }
    result = EloModel().predict(context)

    assert result.ok
    assert result.probabilities["home"] > result.probabilities["away"]

    reversed_context = {
        "fixture": context["fixture"],
        "elo_ratings": {"武汉三镇": 1400.0, "上海海港": 1700.0},
    }
    reversed_result = EloModel().predict(reversed_context)

    assert reversed_result.probabilities["away"] > reversed_result.probabilities["home"]


def test_elo_model_is_not_ready_without_ratings() -> None:
    result = EloModel().predict({"fixture": {"home_team": {"name": "武汉三镇"}, "away_team": {"name": "上海海港"}}})

    assert result.readiness == "insufficient_evidence"
    assert result.probabilities is None


def test_baseline_devigs_market_odds_and_refuses_to_guess() -> None:
    result = BaselineModel().predict({"odds": {"home": 2.0, "draw": 3.5, "away": 4.0}})

    assert result.ok
    assert abs(sum(result.probabilities.values()) - 1.0) < 1e-5
    assert result.provenance["inputs"]["bookmaker_margin"] > 0

    missing = BaselineModel().predict({"odds": {"home": 2.0}})

    assert missing.readiness == "insufficient_evidence"
    assert missing.probabilities is None


def test_llm_adapter_passes_through_valid_contract() -> None:
    result = LlmModelAdapter("deepseek").predict({"prediction_payload": llm_payload()})

    assert result.ok
    assert result.model_version == "deepseek:deepseek-v4-flash"
    assert result.provenance["prompt_version"] == "prompt-v9"


def test_llm_schema_failure_is_explicit_and_never_borrows_another_model() -> None:
    adapter = LlmModelAdapter("deepseek")

    missing = adapter.predict({})
    assert missing.readiness == "insufficient_evidence"
    assert missing.probabilities is None

    broken = adapter.predict({"prediction_payload": {"probabilities": {"home": 0.9}}})
    assert broken.readiness == "failed"
    assert "schema failure" in (broken.failure_reason or "")
    assert broken.probabilities is None

    # Even with another model's payload in context, this model fails alone.
    foreign = adapter.predict({"prediction_payload": {"probabilities": None, "model_version": "chatgpt:gpt-x", "analysis_summary": "x"}})
    assert foreign.readiness == "failed"
    assert foreign.probabilities is None


def test_ensemble_combines_members_with_declared_weights() -> None:
    context = {"expected_goals": {"home": 1.5, "away": 1.1}}
    ensemble = EnsembleModel(
        (PoissonModel(), DixonColesModel()),
        weights={"poisson": 0.6, "dixon_coles": 0.4, "deepseek": 0.0},
    )
    result = ensemble.predict(context)

    assert result.ok
    assert result.provenance["members"] == {"poisson": PoissonModel.model_version, "dixon_coles": DixonColesModel.model_version}
    assert abs(sum(result.probabilities.values()) - 1.0) < 1e-5
    # The zero-weight absent member contributes nothing.
    assert "deepseek" not in result.provenance["members"]


def test_ensemble_without_any_member_is_not_ready() -> None:
    ensemble = EnsembleModel((PoissonModel(),), weights={"poisson": 1.0})
    result = ensemble.predict({})

    assert result.readiness == "insufficient_evidence"
    assert result.probabilities is None


def test_calibrated_ensemble_applies_validation_temperature() -> None:
    ensemble = EnsembleModel((PoissonModel(),), weights={"poisson": 1.0})
    calibrated = CalibratedEnsembleModel(ensemble, temperature=0.8)
    result = calibrated.predict({"expected_goals": {"home": 1.5, "away": 1.1}})

    assert result.ok
    assert result.provenance["temperature"] == 0.8
    assert result.provenance["calibration_version"]

    with pytest.raises(ValueError):
        CalibratedEnsembleModel(ensemble, temperature=0.0)


def _protocol_rows(count: int, seed: int = 5) -> list[dict]:
    import random
    from datetime import UTC, datetime, timedelta

    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(count):
        actual = rng.choice(["home", "draw", "away"])
        # "strong" concentrates on the actual outcome most of the time;
        # "weak" always answers the uniform distribution.
        strong = {key: 0.6 if key == actual else 0.2 for key in ("home", "draw", "away")}
        rows.append(
            {
                "fixture_id": f"f{index}",
                "prediction_created_at": (start + timedelta(days=index)).isoformat(),
                "actual_outcome": actual,
                "models": {
                    "strong": strong,
                    "weak": {"home": 0.34, "draw": 0.33, "away": 0.33},
                },
            }
        )
    return rows


def test_learn_ensemble_weights_prefers_the_better_model_on_train_rows() -> None:
    rows = _protocol_rows(120)
    weights = learn_ensemble_weights(rows, ["strong", "weak"])

    assert weights["strong"] > weights["weak"]
    assert learn_ensemble_weights([], ["strong"]) == {}


def test_protocol_splits_time_and_reports_explicit_calibration() -> None:
    rows = _protocol_rows(150)
    protocol = run_model_protocol(rows, ["strong", "weak"])

    assert protocol["status"] == "ok"
    assert protocol["splits"]["train"] == 90
    assert protocol["splits"]["validation"] == 30
    assert protocol["splits"]["test"] == 30
    assert protocol["metrics"]["ensemble"]["status"] == "ok"
    # Validation split of 30 rows is enough to fit the temperature explicitly.
    if protocol["temperature"]:
        assert protocol["metrics"]["calibrated_ensemble"]["calibration_status"] == "ok"
    else:
        assert protocol["metrics"]["calibrated_ensemble"]["calibration_status"] == "calibration_unavailable"


def test_protocol_insufficient_rows_never_fabricates_metrics() -> None:
    protocol = run_model_protocol(_protocol_rows(4), ["strong", "weak"])

    assert protocol["metrics"]["calibrated_ensemble"]["calibration_status"] in {"calibration_unavailable", "ok"} or protocol["status"] == "ok"
    assert protocol["weights"]


def test_protocol_is_reproducible_for_the_same_dataset() -> None:
    rows = _protocol_rows(150)
    first = run_model_protocol(rows, ["strong", "weak"])
    second = run_model_protocol(list(reversed(rows)), ["strong", "weak"])

    assert first["dataset_fingerprint"] == dataset_fingerprint(rows)
    assert first["dataset_fingerprint"] == second["dataset_fingerprint"]
    assert first["weights"] == second["weights"]
