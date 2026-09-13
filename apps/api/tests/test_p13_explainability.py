"""P13 explainable AI: graph construction, grounding and disagreement tests."""

import pytest

from app.explainability import (
    build_explanation_graph,
    grounded_narrative,
    model_disagreement,
    validate_grounded,
)


def prediction_payload(**overrides) -> dict:
    payload = {
        "id": "pred-1",
        "fixture_id": "sportsdb-1",
        "created_at": "2026-09-01T10:00:00+00:00",
        "model_key": "deepseek",
        "model_version": "deepseek:deepseek-v4-flash",
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
    }
    payload.update(overrides)
    return payload


def feature_snapshot() -> dict:
    return {
        "feature_version": "p3-v1",
        "captured_at": "2026-09-01T10:00:00+00:00",
        "source_captured_at": "2026-09-01T09:00:00+00:00",
        "recent_form": {
            "home": {"points_per_game": 2.2},
            "away": {"points_per_game": 1.0},
        },
        "team_strength": {"home": 3.1, "away": 2.2},
        "squad_status": {"home": {"available": 18}, "away": {"available": 21}},
        "leakage_check": {"passed": True, "rejected_future_fields": []},
    }


def evidence() -> dict:
    return {
        "recent_form": {"home": [{"x": 1}] * 15, "away": [{"x": 1}] * 15, "updated_at": "2026-09-01T09:00:00+00:00"},
        "lineup": {"confirmed": True, "updated_at": "2026-09-01T09:30:00+00:00"},
        "odds": {"home": 2.0, "draw": 3.5, "away": 4.0, "captured_at": "2026-09-01T09:40:00+00:00"},
        "source": "dongqiudi",
    }


def test_model_disagreement_is_computed_from_actual_outputs() -> None:
    outputs = {
        "deepseek": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "chatgpt": {"home": 0.3, "draw": 0.3, "away": 0.4},
    }
    result = model_disagreement(outputs)

    assert result["model_count"] == 2
    assert result["per_outcome_spread"]["home"] == 0.3
    assert result["most_divergent_pair"] == {"model_a": "chatgpt", "model_b": "deepseek"}
    assert 0 < result["disagreement_score"] < 1

    assert model_disagreement({"deepseek": {"home": 0.5, "draw": 0.3, "away": 0.2}}) is None
    assert model_disagreement({"deepseek": None}) is None


def test_graph_links_every_reason_to_refs_and_provenance() -> None:
    graph = build_explanation_graph(
        prediction_payload(),
        feature_snapshot=feature_snapshot(),
        evidence=evidence(),
        model_outputs={
            "deepseek": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "poisson": {"home": 0.45, "draw": 0.3, "away": 0.25},
        },
    )

    assert graph["explanation_version"] == "p13-explain-v1"
    assert graph["prediction_ref"]["fixture_id"] == "sportsdb-1"
    assert graph["reasons"], "core factors should exist from the feature snapshot"
    for reason in graph["reasons"]:
        assert reason["kind"] in {"core_factor", "evidence", "model_disagreement", "completeness", "counterfactual"}
        assert reason["refs"]
        assert reason["provenance"] is not None
        assert reason["direction"] in {"favor_home", "favor_away", "neutral"}
    assert validate_grounded(graph) == []


def test_missing_evidence_is_shown_as_missing() -> None:
    graph = build_explanation_graph(prediction_payload(), feature_snapshot=None, evidence={})

    nodes = {node["kind"]: node for node in graph["nodes"]["evidence"]}
    missing = [kind for kind, node in nodes.items() if node["status"] == "missing"]
    assert "recent_form" in missing and "lineup" in missing and "odds" in missing
    completeness = next(reason for reason in graph["reasons"] if reason["kind"] == "completeness")
    assert "odds" in completeness["statement"]
    assert graph["confidence"]["data_completeness"] < 0.5


def test_explanation_confidence_is_separate_from_prediction_confidence() -> None:
    graph = build_explanation_graph(
        prediction_payload(forecast_confidence=0.9),
        feature_snapshot=feature_snapshot(),
        evidence=evidence(),
        model_outputs={
            "deepseek": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "chatgpt": {"home": 0.5, "draw": 0.3, "away": 0.2},
        },
    )

    assert graph["nodes"]["model_output"]["prediction_confidence"] == 0.9
    assert set(graph["confidence"]) == {"note", "data_completeness", "model_consistency", "evidence_quality"}
    # Identical model outputs mean full consistency regardless of prediction confidence.
    assert graph["confidence"]["model_consistency"] == 1.0
    assert graph["confidence"]["evidence_quality"] is None  # honest: no quality score supplied


def test_narrative_is_fully_grounded_in_the_graph() -> None:
    graph = build_explanation_graph(
        prediction_payload(),
        feature_snapshot=feature_snapshot(),
        evidence=evidence(),
    )

    narrative = graph["narrative"]
    assert narrative
    reason_ids = {reason["id"] for reason in graph["reasons"]}
    assert all(item["reason_id"] in reason_ids for item in narrative)
    assert validate_grounded(graph) == []


def test_counterfactual_is_explicitly_unavailable() -> None:
    graph = build_explanation_graph(prediction_payload(), feature_snapshot=feature_snapshot())

    assert graph["counterfactual"] == {
        "available": False,
        "reason": "当前模型不支持反事实分析；仅在明确标注假设时展示",
        "refs": [],
    }


def test_explanation_is_read_only_over_the_prediction() -> None:
    prediction = prediction_payload()
    original = dict(prediction)
    evidence_payload = evidence()
    evidence_original = dict(evidence_payload)

    build_explanation_graph(prediction, feature_snapshot=feature_snapshot(), evidence=evidence_payload, model_outputs={"deepseek": {"home": 0.5, "draw": 0.3, "away": 0.2}})

    assert prediction == original
    assert evidence_payload == evidence_original


def test_leakage_status_reflects_the_feature_snapshot() -> None:
    snapshot = feature_snapshot()
    snapshot["leakage_check"] = {"passed": False, "rejected_future_fields": ["captured_at"]}

    graph = build_explanation_graph(prediction_payload(), feature_snapshot=snapshot, evidence=evidence())

    assert graph["leakage_status"]["passed"] is False
    assert "captured_at" in graph["leakage_status"]["rejected_future_fields"]
