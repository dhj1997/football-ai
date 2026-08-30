"""Continuous historical OOS accumulation, isolated from production execution."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any, Mapping

from .historical_backfill import (
    HISTORICAL_COMPETITION_ID,
    P7_2_VERSION,
    HistoricalEvaluationRepository,
    HistoricalPredictionBackfillService,
)
from .historical_multimodel import HistoricalMultiModelBackfillService, P7_3_VERSION
from .historical_validation import parse_timestamp
from .league_data_pipeline import normalize_league_code
from .model_evaluation import ModelEvaluationService, leakage_audit


P7_4_VERSION = "p7.4-historical-oos-accumulation-v1"
_MODEL_KEYS = ("poisson", "chatgpt", "deepseek")


class HistoricalOOSAccumulationService:
    """Scan finished canonical fixtures and append only missing historical forecasts."""

    def __init__(
        self,
        repository: Any,
        model_services: Mapping[str, Any],
        *,
        max_total: int = 300,
        max_per_league: int = 100,
        concurrency: int = 4,
    ) -> None:
        self.repository = repository
        self.max_total = max(1, min(int(max_total), 300))
        self.max_per_league = max(1, min(int(max_per_league), 100))
        self.backfill = HistoricalPredictionBackfillService(
            repository,
            max_total=self.max_total,
            max_per_league=self.max_per_league,
        )
        self.multimodel = HistoricalMultiModelBackfillService(
            repository,
            model_services,
            max_total=self.max_total,
            concurrency=concurrency,
        )

    async def run(self) -> dict[str, Any]:
        started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        fixtures = self._selected_fixtures()
        skipped_by_reason: defaultdict[str, int] = defaultdict(int)
        source_predictions: list[dict[str, Any]] = []
        existing_rows_before: list[dict[str, Any]] = []
        existing_before = 0
        generated_poisson = 0
        items: list[dict[str, Any]] = []

        for fixture in fixtures["selected"]:
            fixture_id = str(fixture.get("id") or "")
            before = self._fixture_predictions(fixture_id)
            existing_rows_before.extend(before)
            existing_before += len(before)
            source = self._source_prediction(fixture_id)
            if source is None:
                result = await self.backfill.backfill_fixture(fixture)
                if result.get("status") != "completed":
                    reason = str(result.get("reason") or "historical_backfill_excluded")
                    skipped_by_reason[reason] += 1
                    items.append({"fixture_id": fixture_id, "status": "skipped", "reason": reason})
                    continue
                source = self._source_prediction(fixture_id)
                if source is not None and not before:
                    generated_poisson += 1
            if source is None:
                skipped_by_reason["poisson_prediction_unavailable"] += 1
                items.append({"fixture_id": fixture_id, "status": "skipped", "reason": "poisson_prediction_unavailable"})
                continue
            source = {
                **source,
                "canonical_league": normalize_league_code(
                    fixture.get("canonical_league") or fixture.get("league_key")
                ),
            }
            source_predictions.append(source)

        model_report = await self.multimodel.run(source_predictions, persist_run=False)
        after = self._all_historical_predictions()
        generated_by_model = {
            "poisson": generated_poisson,
            "chatgpt": int(model_report["generated_by_model"].get("chatgpt", 0)),
            "deepseek": int(model_report["generated_by_model"].get("deepseek", 0)),
        }
        newly_generated = sum(generated_by_model.values())
        current_counts = self._current_model_counts(after)
        eligible_by_league = Counter(str(row.get("canonical_league") or "") for row in source_predictions)
        generated_by_league_model = self._generated_by_league(after, existing_rows_before, source_predictions)
        existing_by_league_model = self._existing_by_league(existing_rows_before, source_predictions)
        audit_rows = HistoricalPredictionBackfillService(self.repository).evaluation_rows()
        audit_view = HistoricalEvaluationRepository(self.repository)
        audit = leakage_audit(
            audit_rows,
            snapshot_reader=lambda fixture_id: audit_view.historical_snapshots(fixture_id=fixture_id, limit=100),
        )
        leakage_violations = int(audit.get("violations", 0)) + int(model_report.get("leakage_violations", 0))
        completed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        merged_skips: defaultdict[str, int] = defaultdict(int)
        for reason, count in fixtures["skipped_by_reason"].items():
            merged_skips[reason] += int(count)
        for reason, count in skipped_by_reason.items():
            merged_skips[reason] += int(count)
        skipped_count = sum(merged_skips.values()) + fixtures["deduplicated_records"]
        report: dict[str, Any] = {
            "run_id": f"{P7_4_VERSION}:{uuid.uuid4()}",
            "version": P7_4_VERSION,
            "source_versions": {"backfill": P7_2_VERSION, "multimodel": P7_3_VERSION},
            "competition_id": HISTORICAL_COMPETITION_ID,
            "started_at": started_at,
            "completed_at": completed_at,
            "finished_at": completed_at,
            "status": "partial" if model_report.get("errors") else "completed",
            "total_fixtures_scanned": fixtures["scanned"],
            "total_fixtures": fixtures["scanned"],
            "canonical_fixtures_selected": len(fixtures["selected"]),
            "eligible_fixtures": len(source_predictions),
            "skipped_fixtures": skipped_count,
            "excluded_fixtures": skipped_count,
            "excluded_by_reason": dict(sorted(merged_skips.items())),
            "deduplicated_records": fixtures["deduplicated_records"],
            "newly_generated_predictions": newly_generated,
            "generated_predictions": newly_generated,
            "already_existing_predictions": existing_before,
            "model_failures": sum(int(value) for value in model_report.get("failed_by_model", {}).values()),
            "model_failures_by_model": dict(model_report.get("failed_by_model") or {}),
            "generated_by_model": generated_by_model,
            "already_existing_by_model": self._model_counts(existing_rows_before, source_predictions),
            "eligible_by_league": dict(sorted(eligible_by_league.items())),
            "generated_by_league_model": generated_by_league_model,
            "already_existing_by_league_model": existing_by_league_model,
            "prediction_counts_by_model": current_counts,
            "attempted_by_model": dict(model_report.get("attempted_by_model") or {}),
            "leakage_violations": leakage_violations,
            "leakage_audit": audit,
            "errors": list(model_report.get("errors") or []),
            "items": items,
            "automatic_after_sync": True,
        }
        saver = getattr(self.repository, "save_historical_backfill_run", None)
        if callable(saver):
            saver(report)
        return report

    def run_p6_evaluation(self) -> dict[str, Any]:
        """Run P6 explicitly against the isolated historical view."""

        rows = HistoricalPredictionBackfillService(self.repository).evaluation_rows()
        return ModelEvaluationService(HistoricalEvaluationRepository(self.repository)).evaluate(rows)

    def _selected_fixtures(self) -> dict[str, Any]:
        reader = getattr(self.repository, "list_fixtures", None)
        rows = list(reader() if callable(reader) else [])
        selected: dict[str, dict[str, Any]] = {}
        per_league: defaultdict[str, int] = defaultdict(int)
        skipped: defaultdict[str, int] = defaultdict(int)
        deduplicated = 0
        for raw in rows:
            fixture = dict(raw)
            code = normalize_league_code(fixture.get("canonical_league") or fixture.get("league_key"))
            if code is None:
                skipped["unsupported_league"] += 1
                continue
            canonical_id = str(fixture.get("canonical_fixture_id") or fixture.get("id") or "")
            if not canonical_id:
                skipped["missing_canonical_identity"] += 1
                continue
            if canonical_id in selected:
                deduplicated += 1
                continue
            if per_league[code] >= self.max_per_league:
                skipped["league_fixture_cap"] += 1
                continue
            if len(selected) >= self.max_total:
                skipped["total_fixture_cap"] += 1
                continue
            selected[canonical_id] = fixture
            per_league[code] += 1
        return {
            "scanned": len(rows),
            "selected": sorted(
                selected.values(),
                key=lambda row: (parse_timestamp(row.get("kickoff")) or datetime.max.replace(tzinfo=UTC), str(row.get("id") or "")),
            ),
            "skipped_by_reason": dict(skipped),
            "deduplicated_records": deduplicated,
        }

    def _source_prediction(self, fixture_id: str) -> dict[str, Any] | None:
        rows = self._fixture_predictions(fixture_id)
        return next(
            (
                row
                for row in rows
                if str(row.get("model_key")) == "poisson"
                and str((row.get("historical_backfill") or {}).get("version")) == P7_2_VERSION
                and row.get("prediction_timestamp")
                and row.get("feature_snapshot_id")
                and row.get("evidence_snapshot_id")
            ),
            None,
        )

    def _fixture_predictions(self, fixture_id: str) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "historical_predictions", None)
        return list(reader(fixture_id=fixture_id, limit=50) if callable(reader) else [])

    def _all_historical_predictions(self) -> list[dict[str, Any]]:
        reader = getattr(self.repository, "historical_predictions", None)
        return list(reader(limit=5000) if callable(reader) else [])

    @staticmethod
    def _current_model_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {key: 0 for key in _MODEL_KEYS}
        for row in rows:
            key = str(row.get("model_key") or "")
            marker = str((row.get("historical_backfill") or {}).get("version") or "")
            if key == "poisson" and marker == P7_2_VERSION:
                counts[key] += 1
            elif key in {"chatgpt", "deepseek"} and marker == P7_3_VERSION:
                counts[key] += 1
        return counts

    @staticmethod
    def _model_counts(rows: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, int]:
        fixture_ids = {str(row.get("fixture_id")) for row in sources}
        counts = {key: 0 for key in _MODEL_KEYS}
        for row in rows:
            if str(row.get("fixture_id")) in fixture_ids and str(row.get("model_key")) in counts:
                counts[str(row.get("model_key"))] += 1
        return counts

    @staticmethod
    def _generated_by_league(
        rows: list[dict[str, Any]],
        existing_rows: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> dict[str, dict[str, int]]:
        source_leagues = {
            str(source.get("fixture_id")): str(source.get("canonical_league") or "")
            for source in sources
        }
        existing_keys = {
            (
                str(row.get("fixture_id")),
                str(row.get("model_key")),
                str(row.get("model_version")),
                str(row.get("prediction_timestamp")),
            )
            for row in existing_rows
        }
        result: defaultdict[str, dict[str, int]] = defaultdict(lambda: {key: 0 for key in _MODEL_KEYS})
        for row in rows:
            fixture_id = str(row.get("fixture_id"))
            league = source_leagues.get(fixture_id)
            key = str(row.get("model_key") or "")
            marker = str((row.get("historical_backfill") or {}).get("version") or "")
            identity = (
                fixture_id,
                key,
                str(row.get("model_version")),
                str(row.get("prediction_timestamp")),
            )
            valid_marker = (key == "poisson" and marker == P7_2_VERSION) or (
                key in {"chatgpt", "deepseek"} and marker == P7_3_VERSION
            )
            if league and key in _MODEL_KEYS and valid_marker and identity not in existing_keys:
                result[league][key] += 1
        return dict(sorted(result.items()))

    @staticmethod
    def _existing_by_league(rows: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        leagues = {str(source.get("fixture_id")): str(source.get("canonical_league") or "") for source in sources}
        result: defaultdict[str, dict[str, int]] = defaultdict(lambda: {key: 0 for key in _MODEL_KEYS})
        for row in rows:
            league = leagues.get(str(row.get("fixture_id")))
            key = str(row.get("model_key") or "")
            if league and key in _MODEL_KEYS:
                result[league][key] += 1
        return dict(sorted(result.items()))

__all__ = ["HistoricalOOSAccumulationService", "P7_4_VERSION"]
