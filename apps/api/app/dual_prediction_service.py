"""Run independent model prediction services in parallel for one fixture."""

import asyncio
import inspect
import logging
from datetime import UTC, datetime
from typing import Any

from .leakage_audit import FutureDataLeakageError
from .prediction_intelligence import build_performance_profiles, weighted_ensemble


logger = logging.getLogger(__name__)


class DualPredictionService:
    def __init__(
        self,
        services: dict[str, Any],
        competition_id: str,
        player_name_service: Any | None = None,
        model_registry_service: Any | None = None,
    ) -> None:
        self.services = services
        self.model_keys = tuple(services)
        self.competition_id = competition_id
        self.player_name_service = player_name_service
        self.model_registry_service = model_registry_service

    @property
    def configured(self) -> bool:
        return any(bool(getattr(service.model_provider, "configured", False)) for service in self.services.values())

    async def prepare_context(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        *,
        prediction_timestamp: Any | None = None,
    ) -> Any:
        """Prepare shared evidence once through the primary prediction service."""

        if not self.services:
            return None
        if self.player_name_service is not None:
            await self.player_name_service.enrich(context, resolve_missing=True)
        primary = next(iter(self.services.values()))
        prepare_context = getattr(primary, "prepare_context", None)
        if not callable(prepare_context):
            return None
        parameters = inspect.signature(prepare_context).parameters
        kwargs = (
            {"prediction_timestamp": prediction_timestamp}
            if "prediction_timestamp" in parameters
            else {}
        )
        return await prepare_context(fixture, context, **kwargs)

    async def create(
        self,
        fixture: dict[str, Any],
        context: dict[str, Any],
        model_keys: list[str] | tuple[str, ...] | None = None,
        *,
        snapshot_bundle: dict[str, Any] | None = None,
        prepared_context: bool = False,
        historical_snapshot: dict[str, Any] | None = None,
        prediction_timestamp: Any | None = None,
    ) -> list[dict[str, Any]]:
        requested_timestamp = prediction_timestamp or (historical_snapshot or {}).get(
            "prediction_timestamp"
        )
        preparation_timestamp = requested_timestamp or datetime.now(UTC).isoformat()
        selected = [self.services[key] for key in (model_keys or self.model_keys) if key in self.services]
        if not selected:
            return []
        if self.player_name_service is not None:
            await self.player_name_service.enrich(context, resolve_missing=True)
        snapshot_bundle = snapshot_bundle or (
            historical_snapshot or {}
        ).get("prediction_bundle")
        primary = selected[0]
        prepare_context = getattr(primary, "prepare_context", None)
        prepare_snapshot = getattr(primary, "prepare_snapshot", None)
        persist_snapshot_bundle = getattr(primary, "persist_snapshot_bundle", None)
        if snapshot_bundle is None and callable(prepare_context) and callable(prepare_snapshot):
            context_parameters = inspect.signature(prepare_context).parameters
            context_kwargs = {
                "prediction_timestamp": preparation_timestamp,
            } if "prediction_timestamp" in context_parameters else {}
            await prepare_context(fixture, context, **context_kwargs)
            snapshot_timestamp = requested_timestamp or datetime.now(UTC).isoformat()
            snapshot_parameters = inspect.signature(prepare_snapshot).parameters
            snapshot_kwargs = {
                "prediction_timestamp": snapshot_timestamp,
            } if "prediction_timestamp" in snapshot_parameters else {}
            snapshot_bundle = prepare_snapshot(fixture, context, **snapshot_kwargs)
            if callable(persist_snapshot_bundle):
                persist_snapshot_bundle(snapshot_bundle)
            prepared_context = True
        prediction_timestamp = (
            requested_timestamp
            or ((snapshot_bundle or {}).get("evidence") or {}).get("captured_at")
            or datetime.now(UTC).isoformat()
        )
        async def create_one(service: Any) -> Any:
            parameters = inspect.signature(service.create).parameters
            kwargs: dict[str, Any] = {}
            if snapshot_bundle is not None and "snapshot_bundle" in parameters:
                kwargs["snapshot_bundle"] = snapshot_bundle
            if "prepared_context" in parameters:
                kwargs["prepared_context"] = prepared_context or snapshot_bundle is not None
            if prediction_timestamp is not None and "prediction_timestamp" in parameters:
                kwargs["prediction_timestamp"] = prediction_timestamp
            if "persist_production_evidence" in parameters:
                kwargs["persist_production_evidence"] = service is primary
            return await service.create(fixture, context, **kwargs)

        results = await asyncio.gather(
            *(create_one(service) for service in selected),
            return_exceptions=True,
        )
        predictions: list[dict[str, Any]] = []
        leakage_errors: list[FutureDataLeakageError] = []
        for service, result in zip(selected, results):
            if isinstance(result, Exception):
                if isinstance(result, FutureDataLeakageError):
                    leakage_errors.append(result)
                logger.warning(
                    "prediction failed for fixture %s model %s: %r",
                    fixture.get("id"),
                    getattr(service, "model_key", "?"),
                    result,
                    exc_info=result,
                )
                continue
            else:
                predictions.append(result)
        if leakage_errors:
            raise leakage_errors[0]
        base_predictions = {
            str(item.get("model_key") or (item.get("ai") or {}).get("provider") or "deepseek"): item.get("model_probabilities") or item.get("probabilities") or {}
            for item in predictions
        }
        baseline = next(
            (
                (item.get("baseline") or {}).get("probabilities")
                for item in predictions
                if (item.get("baseline") or {}).get("probabilities")
            ),
            None,
        )
        if baseline:
            base_predictions["poisson"] = baseline
        profiles: dict[str, dict[str, Any]] = {}
        reader = getattr(getattr(primary, "repository", None), "fixture_settlements", None)
        if callable(reader):
            profiles = build_performance_profiles(
                reader(competition_id=self.competition_id),
            )
        champion = None
        champion_reader = getattr(self.model_registry_service, "champion", None)
        if callable(champion_reader):
            try:
                champion = champion_reader("ensemble")
            except Exception:
                logger.warning("failed to read ensemble champion", exc_info=True)
        learned_weights = (getattr(champion, "payload", None) or {}).get("weights") if champion else None
        ensemble = weighted_ensemble(
            base_predictions,
            weights=learned_weights,
            profiles=profiles,
            league_key=fixture.get("league_key"),
        )
        ensemble["weights_source"] = "model_registry" if learned_weights else "defaults"
        # The individual services have already persisted their immutable
        # pre-match prediction and revision by this point.  The ensemble is a
        # derived response annotation; writing it back through
        # ``update_prediction`` would mutate the serving payload without a
        # corresponding append-only revision.  Return shallow copies so even
        # in-memory repository fakes cannot observe that annotation as a
        # mutation of the persisted object.
        return [{**item, "p3_ensemble": ensemble} for item in predictions]
