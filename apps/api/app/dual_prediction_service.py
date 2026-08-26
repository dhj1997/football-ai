"""Run independent model prediction services in parallel for one fixture."""

import asyncio
from typing import Any


class DualPredictionService:
    def __init__(self, services: dict[str, Any], competition_id: str) -> None:
        self.services = services
        self.model_keys = tuple(services)
        self.competition_id = competition_id

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
        results = await asyncio.gather(
            *(service.create(fixture, context) for service in selected),
            return_exceptions=True,
        )
        predictions: list[dict[str, Any]] = []
        for service, result in zip(selected, results):
            if isinstance(result, Exception):
                continue
            else:
                predictions.append(result)
        return predictions
