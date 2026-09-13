"""P10 model registry lifecycle and promotion gate tests."""

import pytest

from app.model_registry import (
    ModelRecord,
    ModelRegistry,
    ModelRegistryError,
    artifact_hash,
    dataset_fingerprint,
    evaluate_promotion,
)
from app.database import PredictionRepository


def record(model_version: str = "v1", status: str = "draft", **overrides) -> ModelRecord:
    values = {
        "model_key": "poisson",
        "model_version": model_version,
        "artifact_hash": artifact_hash({"model": "poisson", "version": model_version}),
        "status": status,
        "feature_version": "p3-v1",
        "dataset_fingerprint": "dataset:abc",
    }
    values.update(overrides)
    return ModelRecord(**values)


def test_artifact_hash_is_deterministic_and_key_order_insensitive() -> None:
    assert artifact_hash({"a": 1, "b": 2}) == artifact_hash({"b": 2, "a": 1})
    assert artifact_hash({"a": 1}) != artifact_hash({"a": 2})


def test_dataset_fingerprint_is_order_insensitive_and_discriminates() -> None:
    rows_a = [
        {"fixture_id": "f1", "prediction_created_at": "2026-01-01", "actual_outcome": "home"},
        {"fixture_id": "f2", "prediction_created_at": "2026-01-02", "actual_outcome": "away"},
    ]
    assert dataset_fingerprint(rows_a) == dataset_fingerprint(list(reversed(rows_a)))
    assert dataset_fingerprint(rows_a) != dataset_fingerprint(rows_a[:1])


def test_registry_register_and_get_roundtrip(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p10.db"))
    repository.initialize()
    registry = ModelRegistry(repository)

    registry.register(record())
    loaded = registry.get("poisson", "v1")

    assert loaded is not None
    assert loaded.status == "draft"
    assert loaded.feature_version == "p3-v1"
    assert loaded.provenance()["artifact_hash"] == record().artifact_hash


def test_registry_re_register_same_artifact_is_idempotent(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p10.db"))
    repository.initialize()
    registry = ModelRegistry(repository)
    registry.register(record())

    again = registry.register(record())

    assert again.status == "draft"
    assert len(registry.list(model_key="poisson")) == 1


def test_registry_rejects_same_version_with_different_artifact(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p10.db"))
    repository.initialize()
    registry = ModelRegistry(repository)
    registry.register(record())

    with pytest.raises(ModelRegistryError):
        registry.register(record(artifact_hash="deadbeef"))


def test_lifecycle_requires_evaluation_before_production(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p10.db"))
    repository.initialize()
    registry = ModelRegistry(repository)
    registry.register(record())

    registry.transition("poisson", "v1", "candidate")
    assert registry.get("poisson", "v1").status == "candidate"

    with pytest.raises(ModelRegistryError):
        registry.transition("poisson", "v1", "champion")
    assert registry.get("poisson", "v1").status == "candidate"

    promoted = registry.transition("poisson", "v1", "champion", promotion_evidence={"promoted": True})
    assert promoted.status == "champion"

    registry.transition("poisson", "v1", "retired")
    assert registry.get("poisson", "v1").status == "retired"
    with pytest.raises(ModelRegistryError):
        registry.transition("poisson", "v1", "candidate")


def test_transition_validates_target_and_unknown_models(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p10.db"))
    repository.initialize()
    registry = ModelRegistry(repository)
    registry.register(record())

    with pytest.raises(ModelRegistryError):
        registry.transition("poisson", "v1", "bogus")
    with pytest.raises(ModelRegistryError):
        registry.transition("unknown", "v9", "retired")


def test_champion_returns_latest_production_record(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p10.db"))
    repository.initialize()
    registry = ModelRegistry(repository)
    registry.register(record("v1", "champion"))
    registry.register(record("v2", "candidate"))

    champion = registry.champion("poisson")

    assert champion is not None
    assert champion.model_version == "v1"
    assert registry.champion("missing") is None


def test_promotion_gates_require_all_four_passes() -> None:
    good = {
        "brier": 0.55,
        "ece": 0.1,
        "samples": 100,
        "calibration_status": "ok",
        "window_briers": [0.53, 0.56, 0.55],
    }
    champion = {"brier": 0.58}

    result = evaluate_promotion(good, champion, leakage_violations=0)

    assert result["promoted"] is True
    assert all(result[gate] == "pass" for gate in ("metric_gate", "calibration_gate", "stability_gate", "leakage_gate"))


def test_promotion_fails_each_gate_individually() -> None:
    champion = {"brier": 0.55}
    worse_metric = {"brier": 0.60, "ece": 0.1, "samples": 100, "calibration_status": "ok", "window_briers": [0.55, 0.56]}
    assert evaluate_promotion(worse_metric, champion)["metric_gate"] == "fail"

    bad_calibration = {"brier": 0.50, "ece": 0.4, "samples": 100, "calibration_status": "ok", "window_briers": [0.55, 0.56]}
    assert evaluate_promotion(bad_calibration, champion)["calibration_gate"] == "fail"

    unstable = {"brier": 0.50, "ece": 0.1, "samples": 100, "calibration_status": "ok", "window_briers": [0.3, 0.7]}
    assert evaluate_promotion(unstable, champion)["stability_gate"] == "fail"

    leaky = {"brier": 0.50, "ece": 0.1, "samples": 100, "calibration_status": "ok", "window_briers": [0.55, 0.56]}
    assert evaluate_promotion(leaky, champion, leakage_violations=2)["leakage_gate"] == "fail"

    tiny_sample = {"brier": 0.50, "ece": 0.1, "samples": 10, "calibration_status": "ok", "window_briers": [0.55, 0.56]}
    assert evaluate_promotion(tiny_sample, champion)["metric_gate"] == "fail"


def test_promotion_without_champion_allows_first_model() -> None:
    challenger = {"brier": 0.55, "ece": 0.1, "samples": 100, "calibration_status": "ok", "window_briers": [0.55, 0.56]}

    assert evaluate_promotion(challenger, None)["promoted"] is True
