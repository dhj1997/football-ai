"""Coverage reporting for persisted Feature Engine v2 values."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Mapping

from .feature_registry import FeatureRegistry


def build_feature_coverage(repository: Any, *, generated_at: str | None = None) -> dict[str, Any]:
    """Calculate coverage from latest persisted snapshot per fixture."""

    snapshots = repository.feature_snapshots() if callable(getattr(repository, "feature_snapshots", None)) else []
    audits = repository.leakage_audits() if callable(getattr(repository, "leakage_audits", None)) else []
    audit_status = {
        str(audit.get("feature_snapshot_id") or ""): str(audit.get("status") or "").upper()
        for audit in audits
        if audit.get("feature_snapshot_id")
    }
    latest: dict[str, Mapping[str, Any]] = {}
    for snapshot in snapshots:
        snapshot_id = str(snapshot.get("snapshot_id") or "")
        if (
            snapshot.get("feature_version") != "round3-feature-engine-v2"
            or audit_status.get(snapshot_id) != "PASS"
        ):
            continue
        fixture_id = str(snapshot.get("canonical_fixture_id") or snapshot.get("fixture_id") or "")
        if not fixture_id:
            continue
        previous = latest.get(fixture_id)
        if previous is None or str(snapshot.get("prediction_cutoff_at") or "") > str(previous.get("prediction_cutoff_at") or ""):
            latest[fixture_id] = snapshot
    definitions = FeatureRegistry(repository).list(status=None)
    registry_by_name = {str(row.get("feature_name")): row for row in definitions}
    groups: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"numerator": 0, "denominator": 0}))
    for snapshot in latest.values():
        competition = _competition(snapshot)
        for row in snapshot.get("features") or []:
            name = str(row.get("feature_name") or "")
            definition = registry_by_name.get(name)
            group = str(row.get("feature_group") or (definition or {}).get("feature_group") or "unknown")
            bucket = groups[competition][group]
            bucket["denominator"] += 1
            if row.get("status") in {"available", "insufficient_sample"} and row.get("feature_value") is not None:
                bucket["numerator"] += 1
    competitions: dict[str, Any] = {}
    for competition, group_rows in sorted(groups.items()):
        competitions[competition] = {
            group: {
                **values,
                "coverage": round(values["numerator"] / values["denominator"], 4) if values["denominator"] else None,
                "status": "ok" if values["denominator"] else "no_snapshots",
            }
            for group, values in sorted(group_rows.items())
        }
    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "feature_version": "round3-feature-engine-v2",
        "snapshot_count": len(latest),
        "fixture_count": len(latest),
        "calculation_versions": sorted(
            {
                str(row.get("calculation_version"))
                for snapshot in latest.values()
                for row in snapshot.get("features") or []
                if row.get("calculation_version")
            }
        ),
        "competitions": competitions,
        "status": "ok" if latest else "no_snapshots",
    }


def render_feature_coverage_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# AI Round 3 Feature Coverage",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        f"Feature version: `{report.get('feature_version')}`",
        f"Latest fixture snapshots: `{report.get('snapshot_count', 0)}`",
        f"Fixtures represented: `{report.get('fixture_count', 0)}`",
        f"Calculation versions: `{', '.join(report.get('calculation_versions') or []) or 'none'}`",
        "",
    ]
    if not report.get("competitions"):
        lines.extend(["Status: `no_snapshots`", "", "No persisted Feature Engine v2 snapshots were available.", ""])
        return "\n".join(lines)
    lines.extend(["| Competition | Feature group | Available | Expected | Coverage |", "|---|---|---:|---:|---:|"])
    for competition, groups in sorted((report.get("competitions") or {}).items()):
        for group, values in sorted(groups.items()):
            coverage = values.get("coverage")
            coverage_text = "no_snapshots" if coverage is None else f"{coverage:.2%}"
            lines.append(f"| {competition} | {group} | {values.get('numerator', 0)} | {values.get('denominator', 0)} | {coverage_text} |")
    lines.append("")
    return "\n".join(lines)


def _competition(snapshot: Mapping[str, Any]) -> str:
    value = snapshot.get("competition") or snapshot.get("league") or snapshot.get("canonical_league")
    if value not in (None, ""):
        return str(value)
    return "unknown"
