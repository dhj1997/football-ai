"""Historical prediction backfill isolated from the production betting chain."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Mapping

from .data import unavailable_context
from .historical_validation import (
    build_historical_snapshot,
    parse_timestamp,
)
from .league_data_pipeline import SUPPORTED_LEAGUES, normalize_league_code
from .prediction import MODEL_VERSION, predict
from .prediction_intelligence import build_feature_snapshot
from .recent_form import RecentFormService


P7_2_VERSION = "p7.2-historical-backfill-v1"
HISTORICAL_COMPETITION_ID = "p7.2-historical"
_CAPTURE_METADATA_KEYS = frozenset(
    {
        "captured_at",
        "source_captured_at",
        "source_synced_at",
        "synced_at",
        "ingested_at",
        "result_captured_at",
    }
)


class HistoricalPredictionBackfillService:
    """Create frozen historical predictions without touching production tables."""

    def __init__(
        self,
        repository: Any,
        *,
        max_total: int = 300,
        max_per_league: int = 100,
        prediction_runner: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.max_total = max(1, min(int(max_total), 300))
        self.max_per_league = max(1, min(int(max_per_league), 100))
        self.prediction_runner = prediction_runner
        self.recent_form = RecentFormService(repository)

    async def run(self) -> dict[str, Any]:
        started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        fixtures = self._canonical_fixtures()
        report: dict[str, Any] = {
            "run_id": f"{P7_2_VERSION}:{uuid.uuid4()}",
            "started_at": started_at,
            "finished_at": None,
            "status": "completed",
            "version": P7_2_VERSION,
            "total_fixtures": len(fixtures),
            "eligible_fixtures": 0,
            "excluded_fixtures": 0,
            "excluded_by_reason": defaultdict(int),
            "generated_predictions": 0,
            "generated_by_league": defaultdict(int),
            "prediction_timestamps_missing": 0,
            "feature_snapshots_missing": 0,
            "evidence_snapshots_missing": 0,
            "leakage_violations": 0,
            "items": [],
        }
        for fixture in fixtures:
            item = await self._backfill_fixture(fixture)
            report["items"].append(item)
            if item["status"] == "completed":
                report["eligible_fixtures"] += 1
                report["generated_predictions"] += item["predictions"]
                code = str(item["league"])
                report["generated_by_league"][code] += item["predictions"]
                report["prediction_timestamps_missing"] += item["prediction_timestamps_missing"]
                report["feature_snapshots_missing"] += item["feature_snapshots_missing"]
                report["evidence_snapshots_missing"] += item["evidence_snapshots_missing"]
                report["leakage_violations"] += item["leakage_violations"]
            else:
                report["excluded_fixtures"] += 1
                report["excluded_by_reason"][item["reason"]] += 1
        report["finished_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        report["excluded_by_reason"] = dict(sorted(report["excluded_by_reason"].items()))
        report["generated_by_league"] = dict(sorted(report["generated_by_league"].items()))
        saver = getattr(self.repository, "save_historical_backfill_run", None)
        if callable(saver):
            saver(report)
        return report

    async def backfill_fixture(self, fixture: Mapping[str, Any]) -> dict[str, Any]:
        """Backfill one canonical fixture using the same P7.2 path as a full run."""

        return await self._backfill_fixture(dict(fixture))

    def evaluation_rows(self) -> list[dict[str, Any]]:
        """Adapt isolated historical predictions to the existing P6 input contract."""

        reader = getattr(self.repository, "historical_predictions", None)
        predictions = reader(limit=5000) if callable(reader) else []
        fixture_reader = getattr(self.repository, "fixture", None)
        rows: list[dict[str, Any]] = []
        for prediction in predictions:
            item = dict(prediction)
            item.setdefault("prediction_id", item.get("id"))
            item.setdefault("prediction_created_at", item.get("prediction_timestamp"))
            fixture = fixture_reader(str(item.get("fixture_id"))) if callable(fixture_reader) and item.get("fixture_id") else None
            canonical_league = item.get("canonical_league") or (fixture or {}).get("canonical_league") or (fixture or {}).get("league_key")
            if canonical_league:
                item.setdefault("canonical_league", normalize_league_code(canonical_league) or canonical_league)
            item.setdefault("league_key", str(item.get("canonical_league") or "").casefold())
            item.setdefault("settled_at", item.get("actual_completed_at"))
            rows.append(item)
        return rows

    def _canonical_fixtures(self) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "list_fixtures", None)
        rows = reader() if callable(reader) else []
        grouped: dict[str, dict[str, Any]] = {}
        per_league: defaultdict[str, int] = defaultdict(int)
        for raw in rows:
            fixture = dict(raw)
            code = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
            canonical = str(fixture.get("canonical_fixture_id") or "")
            if not code or not canonical or per_league[code] >= self.max_per_league:
                continue
            if canonical in grouped:
                continue
            grouped[canonical] = fixture
            per_league[code] += 1
            if len(grouped) >= self.max_total:
                break
        return sorted(
            grouped.values(),
            key=lambda item: (
                parse_timestamp(item.get("kickoff")) or datetime.max.replace(tzinfo=UTC),
                str(item.get("id") or ""),
            ),
        )

    async def _backfill_fixture(self, fixture: dict[str, Any]) -> dict[str, Any]:
        code = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
        kickoff = parse_timestamp(fixture.get("kickoff"))
        score = fixture.get("score") or {}
        if code is None:
            return self._excluded(fixture, "unsupported_league")
        if str(fixture.get("status") or "").casefold() != "finished":
            return self._excluded(fixture, "not_finished")
        if kickoff is None:
            return self._excluded(fixture, "invalid_kickoff")
        if not _valid_score(score):
            return self._excluded(fixture, "missing_result")
        if not _team_identifier(fixture.get("home_team")) or not _team_identifier(fixture.get("away_team")):
            return self._excluded(fixture, "missing_team_identity")
        as_of = (kickoff - timedelta(hours=24)).isoformat()
        recent = self.recent_form.context_for_fixture(fixture, as_of=as_of)
        if recent is None or not recent.get("home") or not recent.get("away"):
            return self._excluded(fixture, "recent_form_unavailable")
        context = self._historical_context(fixture, as_of, recent)
        feature_snapshot = build_feature_snapshot(
            fixture,
            context,
            as_of,
            standings=context.get("standings"),
        )
        historical_fixture = _historical_fixture(fixture)
        evidence_snapshot = _build_evidence_snapshot(
            historical_fixture,
            context,
            feature_snapshot,
            as_of,
        )
        saver = getattr(self.repository, "save_evidence_snapshot", None)
        if callable(saver):
            existing_evidence_reader = getattr(self.repository, "evidence_snapshot", None)
            existing_evidence = (
                existing_evidence_reader(evidence_snapshot["id"])
                if callable(existing_evidence_reader)
                else None
            )
            if existing_evidence:
                evidence_snapshot = existing_evidence
            else:
                saver(evidence_snapshot)
        snapshot = build_historical_snapshot(
            historical_fixture,
            as_of,
            evidence_snapshots=[evidence_snapshot],
            odds_snapshots=[],
            dataset_version=P7_2_VERSION,
            source_versions={"fixture": "canonical-fixtures", "recent_form": P7_2_VERSION, "odds": None},
        )
        snapshot["canonical_fixture_id"] = str(fixture["canonical_fixture_id"])
        payload = dict(snapshot.get("payload") or {})
        payload["context"] = deepcopy(context)
        payload["feature_snapshot"] = deepcopy(feature_snapshot)
        payload["recent_form_snapshot"] = deepcopy(recent.get("snapshot"))
        payload["odds"] = None
        snapshot["payload"] = payload
        snapshot_saver = getattr(self.repository, "save_historical_snapshot", None)
        if callable(snapshot_saver):
            existing_snapshot_reader = getattr(self.repository, "historical_snapshot", None)
            existing_snapshot = (
                existing_snapshot_reader(snapshot["snapshot_id"])
                if callable(existing_snapshot_reader)
                else None
            )
            if existing_snapshot:
                snapshot = existing_snapshot
            else:
                snapshot_saver(snapshot)
        prediction = await self._prediction(fixture, context, feature_snapshot, evidence_snapshot, snapshot, as_of)
        existing_reader = getattr(self.repository, "historical_predictions", None)
        existing = existing_reader(fixture_id=str(fixture["id"]), model_key="poisson", limit=20) if callable(existing_reader) else []
        key_matches = [
            item
            for item in existing
            if str(item.get("model_version")) == MODEL_VERSION
            and str(item.get("prediction_timestamp")) == as_of
        ]
        prediction_saver = getattr(self.repository, "save_historical_prediction", None)
        stored = key_matches[0] if key_matches else None
        if stored is None and callable(prediction_saver):
            stored = prediction_saver(prediction)
        stored = stored or prediction
        audit = _audit_prediction(stored, snapshot, as_of)
        return {
            "fixture_id": str(fixture["id"]),
            "canonical_fixture_id": str(fixture["canonical_fixture_id"]),
            "league": code,
            "as_of": as_of,
            "status": "completed",
            "predictions": 1,
            "prediction_timestamps_missing": int(not stored.get("prediction_timestamp")),
            "feature_snapshots_missing": int(not stored.get("feature_snapshot_id")),
            "evidence_snapshots_missing": int(not stored.get("evidence_snapshot_id")),
            "leakage_violations": len(audit),
            "reused": bool(key_matches),
        }

    async def _prediction(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        feature_snapshot: dict[str, Any],
        evidence_snapshot: dict[str, Any],
        historical_snapshot: dict[str, Any],
        as_of: str,
    ) -> dict[str, Any]:
        if self.prediction_runner is not None:
            result = self.prediction_runner(fixture, context)
            if hasattr(result, "__await__"):
                result = await result
            prediction = dict(result)
        else:
            prediction = predict(fixture, context)
        prediction["created_at"] = as_of
        prediction["prediction_id"] = prediction.get("prediction_id") or prediction.get("id") or str(uuid.uuid4())
        prediction["id"] = prediction["prediction_id"]
        prediction["prediction_timestamp"] = as_of
        prediction["prediction_created_at"] = as_of
        prediction["model_key"] = "poisson"
        prediction["model_version"] = prediction.get("model_version") or MODEL_VERSION
        prediction["competition_id"] = HISTORICAL_COMPETITION_ID
        prediction["canonical_league"] = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
        prediction["league_key"] = str(prediction["canonical_league"] or "").casefold()
        prediction["canonical_fixture_id"] = str(fixture["canonical_fixture_id"])
        prediction["actual_outcome"] = _actual_outcome(fixture.get("score"))
        prediction["actual_completed_at"] = parse_timestamp(fixture.get("kickoff")).isoformat()
        prediction["feature_snapshot"] = feature_snapshot
        prediction["feature_snapshot_id"] = _stable_snapshot_id("feature", fixture, as_of)
        prediction["evidence_snapshot_id"] = evidence_snapshot["id"]
        prediction["evidence_hash"] = evidence_snapshot["content_hash"]
        prediction["evidence_version"] = evidence_snapshot["evidence_version"]
        prediction["odds_snapshot_id"] = None
        prediction["clv"] = None
        prediction["roi"] = None
        prediction["historical_backfill"] = {"version": P7_2_VERSION, "production_chain": False}
        prediction["baseline"] = {
            "model_version": MODEL_VERSION,
            "probabilities": deepcopy(prediction.get("probabilities") or {}),
        }
        prediction["ai"] = {"status": "not_run", "provider": "poisson", "historical": True}
        return prediction

    def _historical_context(
        self,
        fixture: dict[str, Any],
        as_of: str,
        recent: dict[str, Any],
    ) -> dict[str, Any]:
        context = unavailable_context()
        context["recent_form"] = recent
        context["source"] = "canonical-fixtures-as-of"
        context["synced_at"] = as_of
        context["standings"] = self._historical_standings(fixture, as_of)
        return context

    def _historical_standings(self, fixture: Mapping[str, Any], as_of: str) -> dict[str, Any]:
        cutoff = parse_timestamp(as_of)
        code = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
        stats: defaultdict[str, dict[str, Any]] = defaultdict(
            lambda: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0, "points": 0}
        )
        reader = getattr(self.repository, "list_fixtures", None)
        rows = reader() if callable(reader) else []
        seen_fixtures: set[str] = set()
        for row in rows:
            if normalize_league_code(row.get("canonical_league") or row.get("league_key")) != code:
                continue
            fixture_key = str(row.get("canonical_fixture_id") or row.get("id") or "")
            if not fixture_key or fixture_key in seen_fixtures:
                continue
            seen_fixtures.add(fixture_key)
            if str(row.get("status") or "").casefold() != "finished" or not _valid_score(row.get("score")):
                continue
            occurred = parse_timestamp(row.get("kickoff"))
            if cutoff is None or occurred is None or occurred > cutoff:
                continue
            home_id = _team_identifier(row.get("home_team"))
            away_id = _team_identifier(row.get("away_team"))
            if not home_id or not away_id:
                continue
            home_score, away_score = int(row["score"]["home"]), int(row["score"]["away"])
            _update_standing(stats[home_id], home_score, away_score)
            _update_standing(stats[away_id], away_score, home_score)
        home_id = _team_identifier(fixture.get("home_team"))
        away_id = _team_identifier(fixture.get("away_team"))
        return {
            "home": dict(stats[home_id]) if home_id else {},
            "away": dict(stats[away_id]) if away_id else {},
            "source": "canonical-fixtures-as-of",
            "updated_at": cutoff.isoformat() if cutoff else as_of,
        }

    @staticmethod
    def _excluded(fixture: Mapping[str, Any], reason: str) -> dict[str, Any]:
        return {
            "fixture_id": str(fixture.get("id") or ""),
            "canonical_fixture_id": str(fixture.get("canonical_fixture_id") or ""),
            "league": normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key")),
            "status": "excluded",
            "predictions": 0,
            "reason": reason,
            "prediction_timestamps_missing": 0,
            "feature_snapshots_missing": 0,
            "evidence_snapshots_missing": 0,
            "leakage_violations": 0,
        }


def _build_evidence_snapshot(
    fixture: Mapping[str, Any],
    context: Mapping[str, Any],
    feature_snapshot: Mapping[str, Any],
    as_of: str,
) -> dict[str, Any]:
    payload = {
        "fixture": dict(fixture),
        "context": deepcopy(dict(context)),
        "feature_snapshot": deepcopy(dict(feature_snapshot)),
        "standings": deepcopy(context.get("standings") or {}),
        "historical_backfill": {"version": P7_2_VERSION, "production_chain": False},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    snapshot_id = _stable_snapshot_id("evidence", fixture, as_of)
    return {
        "id": snapshot_id,
        "fixture_id": str(fixture["id"]),
        "created_at": as_of,
        "captured_at": as_of,
        "evidence_version": P7_2_VERSION,
        "hash_algorithm": "sha256",
        "source_synced_at": as_of,
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "payload": payload,
    }


def _historical_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Keep fixture identity/result while excluding retrieval-time metadata."""

    return {
        key: value
        for key, value in dict(fixture).items()
        if key not in _CAPTURE_METADATA_KEYS
    }


class HistoricalEvaluationRepository:
    """Read-only P7.2 view that keeps provenance outside the P6 audit input."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self._historical_cache: list[dict[str, Any]] | None = None
        self._evidence_cache: list[dict[str, Any]] | None = None

    def fixture(self, fixture_id: str) -> dict[str, Any] | None:
        reader = getattr(self.repository, "fixture", None)
        return reader(fixture_id) if callable(reader) else None

    def prediction(self, prediction_id: str) -> dict[str, Any] | None:
        reader = getattr(self.repository, "prediction", None)
        return reader(prediction_id) if callable(reader) else None

    def historical_snapshots(
        self,
        fixture_id: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if self._historical_cache is None:
            reader = getattr(self.repository, "historical_snapshots", None)
            source_rows = reader(limit=500) if callable(reader) else []
            self._historical_cache = [
                _sanitize_snapshot(row)
                for row in source_rows
                if str(row.get("dataset_version") or "") == P7_2_VERSION
            ]
        rows = [
            row
            for row in self._historical_cache
            if (fixture_id is None or str(row.get("fixture_id")) == str(fixture_id))
            and (as_of is None or str(row.get("as_of") or "") <= str(as_of))
        ]
        return rows[: max(1, min(int(limit), 500))]

    def evidence_snapshots(self, fixture_id: str | None = None) -> list[dict[str, Any]]:
        if self._evidence_cache is None:
            reader = getattr(self.repository, "evidence_snapshots", None)
            source_rows = reader() if callable(reader) else []
            self._evidence_cache = [
                _sanitize_snapshot(row)
                for row in source_rows
                if isinstance((row.get("payload") or {}).get("historical_backfill"), Mapping)
            ]
        return [
            row
            for row in self._evidence_cache
            if fixture_id is None or str(row.get("fixture_id")) == str(fixture_id)
        ]

    def odds_snapshots(self, fixture_id: str | None = None) -> list[dict[str, Any]]:
        return []


def _sanitize_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only retrieval timestamps nested under the fixture identity."""

    result = deepcopy(dict(snapshot))
    payload = result.get("payload")
    if not isinstance(payload, Mapping):
        return result
    payload_copy = deepcopy(dict(payload))
    if isinstance(payload_copy.get("fixture"), Mapping):
        payload_copy["fixture"] = _historical_fixture(payload_copy["fixture"])
    evidence = payload_copy.get("evidence")
    if isinstance(evidence, Mapping):
        evidence_copy = deepcopy(dict(evidence))
        nested = evidence_copy.get("payload")
        if isinstance(nested, Mapping) and isinstance(nested.get("fixture"), Mapping):
            nested_copy = deepcopy(dict(nested))
            nested_copy["fixture"] = _historical_fixture(nested_copy["fixture"])
            evidence_copy["payload"] = nested_copy
        payload_copy["evidence"] = evidence_copy
    result["payload"] = payload_copy
    return result


def _stable_snapshot_id(prefix: str, fixture: Mapping[str, Any], as_of: str) -> str:
    value = "|".join((prefix, str(fixture.get("canonical_fixture_id") or fixture.get("id") or ""), as_of, P7_2_VERSION))
    return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:32]}"


def _team_identifier(team: Any) -> str | None:
    if not isinstance(team, Mapping):
        return None
    for key in ("canonical_team_id", "provider_id", "id", "source_team_id", "team_id"):
        if team.get(key) not in (None, ""):
            return str(team[key])
    return None


def _valid_score(score: Any) -> bool:
    if not isinstance(score, Mapping):
        return False
    try:
        return int(score.get("home")) >= 0 and int(score.get("away")) >= 0
    except (TypeError, ValueError):
        return False


def _actual_outcome(score: Any) -> str | None:
    if not _valid_score(score):
        return None
    return "home" if int(score["home"]) > int(score["away"]) else "draw" if int(score["home"]) == int(score["away"]) else "away"


def _update_standing(row: dict[str, Any], goals_for: int, goals_against: int) -> None:
    row["played"] += 1
    row["goals_for"] += goals_for
    row["goals_against"] += goals_against
    if goals_for > goals_against:
        row["wins"] += 1
        row["points"] += 3
    elif goals_for == goals_against:
        row["draws"] += 1
        row["points"] += 1
    else:
        row["losses"] += 1


def _audit_prediction(prediction: Mapping[str, Any], snapshot: Mapping[str, Any], as_of: str) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    cutoff = parse_timestamp(as_of)
    if cutoff is None:
        return [{"field": "prediction_timestamp", "reason": "invalid_prediction_timestamp"}]
    for key in ("captured_at", "created_at", "updated_at"):
        timestamp = parse_timestamp(snapshot.get(key))
        if timestamp and timestamp > cutoff:
            violations.append({"field": key, "captured_at": timestamp.isoformat(), "reason": "captured_after_prediction"})
    feature = prediction.get("feature_snapshot") or {}
    captured = parse_timestamp(feature.get("captured_at")) if isinstance(feature, Mapping) else None
    if captured and captured > cutoff:
        violations.append({"field": "feature_snapshot.captured_at", "captured_at": captured.isoformat(), "reason": "captured_after_prediction"})
    return violations


__all__ = [
    "HISTORICAL_COMPETITION_ID",
    "HistoricalEvaluationRepository",
    "HistoricalPredictionBackfillService",
    "P7_2_VERSION",
]
