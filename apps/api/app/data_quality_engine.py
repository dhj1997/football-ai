"""P9 canonical normalization and data quality engine.

Turns provider fixture rows from any of the six competitions into the P9
canonical fixture contract, evaluates the P9 quality rules with explicit
``pass | warn | fail | not_applicable`` outcomes, and aggregates provider
reliability from data sync runs. Freshness and completeness are always
reported separately so one number never masks a specific failure.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping

from .competition_registry import (
    COMPETITION_REGISTRY,
    CompetitionDefinition,
    normalize_competition_key,
)
from .historical_validation import (
    canonical_fixture_id,
    canonical_team_id,
    parse_timestamp,
)
from .league_data_pipeline import normalize_fixture_status

QUALITY_VERSION = "p9-quality-v1"
QUALITY_STATUSES: tuple[str, ...] = ("pass", "warn", "fail", "not_applicable")
DEFAULT_FRESHNESS_SLA_HOURS = 168.0

_STAGE_TYPES: tuple[str, ...] = ("league_round", "group", "knockout_round")

_GROUP_STAGE_MARKERS = ("group", "小组")
_KNOCKOUT_STAGE_MARKERS = ("knockout", "淘汰", "决赛", "半决", "四分之一", "16强", "8强", "final", "semi", "quarter", "round of")


def canonical_stage(
    competition: Any,
    *,
    round: Any = None,
    stage_name: Any = None,
    leg: Any = None,
) -> dict[str, Any]:
    """Normalize provider round/stage text into stage semantics.

    Leagues carry a plain round; cups and continental competitions must be
    expressed as group or knockout-round stages so knockout fixtures never
    masquerade as league rounds.
    """

    definition = competition if isinstance(competition, CompetitionDefinition) else COMPETITION_REGISTRY.get(competition)
    competition_key = definition.key if definition else str(competition or "unknown")
    competition_type = definition.competition_type if definition else "unknown"
    round_text = str(round or stage_name or "").strip()
    round_number = _round_number(round_text)
    lowered = round_text.casefold()
    if any(marker in lowered for marker in _GROUP_STAGE_MARKERS):
        stage_type = "group"
    elif any(marker in lowered for marker in _KNOCKOUT_STAGE_MARKERS):
        stage_type = "knockout_round"
    elif competition_type == "league":
        stage_type = "league_round"
    elif competition_type == "knockout":
        stage_type = "knockout_round"
    else:
        stage_type = "knockout_round" if round_number is not None and round_number > 3 else "group"
    leg_value = _round_number(leg)
    stage_id = "|".join(
        (
            "stage",
            competition_key,
            stage_type,
            str(round_number) if round_number is not None else "unknown",
            str(leg_value) if leg_value is not None else "",
        )
    )
    return {
        "stage_id": stage_id,
        "stage_type": stage_type,
        "round": round_number,
        "round_label": round_text or None,
        "leg": leg_value,
    }


def _round_number(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def canonical_fixture_record(
    fixture: Mapping[str, Any],
    competition: Any,
    *,
    round: Any = None,
    stage_name: Any = None,
    leg: Any = None,
) -> dict[str, Any] | None:
    """Build the P9 canonical fixture contract for one provider row.

    Returns None when the row lacks the identity fields a fixture must
    have (kickoff plus both team names) instead of inventing values.
    """

    definition = competition if isinstance(competition, CompetitionDefinition) else COMPETITION_REGISTRY.get(competition)
    competition_key = definition.key if definition else normalize_competition_key(str(competition or ""))
    if not competition_key:
        return None
    kickoff = parse_timestamp(fixture.get("kickoff_at") or fixture.get("kickoff"))
    home = fixture.get("home_team") if isinstance(fixture.get("home_team"), Mapping) else {"name": fixture.get("home_team") or fixture.get("home")}
    away = fixture.get("away_team") if isinstance(fixture.get("away_team"), Mapping) else {"name": fixture.get("away_team") or fixture.get("away")}
    home_name = str(home.get("name") or "")
    away_name = str(away.get("name") or "")
    if kickoff is None or not home_name or not away_name:
        return None
    league_ref = competition_key
    stage = canonical_stage(definition or competition_key, round=round, stage_name=stage_name, leg=leg)
    score = fixture.get("score") if isinstance(fixture.get("score"), Mapping) else None
    external_ids = dict(fixture.get("external_ids") or {})
    if fixture.get("provider_id") is not None:
        external_ids.setdefault("provider_id", str(fixture.get("provider_id")))
    season = fixture.get("season") or _season_from_definition(definition, kickoff)
    return {
        "fixture_id": str(fixture.get("id") or ""),
        "canonical_fixture_id": canonical_fixture_id(
            league=league_ref,
            home_team=home,
            away_team=away,
            kickoff=kickoff.isoformat(),
        ),
        "competition_key": competition_key,
        "competition_type": definition.competition_type if definition else "unknown",
        "season_id": str(season),
        "stage": stage,
        "stage_id": stage["stage_id"],
        "kickoff_at": kickoff.isoformat(),
        "home_team": {
            "team_id": canonical_team_id(home, competition_key),
            "name": home_name,
            "provider_id": str(home.get("provider_id") or "") or None,
        },
        "away_team": {
            "team_id": canonical_team_id(away, competition_key),
            "name": away_name,
            "provider_id": str(away.get("provider_id") or "") or None,
        },
        "status": normalize_fixture_status(fixture.get("status") or fixture.get("provider_status"), score=score),
        "score": {"home": score.get("home"), "away": score.get("away")} if score else None,
        "venue": fixture.get("venue") or None,
        "source_refs": {
            "source": fixture.get("source") or fixture.get("result_source") or "unknown",
            "external_ids": external_ids,
        },
        "captured_at": _captured_at(fixture),
    }


def _season_from_definition(definition: CompetitionDefinition | None, kickoff: datetime) -> str:
    if definition and definition.season_policy == "calendar_year":
        return str(kickoff.year)
    return str(kickoff.year if kickoff.month >= 7 else kickoff.year - 1)


def _captured_at(fixture: Mapping[str, Any]) -> str | None:
    for field in ("captured_at", "result_captured_at", "evidence_synced_at", "synced_at"):
        parsed = parse_timestamp(fixture.get(field))
        if parsed:
            return parsed.isoformat()
    return None


def _rule(rule: str, status: str, *, detail: Any = None) -> dict[str, Any]:
    return {"rule": rule, "status": status, "detail": detail}


def evaluate_fixture_quality(
    record: Mapping[str, Any],
    *,
    group: Iterable[Mapping[str, Any]] = (),
    odds: Iterable[Mapping[str, Any]] = (),
    freshness_sla_hours: float = DEFAULT_FRESHNESS_SLA_HOURS,
    now: Any = None,
) -> dict[str, Any]:
    """Evaluate the P9 quality rules for one canonical fixture record.

    ``group`` holds the other provider rows that share the fixture's
    canonical identity; ``odds`` holds odds snapshots for the fixture.
    """

    now_at = parse_timestamp(now) or datetime.now(UTC)
    rules: list[dict[str, Any]] = []
    canonical_id = record.get("canonical_fixture_id")
    rules.append(_rule("identity_uniqueness", "pass" if canonical_id else "fail", detail=canonical_id))

    kickoff = parse_timestamp(record.get("kickoff_at"))
    kickoff_valid = kickoff is not None and datetime(1990, 1, 1, tzinfo=UTC) <= kickoff <= now_at + timedelta(days=730)
    rules.append(_rule("kickoff_validity", "pass" if kickoff_valid else "fail", detail=record.get("kickoff_at")))

    home_id = (record.get("home_team") or {}).get("team_id")
    away_id = (record.get("away_team") or {}).get("team_id")
    teams_complete = bool(home_id and away_id and home_id != away_id)
    rules.append(_rule("team_identity_completeness", "pass" if teams_complete else "fail"))

    status = str(record.get("status") or "")
    score = record.get("score") if isinstance(record.get("score"), Mapping) else None
    score_complete = bool(score and score.get("home") is not None and score.get("away") is not None)
    if status == "finished":
        rules.append(_rule("score_completeness", "pass" if score_complete else "fail"))
    else:
        rules.append(_rule("score_completeness", "not_applicable", detail=status))
    if status == "scheduled" and score_complete:
        rules.append(_rule("status_score_consistency", "fail", detail="scheduled fixture carries a score"))
    elif status in {"finished", "live"} and not score_complete:
        rules.append(_rule("status_score_consistency", "warn", detail=f"{status} without score"))
    else:
        rules.append(_rule("status_score_consistency", "pass"))

    stage = record.get("stage") if isinstance(record.get("stage"), Mapping) else None
    competition_type = str(record.get("competition_type") or "")
    if not stage or stage.get("stage_type") not in _STAGE_TYPES:
        rules.append(_rule("stage_validity", "fail", detail="missing stage semantics"))
    elif competition_type == "league" and stage.get("stage_type") != "league_round":
        rules.append(_rule("stage_validity", "fail", detail=f"league fixture staged as {stage.get('stage_type')}"))
    elif competition_type in {"knockout", "continental"} and stage.get("stage_type") == "league_round":
        rules.append(_rule("stage_validity", "fail", detail="knockout fixture must not use league_round stage"))
    elif competition_type in {"knockout", "continental"} and stage.get("round") is None and not stage.get("round_label"):
        rules.append(_rule("stage_validity", "warn", detail="knockout stage without round info"))
    else:
        rules.append(_rule("stage_validity", "pass"))

    siblings = [row for row in group if str(row.get("fixture_id") or "") != str(record.get("fixture_id") or "")]
    same_source = [row for row in siblings if (row.get("source_refs") or {}).get("source") == (record.get("source_refs") or {}).get("source")]
    rules.append(_rule("duplicate_detection", "fail" if same_source else "pass", detail=[row.get("fixture_id") for row in same_source]))

    conflicts = _cross_source_conflicts(record, siblings)
    rules.append(_rule("cross_provider_conflict", "fail" if conflicts else "pass", detail=conflicts or None))

    captured = parse_timestamp(record.get("captured_at"))
    if captured is None:
        freshness = {"captured_at": None, "age_hours": None, "sla_hours": freshness_sla_hours, "status": "unknown"}
        rules.append(_rule("freshness_sla", "fail", detail="missing captured_at provenance"))
    else:
        age_hours = (now_at - captured).total_seconds() / 3600
        freshness = {
            "captured_at": captured.isoformat(),
            "age_hours": round(max(age_hours, 0.0), 2),
            "sla_hours": freshness_sla_hours,
            "status": "ok" if age_hours <= freshness_sla_hours else "stale",
        }
        rules.append(_rule("freshness_sla", "pass" if age_hours <= freshness_sla_hours else "warn", detail=freshness["status"]))

    source = (record.get("source_refs") or {}).get("source")
    sources = {str(source)} | {str((row.get("source_refs") or {}).get("source")) for row in siblings}
    rules.append(_rule("source_coverage", "pass" if sources - {"unknown"} else "fail", detail=sorted(sources)))

    odds_rows = [row for row in odds if isinstance(row, Mapping)]
    if not odds_rows:
        rules.append(_rule("odds_timestamp_ordering", "not_applicable"))
    else:
        kickoff_at = kickoff
        bad = [
            str(row.get("snapshot_id") or row.get("id") or "")
            for row in odds_rows
            if kickoff_at and (captured := parse_timestamp(row.get("captured_at"))) and captured >= kickoff_at
        ]
        rules.append(_rule("odds_timestamp_ordering", "fail" if bad else "pass", detail=bad or None))

    statuses = [rule["status"] for rule in rules]
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    completeness = {
        "identity": bool(canonical_id),
        "kickoff": kickoff is not None,
        "teams": teams_complete,
        "score": score_complete,
        "stage": bool(stage),
        "captured_at": captured is not None,
    }
    return {
        "quality_version": QUALITY_VERSION,
        "fixture_id": record.get("fixture_id"),
        "canonical_fixture_id": canonical_id,
        "competition_key": record.get("competition_key"),
        "status": overall,
        "rules": rules,
        "freshness": freshness,
        "completeness": completeness,
    }


def _cross_source_conflicts(
    record: Mapping[str, Any], siblings: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Report kickoff/score disagreement between sources instead of resolving it."""

    conflicts: list[dict[str, Any]] = []
    source = (record.get("source_refs") or {}).get("source")
    for row in siblings:
        other = (row.get("source_refs") or {}).get("source")
        if not other or other == source:
            continue
        other_kickoff = row.get("kickoff_at") or row.get("kickoff")
        other_score = row.get("score") if isinstance(row.get("score"), Mapping) else None
        kickoff_a = parse_timestamp(record.get("kickoff_at"))
        kickoff_b = parse_timestamp(other_kickoff)
        if kickoff_a and kickoff_b and kickoff_a != kickoff_b:
            conflicts.append(
                {
                    "conflict_type": "kickoff",
                    "source_a": source,
                    "source_b": other,
                    "value_a": record.get("kickoff_at"),
                    "value_b": other_kickoff,
                    "resolution_method": "configured_source_priority_then_manual_review",
                }
            )
        score_a = record.get("score") if isinstance(record.get("score"), Mapping) else None
        if (
            score_a
            and other_score
            and score_a.get("home") is not None
            and other_score.get("home") is not None
            and (score_a.get("home"), score_a.get("away")) != (other_score.get("home"), other_score.get("away"))
        ):
            conflicts.append(
                {
                    "conflict_type": "score",
                    "source_a": source,
                    "source_b": other,
                    "value_a": score_a,
                    "value_b": other_score,
                    "resolution_method": "configured_source_priority_then_manual_review",
                }
            )
    return conflicts


def record_fixture_conflicts(
    repository: Any,
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    detected_at: Any = None,
) -> list[dict[str, Any]]:
    """Persist kickoff/score disagreement between two source rows.

    The merge keeps the configured resolution priority; this function makes
    the disagreement auditable instead of letting the last writer win
    silently (P9 invariant 5).
    """

    saver = getattr(repository, "save_fixture_conflict", None)
    if not callable(saver):
        return []
    league_key = str(existing.get("league_key") or incoming.get("league_key") or "")
    definition = COMPETITION_REGISTRY.get(league_key)
    kickoff_existing = parse_timestamp(existing.get("kickoff"))
    kickoff_incoming = parse_timestamp(incoming.get("kickoff"))
    canonical_id = canonical_fixture_id(
        league=league_key,
        home_team=existing.get("home_team") or existing.get("home"),
        away_team=existing.get("away_team") or existing.get("away"),
        kickoff=(kickoff_existing or kickoff_incoming).isoformat() if (kickoff_existing or kickoff_incoming) else "",
    )
    source_existing = str(existing.get("result_source") or existing.get("source") or "existing")
    source_incoming = str(incoming.get("source") or "unknown")
    if source_existing == source_incoming:
        return []
    found: list[dict[str, Any]] = []
    if (
        kickoff_existing
        and kickoff_incoming
        and kickoff_existing != kickoff_incoming
        and abs((kickoff_existing - kickoff_incoming).total_seconds()) > 900
    ):
        found.append(
            {
                "conflict_type": "kickoff",
                "value_a": kickoff_existing.isoformat(),
                "value_b": kickoff_incoming.isoformat(),
            }
        )
    score_existing = existing.get("score") if isinstance(existing.get("score"), Mapping) else None
    score_incoming = incoming.get("score") if isinstance(incoming.get("score"), Mapping) else None
    if (
        score_existing
        and score_incoming
        and score_existing.get("home") is not None
        and score_incoming.get("home") is not None
        and (score_existing.get("home"), score_existing.get("away"))
        != (score_incoming.get("home"), score_incoming.get("away"))
    ):
        found.append(
            {
                "conflict_type": "score",
                "value_a": score_existing,
                "value_b": score_incoming,
            }
        )
    detected = parse_timestamp(detected_at) or datetime.now(UTC)
    saved: list[dict[str, Any]] = []
    for conflict in found:
        record = {
            "canonical_fixture_id": canonical_id,
            "competition_key": definition.key if definition else league_key or "unknown",
            "conflict_type": conflict["conflict_type"],
            "source_a": source_existing,
            "source_b": source_incoming,
            "value_a": conflict["value_a"],
            "value_b": conflict["value_b"],
            "resolution": "configured_source_priority_then_manual_review",
            "resolved": False,
            "detected_at": detected.replace(microsecond=0).isoformat(),
        }
        conflict_key = "|".join(
            (
                canonical_id,
                record["conflict_type"],
                source_existing,
                source_incoming,
                json.dumps(conflict["value_a"], sort_keys=True, default=str),
                json.dumps(conflict["value_b"], sort_keys=True, default=str),
            )
        )
        record["conflict_id"] = f"conflict:{hashlib.sha256(conflict_key.encode()).hexdigest()[:32]}"
        saver(record)
        saved.append(record)
    return saved


# data_sync_runs entity types mapped onto registry capabilities so
# reliability is reported in capability terms.
_ENTITY_CAPABILITY: dict[str, str] = {
    "league": "standings",
    "fixture": "fixture",
    "result": "historical",
    "team": "team",
    "odds": "odds",
}


def provider_reliability(
    sync_runs: Iterable[Mapping[str, Any]],
    *,
    fixture_conflicts: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Aggregate sync runs per provider x competition x capability.

    Reliability is operational telemetry for data-source selection only;
    it never feeds model probabilities.
    """

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for run in sync_runs:
        provider = str(run.get("provider") or "unknown")
        competition = str(run.get("league") or "unknown")
        capability = _ENTITY_CAPABILITY.get(str(run.get("entity_type") or ""), str(run.get("entity_type") or "unknown"))
        key = (provider, competition, capability)
        item = groups.setdefault(
            key,
            {
                "provider": provider,
                "competition": competition,
                "capability": capability,
                "runs": 0,
                "completed": 0,
                "partial": 0,
                "failed": 0,
                "records_seen": 0,
                "records_inserted": 0,
                "records_updated": 0,
                "records_rejected": 0,
                "error_categories": {},
                "latency_seconds_total": 0.0,
                "latency_samples": 0,
                "last_finished_at": None,
            },
        )
        item["runs"] += 1
        status = str(run.get("status") or "")
        item["completed" if status == "completed" else "partial" if status == "partial" else "failed"] += 1
        for field in ("records_seen", "records_inserted", "records_updated", "records_rejected"):
            item[field] += int(run.get(field) or 0)
        category = run.get("error_category")
        if category:
            item["error_categories"][str(category)] = item["error_categories"].get(str(category), 0) + 1
        started = parse_timestamp(run.get("started_at"))
        finished = parse_timestamp(run.get("finished_at"))
        if started and finished:
            item["latency_seconds_total"] += max((finished - started).total_seconds(), 0.0)
            item["latency_samples"] += 1
        if finished and (item["last_finished_at"] is None or finished > parse_timestamp(item["last_finished_at"])):
            item["last_finished_at"] = finished.isoformat()

    conflicts: list[dict[str, Any]] = [dict(row) for row in fixture_conflicts]
    report: list[dict[str, Any]] = []
    for key in sorted(groups):
        item = groups[key]
        runs = item.pop("runs")
        failed = item.pop("failed")
        partial = item.pop("partial")
        completed = item.pop("completed")
        latency_total = item.pop("latency_seconds_total")
        latency_samples = item.pop("latency_samples")
        schema_errors = sum(count for category, count in item.pop("error_categories").items() if category == "data_quality_error")
        item.update(
            {
                "runs": runs,
                "completed": completed,
                "partial": partial,
                "failed": failed,
                "success_rate": round(completed / runs, 4) if runs else None,
                "avg_latency_seconds": round(latency_total / latency_samples, 2) if latency_samples else None,
                "schema_error_rate": round(schema_errors / runs, 4) if runs else None,
                "conflict_count": sum(
                    1
                    for row in conflicts
                    if str(row.get("source_a") or row.get("source_b") or "") == item["provider"]
                ),
                "freshness": item.pop("last_finished_at"),
            }
        )
        report.append(item)
    return report
