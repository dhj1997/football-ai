"""P13 Explainable AI: grounded explanation graphs over prediction output.

Every reason in the graph references real feature/evidence nodes with
direction, strength, timestamp and provenance. The narrative is rendered
from the graph only — a claim without a graph reference cannot exist.
Explanations are read-only: they consume a prediction snapshot and can
never alter it, and explanation confidence is reported separately from
prediction confidence.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping

from .prediction_intelligence import FEATURE_VERSION, normalize_probabilities, parse_timestamp

EXPLANATION_VERSION = "p13-explain-v1"
EVIDENCE_KINDS: tuple[str, ...] = (
    "recent_form",
    "head_to_head",
    "lineup",
    "injuries",
    "odds",
    "schedule",
    "standings",
)
REASON_KINDS: tuple[str, ...] = (
    "core_factor",
    "evidence",
    "model_disagreement",
    "completeness",
    "counterfactual",
)


def model_disagreement(model_outputs: Mapping[str, Any]) -> dict[str, Any] | None:
    """Quantify divergence between actual model outputs (needs two or more)."""

    valid = {
        str(key): probabilities
        for key, value in model_outputs.items()
        if (probabilities := normalize_probabilities(value)) is not None
    }
    if len(valid) < 2:
        return None
    keys = sorted(valid)
    pairwise = []
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            l1 = sum(abs(valid[left][outcome] - valid[right][outcome]) for outcome in ("home", "draw", "away"))
            pairwise.append({"model_a": left, "model_b": right, "mean_abs_difference": round(l1 / 3, 6)})
    per_outcome = {
        outcome: round(
            max(valid[key][outcome] for key in keys) - min(valid[key][outcome] for key in keys),
            6,
        )
        for outcome in ("home", "draw", "away")
    }
    worst = max(pairwise, key=lambda item: item["mean_abs_difference"])
    score = round(sum(item["mean_abs_difference"] for item in pairwise) / len(pairwise), 6)
    return {
        "model_count": len(valid),
        "per_outcome_spread": per_outcome,
        "pairwise": pairwise,
        "most_divergent_pair": {"model_a": worst["model_a"], "model_b": worst["model_b"]},
        "disagreement_score": score,
    }


def _evidence_nodes(evidence: Mapping[str, Any] | None, *, as_of: Any = None) -> list[dict[str, Any]]:
    evidence = evidence or {}
    as_of_at = parse_timestamp(as_of)
    nodes: list[dict[str, Any]] = []

    def node(kind: str, present: bool, *, ref: str | None = None, detail: Mapping[str, Any] | None = None) -> None:
        raw = evidence.get(kind) if kind in evidence else None
        captured = None
        if isinstance(raw, Mapping):
            for field in ("captured_at", "updated_at", "synced_at"):
                parsed = parse_timestamp(raw.get(field))
                if parsed:
                    captured = parsed.isoformat()
                    break
        future = bool(as_of_at and captured and parse_timestamp(captured) > as_of_at)
        entry = {
            "kind": kind,
            "status": "missing" if not present else "future_rejected" if future else "present",
            "captured_at": captured,
            "source": raw.get("source") if isinstance(raw, Mapping) else None,
            "ref": ref or f"evidence:{kind}",
            "detail": dict(detail) if detail else None,
        }
        nodes.append(entry)

    recent = evidence.get("recent_form") or {}
    recent_home = recent.get("home") or []
    recent_away = recent.get("away") or []
    node("recent_form", bool(recent_home or recent_away), detail={"home_matches": len(recent_home) if isinstance(recent_home, list) else 0, "away_matches": len(recent_away) if isinstance(recent_away, list) else 0})
    node("head_to_head", bool(evidence.get("head_to_head") or evidence.get("h2h")))
    lineup = evidence.get("lineup") or {}
    node("lineup", bool(lineup), detail={"confirmed": bool(lineup.get("confirmed"))} if isinstance(lineup, Mapping) else None)
    node("injuries", bool(evidence.get("injuries") or evidence.get("availability")))
    node("odds", bool(evidence.get("odds")))
    node("schedule", bool(evidence.get("schedule_context") or evidence.get("schedule")))
    node("standings", bool(evidence.get("standings")))
    return nodes


def _core_factor_reasons(feature_snapshot: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Deterministic core factors derived from the real feature snapshot."""

    if not isinstance(feature_snapshot, Mapping):
        return []
    reasons: list[dict[str, Any]] = []
    captured = feature_snapshot.get("source_captured_at") or feature_snapshot.get("captured_at")
    recent = feature_snapshot.get("recent_form") or {}
    home_form = _number((recent.get("home") or {}).get("points_per_game"))
    away_form = _number((recent.get("away") or {}).get("points_per_game"))
    if home_form is not None and away_form is not None:
        diff = home_form - away_form
        reasons.append(
            _reason(
                "core:recent_form",
                "core_factor",
                f"近15场场均积分主队 {home_form:.2f} 对客队 {away_form:.2f}",
                direction="favor_home" if diff > 0.1 else "favor_away" if diff < -0.1 else "neutral",
                strength=min(1.0, abs(diff) / 3.0),
                refs=["feature:recent_form.home.points_per_game", "feature:recent_form.away.points_per_game", "evidence:recent_form"],
                timestamp=captured,
                provenance={"feature_version": feature_snapshot.get("feature_version") or FEATURE_VERSION},
            )
        )
    strength = feature_snapshot.get("team_strength") or {}
    home_strength = _number(strength.get("home"))
    away_strength = _number(strength.get("away"))
    if home_strength is not None and away_strength is not None and home_strength + away_strength:
        diff = (home_strength - away_strength) / max(home_strength + away_strength, 1e-9)
        reasons.append(
            _reason(
                "core:team_strength",
                "core_factor",
                f"积分榜实力差（归一）主队 {home_strength:.2f} 对客队 {away_strength:.2f}",
                direction="favor_home" if diff > 0.05 else "favor_away" if diff < -0.05 else "neutral",
                strength=min(1.0, abs(diff)),
                refs=["feature:team_strength.home", "feature:team_strength.away", "evidence:standings"],
                timestamp=captured,
                provenance={"feature_version": feature_snapshot.get("feature_version") or FEATURE_VERSION},
            )
        )
    squad = feature_snapshot.get("squad_status") or {}
    home_available = _number((squad.get("home") or {}).get("available"))
    away_available = _number((squad.get("away") or {}).get("available"))
    if home_available is not None and away_available is not None:
        reasons.append(
            _reason(
                "core:squad_status",
                "core_factor",
                f"可用球员数主队 {home_available:.0f} 对客队 {away_available:.0f}（阵容/伤停证据）",
                direction="favor_home" if home_available > away_available else "favor_away" if away_available > home_available else "neutral",
                strength=min(1.0, abs(home_available - away_available) / 11.0),
                refs=["feature:squad_status.home.available", "feature:squad_status.away.available", "evidence:lineup", "evidence:injuries"],
                timestamp=captured,
                provenance={"feature_version": feature_snapshot.get("feature_version") or FEATURE_VERSION},
            )
        )
    return reasons


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reason(
    reason_id: str,
    kind: str,
    statement: str,
    *,
    direction: str,
    strength: float,
    refs: Iterable[str],
    timestamp: Any = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": reason_id,
        "kind": kind,
        "statement": statement,
        "direction": direction,
        "strength": round(min(1.0, max(0.0, float(strength))), 6),
        "refs": list(refs),
        "timestamp": timestamp,
        "provenance": dict(provenance or {}),
    }


def build_explanation_graph(
    prediction: Mapping[str, Any],
    *,
    feature_snapshot: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    model_outputs: Mapping[str, Any] | None = None,
    data_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the explanation graph from a prediction snapshot (read-only)."""

    prediction = copy.deepcopy(dict(prediction))
    created_at = prediction.get("created_at") or prediction.get("prediction_timestamp")
    as_of = parse_timestamp(created_at)
    probabilities = normalize_probabilities(prediction.get("probabilities") or prediction.get("model_probabilities"))
    evidence_nodes = _evidence_nodes(evidence, as_of=as_of)
    present_kinds = {node["kind"] for node in evidence_nodes if node["status"] == "present"}
    missing_kinds = [kind for kind in EVIDENCE_KINDS if kind not in present_kinds]

    outputs = {
        str(key): value
        for key, value in (model_outputs or {}).items()
        if isinstance(value, Mapping)
    }
    disagreement = model_disagreement(outputs)

    reasons = _core_factor_reasons(feature_snapshot)
    if probabilities:
        favorite = max(probabilities, key=lambda key: probabilities[key])
        reasons.append(
            _reason(
                "core:model_output",
                "evidence",
                f"模型当前最高概率方向为 {favorite}（{probabilities[favorite]:.4f}）",
                direction="favor_home" if favorite == "home" else "favor_away" if favorite == "away" else "neutral",
                strength=probabilities[favorite],
                refs=["model_output:probabilities"],
                timestamp=created_at,
                provenance={"model_version": prediction.get("model_version")},
            )
        )
    if disagreement:
        reasons.append(
            _reason(
                "disagreement:models",
                "model_disagreement",
                f"{disagreement['model_count']} 个模型输出存在分歧（平均绝对差 {disagreement['disagreement_score']:.4f}，最大差异为 {disagreement['most_divergent_pair']['model_a']} 与 {disagreement['most_divergent_pair']['model_b']}）",
                direction="neutral",
                strength=min(1.0, disagreement["disagreement_score"] * 2),
                refs=["model_output:disagreement"],
                timestamp=created_at,
                provenance={"model_outputs": sorted(outputs)},
            )
        )
    if missing_kinds:
        reasons.append(
            _reason(
                "completeness:missing_evidence",
                "completeness",
                f"缺失证据：{('、'.join(missing_kinds))}",
                direction="neutral",
                strength=1.0,
                refs=[f"evidence:{kind}" for kind in missing_kinds],
                timestamp=created_at,
                provenance={},
            )
        )
    counterfactual = {
        "available": False,
        "reason": "当前模型不支持反事实分析；仅在明确标注假设时展示",
        "refs": [],
    }

    completeness = round(len(present_kinds) / len(EVIDENCE_KINDS), 6)
    consistency = round(max(0.0, 1.0 - (disagreement["disagreement_score"] if disagreement else 0.0)), 6)
    quality = _number((data_quality or {}).get("data_quality_score"))
    graph = {
        "explanation_version": EXPLANATION_VERSION,
        "prediction_ref": {
            "prediction_id": prediction.get("id") or prediction.get("prediction_id"),
            "fixture_id": prediction.get("fixture_id"),
            "prediction_timestamp": created_at,
            "model_key": prediction.get("model_key"),
            "model_version": prediction.get("model_version"),
            "feature_version": (feature_snapshot or {}).get("feature_version") or FEATURE_VERSION,
            "prompt_version": (prediction.get("ai") or {}).get("prompt_version") or prediction.get("prompt_version"),
        },
        "nodes": {
            "model_output": {
                "probabilities": probabilities,
                "prediction_confidence": prediction.get("forecast_confidence"),
                "models": {key: normalize_probabilities(value) for key, value in outputs.items()},
                "disagreement": disagreement,
            },
            "feature_snapshot": {
                "ref": "feature_snapshot",
                "feature_version": (feature_snapshot or {}).get("feature_version") or FEATURE_VERSION,
                "captured_at": (feature_snapshot or {}).get("captured_at"),
                "leakage_check": (feature_snapshot or {}).get("leakage_check") or {},
                "sections": [
                    key
                    for key in ("team_strength", "recent_form", "home_away", "squad_status", "schedule_context", "market_context")
                    if (feature_snapshot or {}).get(key)
                ],
            },
            "evidence": evidence_nodes,
        },
        "reasons": reasons,
        "counterfactual": counterfactual,
        "confidence": {
            "note": "解释置信度独立于预测置信度",
            "data_completeness": completeness,
            "model_consistency": consistency,
            "evidence_quality": quality,
        },
        "leakage_status": {
            "passed": bool(((feature_snapshot or {}).get("leakage_check") or {}).get("passed", True)),
            "rejected_future_fields": ((feature_snapshot or {}).get("leakage_check") or {}).get("rejected_future_fields") or [],
        },
    }
    graph["narrative"] = grounded_narrative(graph)
    return graph


def grounded_narrative(graph: Mapping[str, Any]) -> list[dict[str, str]]:
    """Render narrative sentences from reasons only — one per reason."""

    narrative = [
        {"reason_id": reason["id"], "text": reason["statement"]}
        for reason in graph.get("reasons") or []
    ]
    reason_ids = {reason["id"] for reason in graph.get("reasons") or []}
    # A narrative claim without a graph reason would violate grounding.
    narrative = [item for item in narrative if item["reason_id"] in reason_ids]
    return narrative


def validate_grounded(graph: Mapping[str, Any]) -> list[str]:
    """Return violations; empty list means every claim carries a reference."""

    violations: list[str] = []
    reason_ids = {reason["id"] for reason in graph.get("reasons") or []}
    refs = {reason_id for reason_id in reason_ids}
    node_refs = {
        node.get("ref") for node in graph.get("nodes", {}).get("evidence") or [] if node.get("ref")
    }
    for reason in graph.get("reasons") or []:
        if reason["kind"] not in REASON_KINDS:
            violations.append(f"unknown reason kind: {reason['kind']}")
        if not reason.get("refs"):
            violations.append(f"reason {reason['id']} has no references")
        for ref in reason.get("refs") or []:
            if ref.startswith("evidence:") and ref not in node_refs:
                violations.append(f"reason {reason['id']} references unknown evidence {ref}")
    for item in graph.get("narrative") or []:
        if item.get("reason_id") not in refs:
            violations.append(f"narrative claim without graph reason: {item.get('reason_id')}")
    return violations
