"""Run independent model prediction services in parallel for one fixture."""

import asyncio
import inspect
from typing import Any


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
    ) -> list[dict[str, Any]]:
        selected = [self.services[key] for key in (model_keys or self.model_keys) if key in self.services]
        if not selected:
            return []
        if self.player_name_service is not None:
            await self.player_name_service.enrich(context, resolve_missing=True)
        snapshot_bundle = None
        prepared_context = False
        primary = selected[0]
        prepare_context = getattr(primary, "prepare_context", None)
        prepare_snapshot = getattr(primary, "prepare_snapshot", None)
        persist_snapshot_bundle = getattr(primary, "persist_snapshot_bundle", None)
        if callable(prepare_context) and callable(prepare_snapshot):
            await prepare_context(fixture, context)
            snapshot_bundle = prepare_snapshot(fixture, context)
            if callable(persist_snapshot_bundle):
                persist_snapshot_bundle(snapshot_bundle)
            prepared_context = True
        results = await asyncio.gather(
            *(
                service.create(
                    fixture,
                    context,
                    snapshot_bundle=snapshot_bundle,
                    prepared_context=prepared_context,
                )
                if snapshot_bundle is not None and "snapshot_bundle" in inspect.signature(service.create).parameters
                else service.create(fixture, context)
                for service in selected
            ),
            return_exceptions=True,
        )
        predictions: list[dict[str, Any]] = []
        for service, result in zip(selected, results):
            if isinstance(result, Exception):
                continue
            else:
                predictions.append(result)
        return predictions
