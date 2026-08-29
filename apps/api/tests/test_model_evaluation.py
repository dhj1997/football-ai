from datetime import UTC, datetime, timedelta

from app.database import PredictionRepository
from app.model_evaluation import (
    ModelEvaluationService,
    audit_prediction_leakage,
    chronological_split,
    leakage_audit,
    sample_confidence,
)


def _rows(count: int = 40, league: str = "EPL") -> list[dict]:
    rows = []
    for index in range(count):
        kickoff = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index)
        prediction_timestamp = kickoff - timedelta(hours=24)
        actual = "home" if index % 2 == 0 else "away"
        base = {"home": 0.50, "draw": 0.20, "away": 0.30}
        deepseek = {"home": 0.60, "draw": 0.15, "away": 0.25}
        gpt = {"home": 0.45, "draw": 0.25, "away": 0.30}
        for model_key, probabilities in (("deepseek", deepseek), ("chatgpt", gpt)):
            rows.append(
                {
                    "prediction_id": f"{model_key}-{index}",
                    "fixture_id": f"fixture-{index}",
                    "league_key": league.casefold(),
                    "kickoff_at": kickoff.isoformat(),
                    "prediction_created_at": prediction_timestamp.isoformat(),
                    "model_key": model_key,
                    "model_version": f"{model_key}:test-v1",
                    "feature_version": "p3-v1",
                    "ensemble_version": "p3-ensemble-v1",
                    "calibration_version": "p3-temperature-v1",
                    "model_probabilities": probabilities,
                    "baseline": {"probabilities": base},
                    "actual_outcome": actual,
                    "settled_at": (kickoff + timedelta(hours=2)).isoformat(),
                    "feature_snapshot": {"captured_at": (prediction_timestamp - timedelta(hours=1)).isoformat()},
                }
            )
    return rows


def test_chronological_split_orders_by_kickoff_and_freezes_three_slices() -> None:
    rows = [{"fixture_id": "late", "kickoff_at": "2025-01-03T00:00:00+00:00"}, {"fixture_id": "early", "kickoff_at": "2025-01-01T00:00:00+00:00"}, {"fixture_id": "middle", "kickoff_at": "2025-01-02T00:00:00+00:00"}]
    train, validation, test = chronological_split(rows)
    assert [row["fixture_id"] for row in train] == ["early"]
    assert [row["fixture_id"] for row in validation] == ["middle"]
    assert [row["fixture_id"] for row in test] == ["late"]


def test_future_result_odds_and_feature_captures_fail_audit() -> None:
    cutoff = "2025-01-01T00:00:00+00:00"
    row = {
        "prediction_id": "prediction-1",
        "prediction_timestamp": cutoff,
        "result": {"captured_at": "2025-01-01T01:00:00+00:00"},
        "odds": {"captured_at": "2025-01-01T02:00:00+00:00"},
        "feature_snapshot": {"captured_at": "2025-01-01T03:00:00+00:00"},
    }
    violations = audit_prediction_leakage(row)
    assert len(violations) == 3
    assert audit_prediction_leakage({"prediction_id": "prediction-2", "prediction_timestamp": cutoff}, auxiliary=[{"captured_at": "2025-01-01T01:00:00+00:00"}])
    assert leakage_audit([row])["violations"] == 3
    assert audit_prediction_leakage({**row, "result": {"captured_at": "2024-12-31T23:00:00+00:00"}, "odds": None, "feature_snapshot": None}) == []


def test_evaluation_uses_same_frozen_test_fixtures_and_validation_only_calibration() -> None:
    result = ModelEvaluationService().evaluate(_rows(40))
    report = result["reports"]["EPL"]
    assert report["test_fixture_ids"]
    assert report["weights_fit_on"] == "train"
    assert report["calibration"]["fit_on"] == "validation"
    assert report["calibration"]["fit_as_of"] < report["test_prediction_range"]["start"]
    assert set(result["model_comparison"]["EPL"]) == {"baseline", "poisson", "gpt", "deepseek", "ensemble", "calibrated_ensemble"}
    assert set(report["common_test_fixture_ids"]) == set(report["test_fixture_ids"])
    assert "confidence_interval_95" in report["models"]["ensemble"]["statistics"]["brier"]
    assert "full_ensemble" in report["ablation"]
    assert result["betting"]["status"] == "unavailable"


def test_small_sample_is_explicitly_insufficient_and_model_absence_unavailable() -> None:
    result = ModelEvaluationService().evaluate(_rows(8, "CSL"))
    assert result["reports"]["CSL"]["sample_size_warning"] == "insufficient_sample"
    assert sample_confidence(29) == ("insufficient_sample", "insufficient_sample")
    assert result["reports"]["CSL"]["models"]["deepseek"]["status"] == "insufficient_sample"
    unavailable = ModelEvaluationService().evaluate([row for row in _rows(8, "LAL") if row["model_key"] == "chatgpt"])
    assert unavailable["reports"]["LAL"]["models"]["deepseek"]["status"] == "unavailable"


def test_experiment_persistence_is_idempotent_and_does_not_touch_betting_tables(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "evaluation.db"))
    repository.initialize()
    service = ModelEvaluationService(repository)
    result = service.evaluate(_rows(10))
    before_bets = repository.bets()
    stored = repository.save_model_evaluation(result)
    repository.save_model_evaluation(result)
    assert stored["experiment_id"] == result["experiment_id"]
    assert repository.model_evaluation_experiment(result["experiment_id"])["experiment_id"] == result["experiment_id"]
    assert repository.model_evaluation_metrics(result["experiment_id"])
    assert repository.bets() == before_bets == []
