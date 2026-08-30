"""Historical multi-model prediction backfill isolated from production writes."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping

from .historical_backfill import HISTORICAL_COMPETITION_ID, P7_2_VERSION
from .prompt_contract import DEFAULT_PROMPT_CONTRACT
from .prediction_service import PredictionService


P7_3_VERSION = "p7.3-historical-multimodel-v1"
MODEL_ALIASES = {"gpt": "chatgpt", "chatgpt": "chatgpt", "deepseek": "deepseek"}


class _HistoricalWriteBarrier:
    """Delegate reads while making PredictionService persistence methods no-ops."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)

    def current_balance(self, *_: Any, **__: Any) -> float:
        return 1000.0

    def save(self, *_: Any, **__: Any) -> None:
        return None

    def prune_prediction_history(self, *_: Any, **__: Any) -> None:
        return None

    def update_prediction(self, *_: Any, **__: Any) -> None:
        return None


class HistoricalMultiModelBackfillService:
    """Generate GPT/DeepSeek predictions from frozen P7.2 evidence snapshots."""

    def __init__(
        self,
        repository: Any,
        model_services: Mapping[str, Any],
        *,
        source_version: str = P7_2_VERSION,
        max_total: int = 300,
        concurrency: int = 4,
    ) -> None:
        self.repository = repository
        self.model_services = {
            MODEL_ALIASES[key.casefold()]: service
            for key, service in model_services.items()
            if key.casefold() in MODEL_ALIASES
        }
        self.source_version = source_version
        self.max_total = max(1, min(int(max_total), 300))
        self.concurrency = max(1, min(int(concurrency), 8))

    async def run(self) -> dict[str, Any]:
        started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        source_predictions = self._eligible_predictions()
        models = ("poisson", "chatgpt", "deepseek")
        report: dict[str, Any] = {
            "run_id": f"{P7_3_VERSION}:{uuid.uuid4()}",
            "version": P7_3_VERSION,
            "source_version": self.source_version,
            "started_at": started_at,
            "finished_at": None,
            "status": "completed",
            "eligible_fixtures": len(source_predictions),
            "attempted_by_model": {key: 0 for key in models},
            "generated_by_model": {key: 0 for key in models},
            "reused_by_model": {key: 0 for key in models},
            "failed_by_model": {key: 0 for key in models},
            "ensemble_ready_fixtures": 0,
            "prediction_timestamps_missing": 0,
            "feature_snapshots_missing": 0,
            "evidence_snapshots_missing": 0,
            "leakage_violations": 0,
            "errors": [],
            "items": [],
        }
        report["generated_by_model"]["poisson"] = len(source_predictions)
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(source: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await self._backfill_fixture(source, report)

        items = await asyncio.gather(*(process(source) for source in source_predictions))
        for item in items:
            report["items"].append(item)
            report["prediction_timestamps_missing"] += item["prediction_timestamps_missing"]
            report["feature_snapshots_missing"] += item["feature_snapshots_missing"]
            report["evidence_snapshots_missing"] += item["evidence_snapshots_missing"]
            report["leakage_violations"] += item["leakage_violations"]
            if set(item["models_ready"]) == {"chatgpt", "deepseek", "poisson"}:
                report["ensemble_ready_fixtures"] += 1
        report["finished_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        saver = getattr(self.repository, "save_historical_backfill_run", None)
        if callable(saver):
            saver(report)
        return report

    def _eligible_predictions(self) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "historical_predictions", None)
        rows = reader(model_key="poisson", limit=5000) if callable(reader) else []
        eligible = []
        for row in rows:
            marker = row.get("historical_backfill") or {}
            if marker.get("version") != self.source_version:
                continue
            if not row.get("fixture_id") or not row.get("prediction_timestamp"):
                continue
            if not row.get("feature_snapshot_id") or not row.get("evidence_snapshot_id"):
                continue
            eligible.append(dict(row))
        return sorted(
            eligible[: self.max_total],
            key=lambda row: (str(row.get("prediction_timestamp")), str(row.get("fixture_id"))),
        )

    async def _backfill_fixture(self, source: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        fixture_id = str(source["fixture_id"])
        fixture_reader = getattr(self.repository, "fixture", None)
        fixture = fixture_reader(fixture_id) if callable(fixture_reader) else None
        snapshot, evidence = self._snapshots(source)
        if not fixture or not snapshot or not evidence:
            reason = "fixture_or_snapshot_missing"
            for model_key in self.model_services:
                report["failed_by_model"][model_key] += 1
                report["errors"].append({"fixture_id": fixture_id, "model_key": model_key, "reason": reason})
            return self._item(source, set(), reason)
        payload = snapshot.get("payload") or {}
        context = deepcopy(payload.get("context") or (evidence.get("payload") or {}).get("context") or {})
        feature_snapshot = deepcopy(source.get("feature_snapshot") or payload.get("feature_snapshot") or {})
        bundle = {
            "evidence": deepcopy(evidence),
            "odds": None,
            "standings": deepcopy(payload.get("standings") or context.get("standings") or {}),
            "quality": _quality(snapshot),
        }
        models_ready = {"poisson"}
        for model_key, configured_service in self.model_services.items():
            report["attempted_by_model"][model_key] += 1
            existing = self._existing_prediction(fixture_id, model_key, source["prediction_timestamp"])
            if existing:
                report["reused_by_model"][model_key] += 1
                models_ready.add(model_key)
                continue
            try:
                result = await self._run_model(
                    configured_service,
                    model_key,
                    fixture,
                    context,
                    bundle,
                    source,
                    feature_snapshot,
                )
                if result is None:
                    raise RuntimeError("provider did not return a completed historical forecast")
                saver = getattr(self.repository, "save_historical_prediction", None)
                if not callable(saver):
                    raise RuntimeError("historical prediction persistence is unavailable")
                saver(result)
                report["generated_by_model"][model_key] += 1
                models_ready.add(model_key)
            except Exception as error:
                report["failed_by_model"][model_key] += 1
                report["errors"].append(
                    {
                        "fixture_id": fixture_id,
                        "model_key": model_key,
                        "reason": _bounded_error(error),
                    }
                )
        return self._item(source, models_ready, None)

    async def _run_model(
        self,
        configured_service: Any,
        model_key: str,
        fixture: dict[str, Any],
        context: dict[str, Any],
        bundle: dict[str, Any],
        source: dict[str, Any],
        feature_snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        provider = getattr(configured_service, "model_provider", configured_service)
        if not bool(getattr(provider, "configured", False)):
            raise RuntimeError("provider is not configured")
        historical_service = PredictionService(
            provider,
            _HistoricalWriteBarrier(self.repository),
            model_key,
            HISTORICAL_COMPETITION_ID,
        )
        result = await historical_service.create(
            deepcopy(fixture),
            deepcopy(context),
            snapshot_bundle=deepcopy(bundle),
            prepared_context=True,
            prediction_timestamp=source["prediction_timestamp"],
        )
        ai = result.get("ai") or {}
        if str(ai.get("status")) != "completed":
            status = str(ai.get("status") or "unknown")
            reason = str(ai.get("error") or "provider did not return a completed historical forecast")
            raise RuntimeError(f"provider_status={status}: {reason[:260]}")
        model_version = str(result.get("model_version") or "")
        if not model_version:
            raise RuntimeError("completed provider response is missing model_version")
        prediction_id = _historical_prediction_id(
            fixture_id=str(source["fixture_id"]),
            model_key=model_key,
            model_version=model_version,
            prediction_timestamp=str(source["prediction_timestamp"]),
        )
        result["id"] = prediction_id
        result["prediction_id"] = prediction_id
        result["created_at"] = source["prediction_timestamp"]
        result["prediction_created_at"] = source["prediction_timestamp"]
        result["prediction_timestamp"] = source["prediction_timestamp"]
        result["model_key"] = model_key
        result["model_version"] = model_version
        canonical_league = source.get("canonical_league") or fixture.get("canonical_league") or fixture.get("league_key")
        result["canonical_fixture_id"] = source.get("canonical_fixture_id")
        result["canonical_league"] = canonical_league
        result["league_key"] = str(canonical_league or "").casefold()
        result["competition_id"] = HISTORICAL_COMPETITION_ID
        result["actual_outcome"] = source.get("actual_outcome")
        result["actual_completed_at"] = source.get("actual_completed_at")
        result["feature_snapshot"] = deepcopy(feature_snapshot)
        result["feature_snapshot_id"] = source["feature_snapshot_id"]
        result["evidence_snapshot_id"] = source["evidence_snapshot_id"]
        result["evidence_hash"] = source.get("evidence_hash")
        result["evidence_version"] = source.get("evidence_version")
        result["prompt_version"] = result.get("prompt_version") or (result.get("ai") or {}).get("prompt_version") or DEFAULT_PROMPT_CONTRACT.version
        result["odds_snapshot_id"] = None
        result["clv"] = None
        result["roi"] = None
        result["historical_backfill"] = {
            "version": P7_3_VERSION,
            "source_version": self.source_version,
            "production_chain": False,
        }
        return result

    def _snapshots(self, source: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        fixture_id = str(source["fixture_id"])
        snapshot_reader = getattr(self.repository, "historical_snapshots", None)
        snapshots = snapshot_reader(fixture_id=fixture_id, limit=50) if callable(snapshot_reader) else []
        snapshot = next(
            (
                row
                for row in snapshots
                if str(row.get("dataset_version")) == self.source_version
                and str(row.get("evidence_snapshot_id")) == str(source.get("evidence_snapshot_id"))
            ),
            None,
        )
        evidence_reader = getattr(self.repository, "evidence_snapshot", None)
        evidence = evidence_reader(str(source["evidence_snapshot_id"])) if callable(evidence_reader) else None
        if evidence is None:
            reader = getattr(self.repository, "evidence_snapshots", None)
            rows = reader(fixture_id) if callable(reader) else []
            evidence = next((row for row in rows if str(row.get("id")) == str(source["evidence_snapshot_id"])), None)
        return snapshot, evidence

    def _existing_prediction(self, fixture_id: str, model_key: str, prediction_timestamp: str) -> dict[str, Any] | None:
        reader = getattr(self.repository, "historical_predictions", None)
        rows = reader(fixture_id=fixture_id, model_key=model_key, limit=50) if callable(reader) else []
        return next(
            (
                row
                for row in rows
                if str(row.get("prediction_timestamp")) == prediction_timestamp
                and str((row.get("historical_backfill") or {}).get("version")) == P7_3_VERSION
            ),
            None,
        )

    @staticmethod
    def _item(source: Mapping[str, Any], models_ready: set[str], reason: str | None) -> dict[str, Any]:
        return {
            "fixture_id": str(source.get("fixture_id") or ""),
            "canonical_fixture_id": str(source.get("canonical_fixture_id") or ""),
            "canonical_league": source.get("canonical_league"),
            "prediction_timestamp": source.get("prediction_timestamp"),
            "models_ready": sorted(models_ready),
            "reason": reason,
            "prediction_timestamps_missing": 0,
            "feature_snapshots_missing": 0,
            "evidence_snapshots_missing": 0,
            "leakage_violations": 0,
        }


def _quality(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    payload = snapshot.get("payload") or {}
    data_quality = payload.get("data_quality") or {}
    fields = {
        str(check.get("code")): check.get("status") == "ok"
        for check in data_quality.get("checks") or []
        if check.get("code")
    }
    return {"score": snapshot.get("data_quality_score", 0.0), "fields": fields}


def _historical_prediction_id(
    *, fixture_id: str, model_key: str, model_version: str, prediction_timestamp: str
) -> str:
    identity = "|".join((P7_3_VERSION, fixture_id, model_key, model_version, prediction_timestamp))
    return f"historical-prediction:{hashlib.sha256(identity.encode()).hexdigest()[:32]}"


def _bounded_error(error: Exception) -> str:
    return (str(error).replace("\n", " ").replace("\r", " ")[:300] or error.__class__.__name__)


__all__ = ["HistoricalMultiModelBackfillService", "P7_3_VERSION"]
