"""Timestamp-safe historical reconstruction and validation infrastructure."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Iterable, Mapping

from .player_identity import public_payload
from .prediction_intelligence import (
    CALIBRATION_VERSION,
    ENSEMBLE_VERSION,
    FEATURE_VERSION,
    apply_temperature,
    build_backtest_rows,
    build_performance_profiles,
    evaluate_probabilities,
    fit_temperature,
    parse_timestamp,
    split_time_ordered,
    weighted_ensemble,
)
from .team_names import to_chinese_team_name


HISTORICAL_SNAPSHOT_VERSION = "p4-historical-v1"
DATASET_VERSION = "p4-dataset-v1"
BACKTEST_VERSION = "p4-backtest-v1"

DEFAULT_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "fixture": ("api-football", "espn", "thesportsdb", "demo"),
    "odds": ("api-football", "espn", "thesportsdb", "demo"),
    "team": ("espn", "api-football", "thesportsdb", "demo"),
    "league": ("espn", "api-football", "thesportsdb", "demo"),
    "lineup": ("api-football", "espn", "thesportsdb", "demo"),
    "injury": ("api-football", "espn", "thesportsdb", "demo"),
}


def build_raw_data_record(
    entity_type: str,
    source: str,
    source_record_id: Any,
    payload: Mapping[str, Any],
    captured_at: Any,
    *,
    ingested_at: Any | None = None,
) -> dict[str, Any]:
    """Normalize raw provenance without discarding the provider payload."""

    captured = parse_timestamp(captured_at)
    ingested = parse_timestamp(ingested_at) or datetime.now(UTC)
    if captured is None:
        raise ValueError("captured_at must be an ISO timestamp")
    source_id = str(source_record_id or "")
    if not source_id:
        raise ValueError("source_record_id is required")
    record_key = "|".join((entity_type, source, source_id, captured.isoformat()))
    return {
        "record_id": f"raw:{hashlib.sha256(record_key.encode()).hexdigest()[:32]}",
        "entity_type": entity_type,
        "source": source,
        "source_record_id": source_id,
        "captured_at": captured.isoformat(),
        "ingested_at": ingested.isoformat(),
        "payload": dict(payload),
    }


class RawDataIngestionService:
    """Append provider responses to the raw layer before normalization."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def ingest(
        self,
        entity_type: str,
        source: str,
        records: Iterable[Mapping[str, Any]],
        *,
        ingested_at: Any | None = None,
    ) -> dict[str, Any]:
        saver = getattr(self.repository, "save_raw_data_record", None)
        normalized = []
        for record in records:
            normalized_record = build_raw_data_record(
                entity_type,
                source,
                record.get("source_record_id") or record.get("id"),
                record.get("payload") if isinstance(record.get("payload"), Mapping) else record,
                record.get("captured_at"),
                ingested_at=ingested_at,
            )
            if callable(saver):
                saver(normalized_record)
            normalized.append(normalized_record)
        return {"status": "ok", "entity_type": entity_type, "source": source, "count": len(normalized), "records": normalized}


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("name") or value.get("id") or value.get("team_id") or "")
    return str(value or "")


def _name_key(value: Any) -> str:
    localized = to_chinese_team_name(_text(value))
    return "".join(character.casefold() for character in localized if character.isalnum())


def _team_name_key(value: Any) -> str:
    raw = _text(value)
    tokens = [token for token in raw.replace("-", " ").split() if token.casefold() not in {"fc", "cf", "club", "football"}]
    return _name_key(" ".join(tokens))


def canonical_league_id(value: Any) -> str:
    """Map common provider league labels to one stable internal identity."""

    key = _name_key(value)
    aliases = {
        "epl": "epl",
        "premierleague": "epl",
        "englishpremierleague": "epl",
        "laliga": "laliga",
        "spanishlaliga": "laliga",
        "csl": "csl",
        "chinesesuperleague": "csl",
        "中超": "csl",
    }
    return aliases.get(key, f"league:{key or 'unknown'}")


def canonical_team_id(value: Any, league: Any | None = None) -> str:
    """Build a deterministic team identity while retaining source IDs separately."""

    league_id = canonical_league_id(league) if league else "league:unknown"
    digest = hashlib.sha256(f"team|{league_id}|{_team_name_key(value)}".encode()).hexdigest()[:24]
    return f"team:{digest}"


def canonical_fixture_id(
    fixture: Mapping[str, Any] | None = None,
    *,
    league: Any | None = None,
    home_team: Any | None = None,
    away_team: Any | None = None,
    kickoff: Any | None = None,
) -> str:
    """Build a stable fixture identity across provider-specific IDs."""

    fixture = fixture or {}
    league_value = league if league is not None else fixture.get("league_key") or fixture.get("league")
    home_value = home_team if home_team is not None else fixture.get("home_team")
    away_value = away_team if away_team is not None else fixture.get("away_team")
    kickoff_value = kickoff if kickoff is not None else fixture.get("kickoff")
    kickoff_at = parse_timestamp(kickoff_value)
    kickoff_key = kickoff_at.isoformat() if kickoff_at else _text(kickoff_value)
    identity = "|".join(
        (
            canonical_league_id(league_value),
            _team_name_key(home_value),
            _team_name_key(away_value),
            kickoff_key,
        )
    )
    return f"fixture:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


def _source_rank(kind: str, source: Any, priorities: Mapping[str, Iterable[str]] | None) -> int:
    configured = tuple(priorities.get(kind, ())) if priorities else DEFAULT_SOURCE_PRIORITY.get(kind, ())
    source_key = str(source or "unknown").casefold()
    try:
        return len(configured) - configured.index(source_key)
    except ValueError:
        return 0


def resolve_source_records(
    records: Iterable[Mapping[str, Any]],
    *,
    kind: str,
    priorities: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Resolve one normalized record without hiding source conflicts."""

    rows = [dict(record) for record in records]
    if not rows:
        return {"selected": None, "records": [], "conflict": False, "conflict_details": None}
    fingerprints = {
        json.dumps(row.get("payload", row), ensure_ascii=False, sort_keys=True, default=str)
        for row in rows
    }
    conflict = len(fingerprints) > 1
    selected = max(
        rows,
        key=lambda row: (
            _source_rank(kind, row.get("source"), priorities),
            parse_timestamp(row.get("captured_at")) or datetime.min.replace(tzinfo=UTC),
            str(row.get("source_record_id") or ""),
        ),
    )
    details = None
    if conflict:
        captured_times = [parse_timestamp(row.get("captured_at")) for row in rows]
        captured_times = [value for value in captured_times if value]
        details = {
            "source_a": rows[0].get("source"),
            "source_b": next((row.get("source") for row in rows[1:] if row.get("source") != rows[0].get("source")), rows[1].get("source")),
            "resolved_by": "configured_source_priority_then_capture_time",
            "resolved_at": max(captured_times).isoformat() if captured_times else None,
        }
    return {
        "selected": selected,
        "records": rows,
        "conflict": conflict,
        "conflict_details": details,
    }


def map_fixture_sources(
    records: Iterable[Mapping[str, Any]],
    *,
    priorities: Mapping[str, Iterable[str]] | None = None,
) -> list[dict[str, Any]]:
    """Map provider fixtures to canonical IDs and report conflicting identities."""

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[canonical_fixture_id(record)].append(record)
    result = []
    for canonical_id, group in sorted(groups.items()):
        resolution = resolve_source_records(group, kind="fixture", priorities=priorities)
        result.append(
            {
                "canonical_fixture_id": canonical_id,
                "source_records": [
                    {
                        "source": row.get("source"),
                        "source_record_id": row.get("source_record_id") or row.get("id"),
                    }
                    for row in group
                ],
                "selected": resolution["selected"],
                "conflict": resolution["conflict"],
                "conflict_details": resolution["conflict_details"],
            }
        )
    coarse: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in result:
        selected = item.get("selected") or {}
        coarse_key = (
            canonical_league_id(selected.get("league_key") or selected.get("league")),
            parse_timestamp(selected.get("kickoff")).isoformat() if parse_timestamp(selected.get("kickoff")) else _text(selected.get("kickoff")),
            _team_name_key(selected.get("away_team") or selected.get("away")),
        )
        coarse[coarse_key].append(item)
    for items in coarse.values():
        if len(items) < 2:
            continue
        source_rows = [row for item in items for row in item.get("source_records") or []]
        details = resolve_source_records(source_rows, kind="fixture", priorities=priorities)["conflict_details"]
        for item in items:
            item["conflict"] = True
            item["conflict_details"] = details or {
                "resolved_by": "manual_conflict_review",
                "resolved_at": None,
            }
    return result


def map_team_sources(
    records: Iterable[Mapping[str, Any]],
    *,
    league: Any | None = None,
    priorities: Mapping[str, Iterable[str]] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[canonical_team_id(record.get("name") or record, league)].append(record)
    result = []
    for canonical_id, group in sorted(groups.items()):
        resolution = resolve_source_records(group, kind="team", priorities=priorities)
        result.append(
            {
                "canonical_team_id": canonical_id,
                "source_records": [
                    {
                        "source": row.get("source"),
                        "source_record_id": row.get("source_record_id") or row.get("id"),
                    }
                    for row in group
                ],
                "selected": resolution["selected"],
                "conflict": resolution["conflict"],
                "conflict_details": resolution["conflict_details"],
            }
        )
    return result


def filter_as_of(
    records: Iterable[Mapping[str, Any]],
    as_of: Any,
    *,
    captured_field: str = "captured_at",
) -> dict[str, Any]:
    """Keep only records available at T and explain every rejection."""

    as_of_at = parse_timestamp(as_of)
    if as_of_at is None:
        raise ValueError("as_of must be an ISO timestamp")
    accepted: list[dict[str, Any]] = []
    future: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for record in records:
        captured = parse_timestamp(record.get(captured_field) or record.get("created_at"))
        if captured is None:
            invalid.append(dict(record))
        elif captured <= as_of_at:
            accepted.append(dict(record))
        else:
            future.append(dict(record))
    return {"accepted": accepted, "future": future, "invalid_timestamp": invalid, "as_of": as_of_at.isoformat()}


def _latest_record(records: Iterable[Mapping[str, Any]], as_of: Any) -> dict[str, Any] | None:
    filtered = filter_as_of(records, as_of)
    if not filtered["accepted"]:
        return None
    return max(
        filtered["accepted"],
        key=lambda row: (
            parse_timestamp(row.get("captured_at") or row.get("created_at")) or datetime.min.replace(tzinfo=UTC),
            str(row.get("id") or row.get("snapshot_id") or ""),
        ),
    )


def select_closing_odds(
    odds_snapshots: Iterable[Mapping[str, Any]],
    kickoff: Any,
    *,
    market: str | None = None,
    selection: str | None = None,
    line: Any | None = None,
) -> dict[str, Any] | None:
    """Select the last valid quote strictly before kickoff, never from current state."""

    kickoff_at = parse_timestamp(kickoff)
    if kickoff_at is None:
        return None
    candidates: list[dict[str, Any]] = []
    for snapshot in odds_snapshots:
        snapshot_captured = snapshot.get("captured_at")
        for quote in snapshot.get("quotes") or []:
            captured = parse_timestamp(quote.get("captured_at") or snapshot_captured)
            if captured is None or captured >= kickoff_at:
                continue
            if market and quote.get("market") != market:
                continue
            if selection and quote.get("selection") != selection:
                continue
            if line is not None and str(quote.get("line")) != str(line):
                continue
            candidates.append(
                {
                    **quote,
                    "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("id"),
                    "captured_at": captured.isoformat(),
                }
            )
    return max(candidates, key=lambda row: (parse_timestamp(row["captured_at"]), str(row.get("snapshot_id") or ""))) if candidates else None


def classify_odds_timeline(
    odds_snapshots: Iterable[Mapping[str, Any]],
    kickoff: Any,
) -> dict[str, Any]:
    """Expose opening/pre-match/closing quotes using capture time only."""

    kickoff_at = parse_timestamp(kickoff)
    if kickoff_at is None:
        return {"status": "unavailable", "opening": None, "pre_match": None, "closing": None}
    quotes: list[dict[str, Any]] = []
    for snapshot in odds_snapshots:
        for quote in snapshot.get("quotes") or []:
            captured = parse_timestamp(quote.get("captured_at") or snapshot.get("captured_at"))
            if captured is None or captured >= kickoff_at:
                continue
            quotes.append({
                **quote,
                "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("id"),
                "captured_at": captured.isoformat(),
            })
    if not quotes:
        return {"status": "unavailable", "opening": None, "pre_match": None, "closing": None}
    ordered = sorted(quotes, key=lambda row: (parse_timestamp(row["captured_at"]), str(row.get("snapshot_id") or "")))
    opening = ordered[0]
    pre_match = ordered[-1]
    return {"status": "ok", "opening": opening, "pre_match": pre_match, "closing": pre_match}


def _check(code: str, passed: bool, *, critical: bool, detail: Any = None) -> dict[str, Any]:
    return {"code": code, "status": "ok" if passed else "failed", "critical": critical, "detail": detail}


def assess_data_quality(
    fixture: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any] | None = None,
    odds_snapshots: Iterable[Mapping[str, Any]] | None = None,
    result: Mapping[str, Any] | None = None,
    as_of: Any | None = None,
    source_records: Iterable[Mapping[str, Any]] | None = None,
    source_conflict: bool = False,
    require_result: bool = False,
    require_kickoff: bool = True,
    require_odds: bool = False,
    freshness_policy: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return explicit checks, an audit score, and exclusion reasons."""

    checks: list[dict[str, Any]] = []
    fixture_id = fixture.get("id") or fixture.get("fixture_id")
    home = fixture.get("home_team") or fixture.get("home")
    away = fixture.get("away_team") or fixture.get("away")
    kickoff = parse_timestamp(fixture.get("kickoff"))
    checks.append(_check("missing_fixture", bool(fixture_id), critical=True))
    checks.append(_check("missing_team", bool(_text(home) and _text(away)), critical=True))
    checks.append(_check("missing_evidence", bool(evidence), critical=True))
    checks.append(_check("invalid_kickoff", kickoff is not None, critical=require_kickoff))
    rows = list(source_records or [])
    ids = [str(row.get("source_record_id") or row.get("id") or "") for row in rows]
    checks.append(_check("duplicate_fixture", len(ids) == len(set(ids)), critical=True, detail=ids))
    odds = list(odds_snapshots or [])
    checks.append(_check("odds_gap", bool(odds), critical=require_odds))
    result_value = (result or fixture.get("score") or {}).get("actual_outcome") if isinstance(result or fixture.get("score"), Mapping) else None
    if result_value is None and isinstance(fixture.get("score"), Mapping):
        score = fixture.get("score") or {}
        if score.get("home") is not None and score.get("away") is not None:
            result_value = "home" if score["home"] > score["away"] else "draw" if score["home"] == score["away"] else "away"
    checks.append(_check("result_missing", result_value is not None, critical=require_result))
    timestamp_issues: list[str] = []
    as_of_at = parse_timestamp(as_of)
    if as_of_at:
        for field in ("captured_at", "synced_at", "updated_at"):
            value = parse_timestamp((evidence or {}).get(field))
            if value and value > as_of_at:
                timestamp_issues.append(field)
        for snapshot in odds:
            value = parse_timestamp(snapshot.get("captured_at"))
            if value and value > as_of_at:
                timestamp_issues.append("odds.captured_at")
    checks.append(_check("timestamp_inconsistency", not timestamp_issues, critical=True, detail=timestamp_issues))
    checks.append(_check("source_conflict", not source_conflict, critical=True))
    freshness_issues: list[str] = []
    if freshness_policy and as_of_at:
        for kind, limit_minutes in freshness_policy.items():
            captured = parse_timestamp((evidence or {}).get(f"{kind}_captured_at"))
            if captured and (as_of_at - captured).total_seconds() > float(limit_minutes) * 60:
                freshness_issues.append(kind)
    checks.append(_check("freshness", not freshness_issues, critical=False, detail=freshness_issues))
    failed_critical = [item["code"] for item in checks if item["critical"] and item["status"] == "failed"]
    score = round(sum(item["status"] == "ok" for item in checks) / len(checks), 4) if checks else 0.0
    return {
        "quality_version": "p4-quality-v1",
        "data_quality_score": score,
        "status": "eligible" if not failed_critical else "excluded",
        "eligible": not failed_critical,
        "checks": checks,
        "exclusion_reasons": failed_critical,
    }


def sample_size_warning(sample_size: int) -> str:
    if sample_size < 30:
        return "insufficient"
    if sample_size < 100:
        return "low_confidence"
    if sample_size < 500:
        return "usable"
    return "stronger_evidence"


def _dataset_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
    stable = [
        {
            "fixture_id": row.get("fixture_id"),
            "prediction_id": row.get("prediction_id"),
            "prediction_created_at": row.get("prediction_created_at"),
            "actual_outcome": row.get("actual_outcome"),
        }
        for row in rows
    ]
    encoded = json.dumps(sorted(stable, key=lambda item: (str(item["fixture_id"]), str(item["prediction_id"]))), sort_keys=True, separators=(",", ":"))
    return f"{DATASET_VERSION}:{hashlib.sha256(encoded.encode()).hexdigest()[:16]}"


def build_historical_snapshot(
    fixture: Mapping[str, Any],
    as_of: Any,
    *,
    evidence_snapshots: Iterable[Mapping[str, Any]] = (),
    odds_snapshots: Iterable[Mapping[str, Any]] = (),
    dataset_version: str = DATASET_VERSION,
    source_versions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct exactly what was available at a historical prediction time."""

    as_of_at = parse_timestamp(as_of)
    if as_of_at is None:
        raise ValueError("as_of must be an ISO timestamp")
    evidence_rows = [row for row in evidence_snapshots if str(row.get("fixture_id")) == str(fixture.get("id") or fixture.get("fixture_id"))]
    odds_rows = [row for row in odds_snapshots if str(row.get("fixture_id")) == str(fixture.get("id") or fixture.get("fixture_id"))]
    evidence_filter = filter_as_of(evidence_rows, as_of_at)
    odds_filter = filter_as_of(odds_rows, as_of_at)
    evidence = _latest_record(evidence_filter["accepted"], as_of_at)
    odds = _latest_record(odds_filter["accepted"], as_of_at)
    evidence_payload = (evidence or {}).get("payload") or {}
    context = evidence_payload.get("context") if isinstance(evidence_payload, Mapping) else None
    context = context if isinstance(context, Mapping) else None
    evidence_sources = {
        str(
            ((row.get("payload") or {}).get("context") or {}).get("source")
            or row.get("source")
            or "unknown"
        )
        for row in evidence_filter["accepted"]
    }
    evidence_payloads = {
        json.dumps(row.get("payload") or {}, ensure_ascii=False, sort_keys=True, default=str)
        for row in evidence_filter["accepted"]
    }
    quality = assess_data_quality(
        fixture,
        evidence=context,
        odds_snapshots=odds_filter["accepted"],
        as_of=as_of_at,
        source_conflict=len(evidence_sources) > 1 and len(evidence_payloads) > 1,
        require_result=False,
        require_odds=False,
    )
    canonical_id = canonical_fixture_id(fixture)
    identity = "|".join(
        (
            canonical_id,
            as_of_at.isoformat(),
            str((evidence or {}).get("id") or ""),
            str((odds or {}).get("id") or (odds or {}).get("snapshot_id") or ""),
            HISTORICAL_SNAPSHOT_VERSION,
        )
    )
    snapshot_id = f"historical:{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
    accepted_odds = odds_filter["accepted"]
    resolved_versions = dict(source_versions or {})
    if evidence:
        resolved_versions.setdefault("evidence", evidence.get("evidence_version"))
    if odds:
        resolved_versions.setdefault("odds", odds.get("source") or odds.get("source_updated_at"))
    payload = {
        "fixture": dict(fixture),
        "evidence": dict(evidence) if evidence else None,
        "context": dict(context) if context else None,
        "standings": evidence_payload.get("standings") if isinstance(evidence_payload, Mapping) else None,
        "odds": dict(odds) if odds else None,
        "odds_timeline": accepted_odds,
        "odds_phases": classify_odds_timeline(accepted_odds, fixture.get("kickoff")),
        "data_quality": quality,
    }
    return {
        "snapshot_id": snapshot_id,
        "canonical_fixture_id": canonical_id,
        "fixture_id": str(fixture.get("id") or fixture.get("fixture_id") or ""),
        "as_of": as_of_at.isoformat(),
        "snapshot_version": HISTORICAL_SNAPSHOT_VERSION,
        "dataset_version": dataset_version,
        "source_versions": resolved_versions,
        "evidence_snapshot_id": (evidence or {}).get("id"),
        "odds_snapshot_id": (odds or {}).get("id") or (odds or {}).get("snapshot_id"),
        "data_quality_score": quality["data_quality_score"],
        # Use the reconstruction boundary so rebuilding the same snapshot is idempotent.
        "created_at": as_of_at.isoformat(),
        "payload": payload,
        "as_of_filter": {
            "future_evidence": len(evidence_filter["future"]),
            "invalid_evidence_timestamps": len(evidence_filter["invalid_timestamp"]),
            "future_odds": len(odds_filter["future"]),
            "invalid_odds_timestamps": len(odds_filter["invalid_timestamp"]),
        },
    }


def _call_runner(
    runner: Callable[..., Any],
    fixture: Mapping[str, Any],
    context: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    as_of: str,
    model_keys: Iterable[str] | None,
) -> Any | Awaitable[Any]:
    parameters = inspect.signature(runner).parameters
    kwargs: dict[str, Any] = {}
    for key, value in (
        ("historical_snapshot", snapshot),
        ("prediction_timestamp", as_of),
        ("model_keys", list(model_keys) if model_keys else None),
        ("snapshot_bundle", snapshot.get("prediction_bundle")),
        ("prepared_context", True),
    ):
        if key in parameters and value is not None:
            kwargs[key] = value
    return runner(fixture, context, **kwargs)


class HistoricalBackfillService:
    """Use a formal prediction runner against a reconstructed historical snapshot."""

    def __init__(self, repository: Any, prediction_runner: Callable[..., Any] | None = None) -> None:
        self.repository = repository
        self.prediction_runner = prediction_runner

    async def backfill(
        self,
        fixture_id: str,
        prediction_timestamp: Any,
        *,
        model_keys: Iterable[str] | None = None,
        prediction_runner: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        fixture_reader = getattr(self.repository, "fixture", None)
        fixture = fixture_reader(fixture_id) if callable(fixture_reader) else None
        if not fixture:
            return {"status": "fixture_missing", "fixture_id": fixture_id}
        evidence_reader = getattr(self.repository, "evidence_snapshots", None)
        odds_reader = getattr(self.repository, "odds_snapshots", None)
        evidence = evidence_reader(fixture_id) if callable(evidence_reader) else []
        odds = odds_reader(fixture_id) if callable(odds_reader) else []
        snapshot = build_historical_snapshot(
            fixture,
            prediction_timestamp,
            evidence_snapshots=evidence,
            odds_snapshots=odds,
        )
        context = snapshot["payload"].get("context") or {}
        snapshot["prediction_bundle"] = {
            "evidence": snapshot["payload"].get("evidence"),
            "odds": snapshot["payload"].get("odds"),
            "standings": snapshot["payload"].get("standings") or {},
            "quality": {
                "score": snapshot["data_quality_score"],
                "fields": {
                    check["code"]: check["status"] == "ok"
                    for check in snapshot["payload"]["data_quality"]["checks"]
                },
            },
        }
        saver = getattr(self.repository, "save_historical_snapshot", None)
        if callable(saver):
            saver(snapshot)
        if not snapshot["payload"]["data_quality"]["eligible"]:
            return {"status": "excluded", "snapshot": snapshot, "exclusion_reasons": snapshot["payload"]["data_quality"]["exclusion_reasons"]}
        runner = prediction_runner or self.prediction_runner
        if runner is None:
            return {"status": "runner_required", "snapshot": snapshot}
        result = _call_runner(runner, fixture, context, snapshot, snapshot["as_of"], model_keys)
        if inspect.isawaitable(result):
            result = await result
        return {
            "status": "completed",
            "fixture_id": fixture_id,
            "snapshot": snapshot,
            "predictions": result if isinstance(result, list) else [result],
        }


def rolling_windows(
    start: Any,
    end: Any,
    *,
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
) -> list[dict[str, Any]]:
    """Create deterministic walk-forward windows with configurable boundaries."""

    start_at = parse_timestamp(start)
    end_at = parse_timestamp(end)
    if start_at is None or end_at is None:
        raise ValueError("start and end must be ISO timestamps")
    if min(train_days, test_days, step_days) <= 0:
        raise ValueError("train_days, test_days, and step_days must be positive")
    cursor = start_at + timedelta(days=train_days)
    windows: list[dict[str, Any]] = []
    index = 1
    while cursor + timedelta(days=test_days) <= end_at:
        test_end = cursor + timedelta(days=test_days)
        windows.append(
            {
                "window_id": f"window-{index:04d}",
                "train_start": (cursor - timedelta(days=train_days)).isoformat(),
                "train_end": cursor.isoformat(),
                "test_start": cursor.isoformat(),
                "test_end": test_end.isoformat(),
            }
        )
        cursor += timedelta(days=step_days)
        index += 1
    return windows


def _row_time(row: Mapping[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        parsed = parse_timestamp(row.get(key))
        if parsed:
            return parsed
    return None


def _betting_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    stakes: list[float] = []
    profits: list[float] = []
    clv: list[float] = []
    for row in rows:
        stake = row.get("stake") or row.get("bet_stake") or (row.get("bet") or {}).get("stake")
        profit = row.get("net_profit") or row.get("profit") or (row.get("bet") or {}).get("net_profit")
        if stake is not None and profit is not None:
            stakes.append(float(stake))
            profits.append(float(profit))
        if row.get("clv") is not None:
            clv.append(float(row["clv"]))
    if not stakes:
        return {"status": "insufficient_sample", "bets": 0, "stake": 0.0, "pnl": 0.0, "roi": None, "drawdown": None, "clv": None}
    balance = 0.0
    peak = 0.0
    drawdown = 0.0
    for profit in profits:
        balance += profit
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    stake_total = sum(stakes)
    return {
        "status": "ok",
        "bets": len(stakes),
        "stake": round(stake_total, 4),
        "pnl": round(sum(profits), 4),
        "roi": round(sum(profits) / stake_total, 6) if stake_total else None,
        "drawdown": round(drawdown, 4),
        "clv": round(sum(clv) / len(clv), 6) if clv else None,
    }


def _paired_comparison(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    differences: list[float] = []
    for row in rows:
        baseline = row.get("existing_probabilities") or {}
        ensemble = row.get("calibrated_probabilities") or row.get("ensemble_probabilities") or {}
        actual = row.get("actual_outcome")
        if not baseline or not ensemble or actual not in {"home", "draw", "away"}:
            continue
        baseline_brier = sum((float(baseline.get(key, 0)) - (1.0 if key == actual else 0.0)) ** 2 for key in ("home", "draw", "away"))
        ensemble_brier = sum((float(ensemble.get(key, 0)) - (1.0 if key == actual else 0.0)) ** 2 for key in ("home", "draw", "away"))
        differences.append(ensemble_brier - baseline_brier)
    return {
        "samples": len(differences),
        "mean_brier_difference": round(sum(differences) / len(differences), 6) if differences else None,
        "status": "ok" if differences else "insufficient_sample",
    }


def _enrich_for_window(
    rows: list[dict[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    calibration_rows: list[dict[str, Any]],
    *,
    calibration_as_of: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        ensemble = weighted_ensemble(row["base_predictions"], profiles=profiles, league_key=row.get("league_key"))
        enriched.append({**row, "ensemble_probabilities": ensemble.get("ensemble_probabilities"), "ensemble": ensemble})
    calibration = fit_temperature(
        calibration_rows,
        probability_reader=lambda row: row.get("ensemble_probabilities"),
        trained_at=calibration_as_of,
        as_of=calibration_as_of,
    )
    for row in enriched:
        calibrated = row.get("ensemble_probabilities")
        if calibration.get("status") == "ok":
            calibrated = apply_temperature(calibrated or {}, float(calibration["temperature"]))
        row["calibrated_probabilities"] = calibrated
    return enriched, calibration


class RollingBacktestService:
    """Run reproducible walk-forward validation from persisted settlement rows."""

    def __init__(self, settlements: Iterable[Mapping[str, Any]]) -> None:
        self.settlements = [dict(row) for row in settlements]

    def run(
        self,
        *,
        start: Any,
        end: Any,
        train_days: int = 180,
        test_days: int = 30,
        step_days: int = 30,
    ) -> dict[str, Any]:
        windows = rolling_windows(start, end, train_days=train_days, test_days=test_days, step_days=step_days)
        reports: list[dict[str, Any]] = []
        leakage_issues: list[str] = []
        for window in windows:
            train_end = parse_timestamp(window["train_end"])
            test_start = parse_timestamp(window["test_start"])
            test_end = parse_timestamp(window["test_end"])
            train_rows = [
                row for row in self.settlements
                if (_row_time(row, "settled_at", "prediction_created_at") or datetime.min.replace(tzinfo=UTC)) <= train_end
            ]
            test_rows = [
                row for row in self.settlements
                if test_start < (_row_time(row, "prediction_created_at", "settled_at") or datetime.max.replace(tzinfo=UTC)) <= test_end
            ]
            if any((_row_time(row, "settled_at", "prediction_created_at") or datetime.max.replace(tzinfo=UTC)) > train_end for row in train_rows):
                leakage_issues.append(window["window_id"])
            train_backtest = build_backtest_rows(train_rows)
            test_fixture_ids = sorted({str(row.get("fixture_id") or "") for row in test_rows})
            quality_by_fixture: dict[str, dict[str, Any]] = {}
            for fixture_key in test_fixture_ids:
                fixture_rows = [row for row in test_rows if str(row.get("fixture_id") or "") == fixture_key]
                actual = next((row.get("actual_outcome") for row in fixture_rows if row.get("actual_outcome")), None)
                quality_by_fixture[fixture_key] = assess_data_quality(
                    {
                        "id": fixture_key,
                        "home_team": {"name": "historical"},
                        "away_team": {"name": "historical"},
                    },
                    evidence={"source": "fixture_settlement"},
                    result={"actual_outcome": actual},
                    require_result=True,
                    require_kickoff=False,
                )
            quality_eligible = {key for key, quality in quality_by_fixture.items() if quality["eligible"]}
            test_backtest = [
                row for row in build_backtest_rows(test_rows)
                if str(row.get("fixture_id") or "") in quality_eligible
            ]
            profiles = build_performance_profiles(train_rows, as_of=train_end)
            _, calibration_rows, _ = split_time_ordered(train_backtest)
            calibration_input, _ = _enrich_for_window(calibration_rows, profiles, [])
            evaluated, calibration = _enrich_for_window(
                test_backtest,
                profiles,
                calibration_input,
                calibration_as_of=train_end,
            )
            quality_reasons: dict[str, int] = defaultdict(int)
            for quality in quality_by_fixture.values():
                for reason in quality["exclusion_reasons"]:
                    quality_reasons[reason] += 1
            for fixture_key in set(test_fixture_ids) - {str(row.get("fixture_id") or "") for row in test_backtest}:
                if fixture_key not in quality_by_fixture or quality_by_fixture[fixture_key]["eligible"]:
                    quality_reasons["prediction_or_baseline_missing"] += 1
            evaluated_ids = {str(row.get("fixture_id") or "") for row in evaluated}
            reports.append(
                {
                    **window,
                    "train_samples": len(train_backtest),
                    "test_samples": len(test_fixture_ids),
                    "eligible_samples": len(evaluated),
                    "excluded_samples": max(0, len(test_fixture_ids) - len(evaluated_ids)),
                    "prediction_records": [
                        {
                            "backtest_run_id": None,
                            "window_id": window["window_id"],
                            "prediction_id": row.get("prediction_id"),
                            "prediction_timestamp": row.get("prediction_created_at"),
                            "evaluation_timestamp": row.get("evaluation_timestamp"),
                            "model_version": row.get("model_version"),
                            "feature_version": row.get("feature_version") or FEATURE_VERSION,
                            "ensemble_version": row.get("ensemble_version") or ENSEMBLE_VERSION,
                            "calibration_version": row.get("calibration_version") or calibration.get("calibration_version", CALIBRATION_VERSION),
                        }
                        for row in evaluated
                    ],
                    "forecast_metrics": {
                        "baseline": evaluate_probabilities(evaluated, lambda row: row.get("existing_probabilities")),
                        "p3_ensemble": evaluate_probabilities(evaluated, lambda row: row.get("calibrated_probabilities")),
                        "paired_comparison": _paired_comparison(evaluated),
                    },
                    "betting_metrics": _betting_metrics(
                        [row for row in test_rows if str(row.get("fixture_id") or "") in evaluated_ids]
                    ),
                    "calibration": calibration,
                    "sample_size_warning": sample_size_warning(len(evaluated)),
                    "quality": {"exclusion_reasons": dict(sorted(quality_reasons.items()))},
                }
            )
        total_test = sum(item["test_samples"] for item in reports)
        total_eligible = sum(item["eligible_samples"] for item in reports)
        return {
            "status": "ok" if reports else "insufficient_sample",
            "config": {
                "start": parse_timestamp(start).isoformat(),
                "end": parse_timestamp(end).isoformat(),
                "train_days": train_days,
                "test_days": test_days,
                "step_days": step_days,
            },
            "dataset_version": _dataset_fingerprint(self.settlements),
            "windows": reports,
            "runs": len(reports),
            "total_fixtures": total_test,
            "eligible_fixtures": total_eligible,
            "excluded_fixtures": max(0, total_test - total_eligible),
            "sample_size_warning": sample_size_warning(total_eligible),
            "leakage_check": {"passed": not leakage_issues, "future_windows": leakage_issues},
            "forecast_metrics": {"separate_from_betting": True},
            "betting_metrics": {"separate_from_forecast": True},
            "versions": {
                "feature_version": FEATURE_VERSION,
                "ensemble_version": ENSEMBLE_VERSION,
                "calibration_version": CALIBRATION_VERSION,
            },
        }


class BacktestRunService:
    """Persist a reproducible completed run without opening a write API."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def save_result(
        self,
        name: str,
        result: Mapping[str, Any],
        *,
        config: Mapping[str, Any] | None = None,
        code_version: str = BACKTEST_VERSION,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        dataset_version = result.get("dataset_version") or DATASET_VERSION
        run_key = json.dumps({"name": name, "dataset_version": dataset_version, "config": config or result.get("config") or {}}, sort_keys=True, separators=(",", ":"))
        run_id = f"backtest:{hashlib.sha256(run_key.encode()).hexdigest()[:32]}"
        existing_reader = getattr(self.repository, "backtest_run", None)
        if callable(existing_reader):
            existing = existing_reader(run_id)
            if existing:
                return existing
        stored_result = json.loads(json.dumps(dict(result), ensure_ascii=False, default=str))
        for window in stored_result.get("windows") or []:
            for record in window.get("prediction_records") or []:
                record["backtest_run_id"] = run_id
        run = {
            "run_id": run_id,
            "name": name,
            "started_at": now,
            "finished_at": now,
            "dataset_version": dataset_version,
            "config": dict(config or result.get("config") or {}),
            "code_version": code_version,
            "model_version": "persisted-settlement-models",
            "feature_version": FEATURE_VERSION,
            "ensemble_version": ENSEMBLE_VERSION,
            "calibration_version": CALIBRATION_VERSION,
            "status": result.get("status") or "completed",
            "result": stored_result,
        }
        saver = getattr(self.repository, "save_backtest_run", None)
        if callable(saver):
            saver(run)
        return run


def serialize_public(value: Any) -> Any:
    """Apply the existing player-safe public payload sanitizer to P4 responses."""

    return public_payload(value)
