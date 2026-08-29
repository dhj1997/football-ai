"""Run independent model prediction services in parallel for one fixture."""

import asyncio
import inspect
from typing import Any

from .prediction_intelligence import build_performance_profiles, weighted_ensemble


class DualPredictionService:
    def __init__(self, services: dict[str, Any], competition_id: str, player_name_service: Any | None = None) -> None:
        self.services = services
        self.model_keys = tuple(services)
        self.competition_id = competition_id
        self.player_name_service = player_name_service

    @property
    def configured(self) -> bool:
        return any(bool(getattr(service.model_provider, "configured", False)) for service in self.services.values())

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
            await prepare_context(fixture, context)
            snapshot_bundle = prepare_snapshot(fixture, context)
            if callable(persist_snapshot_bundle):
                persist_snapshot_bundle(snapshot_bundle)
            prepared_context = True
        async def create_one(service: Any) -> Any:
            parameters = inspect.signature(service.create).parameters
            kwargs: dict[str, Any] = {}
            if snapshot_bundle is not None and "snapshot_bundle" in parameters:
                kwargs["snapshot_bundle"] = snapshot_bundle
            if "prepared_context" in parameters:
                kwargs["prepared_context"] = prepared_context or snapshot_bundle is not None
            if prediction_timestamp is not None and "prediction_timestamp" in parameters:
                kwargs["prediction_timestamp"] = prediction_timestamp
            return await service.create(fixture, context, **kwargs)

        results = await asyncio.gather(
            *(create_one(service) for service in selected),
            return_exceptions=True,
        )
        predictions: list[dict[str, Any]] = []
        for service, result in zip(selected, results):
            if isinstance(result, Exception):
                continue
            else:
                predictions.append(result)
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
        ensemble = weighted_ensemble(
            base_predictions,
            profiles=profiles,
            league_key=fixture.get("league_key"),
        )
        repository = getattr(primary, "repository", None)
        metadata_updater = getattr(repository, "update_prediction", None)
        for item in predictions:
            item["p3_ensemble"] = ensemble
            if callable(metadata_updater) and item.get("id"):
                metadata = {
                    **(item.get("metadata") or {}),
                    "p3_ensemble": ensemble,
                }
                try:
                    metadata_updater(item["id"], {"metadata": metadata})
                except Exception:
                    # P3 explainability must not make an otherwise valid prediction fail.
                    continue
                item["metadata"] = metadata
        return predictions
