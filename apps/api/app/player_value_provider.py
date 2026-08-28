"""Authorized, replaceable player market-value provider boundary."""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .player_identity import link_evidence_players


SUPPORTED_LEAGUES = frozenset({"epl", "laliga", "csl"})
MISSING_VALUE_REASON = "暂无覆盖英超、西甲和中超且再展示授权明确的身价源"


class PlayerValueProvider(Protocol):
    source_name: str | None
    supported_leagues: frozenset[str]
    redisplay_authorized: bool

    @property
    def configured(self) -> bool: ...

    async def fetch_values(
        self,
        canonical_player_ids: list[str],
        league_key: str,
    ) -> list[dict[str, Any]]: ...


class NullPlayerValueProvider:
    """Explicit runtime provider used until a licensed source is configured."""

    source_name = None
    supported_leagues: frozenset[str] = frozenset()
    redisplay_authorized = False

    @property
    def configured(self) -> bool:
        return False

    async def fetch_values(
        self,
        canonical_player_ids: list[str],
        league_key: str,
    ) -> list[dict[str, Any]]:
        return []


class PlayerValueService:
    """Apply cached licensed values and refresh them only through an authorized provider."""

    def __init__(
        self,
        provider: PlayerValueProvider,
        repository: Any,
        stale_after_days: int = 14,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.stale_after = timedelta(days=max(1, stale_after_days))

    async def enrich(self, context: dict[str, Any], league_key: str) -> dict[str, Any]:
        link_evidence_players(context)
        players = [
            player
            for side in ("home", "away")
            for player in (context.get("squads") or {}).get(side) or []
        ]
        canonical_ids = list(
            dict.fromkeys(
                player["canonical_player_id"]
                for player in players
                if player.get("canonical_player_id")
            )
        )
        cached = self._cached_values(canonical_ids)
        if self._can_refresh(league_key):
            fetched = await self.provider.fetch_values(canonical_ids, league_key)
            validated = [_validated_value(item, str(self.provider.source_name)) for item in fetched]
            validated = [item for item in validated if item["canonical_player_id"] in canonical_ids]
            if validated:
                saver = getattr(self.repository, "save_player_values", None)
                if callable(saver):
                    saver(validated)
                cached.update({item["canonical_player_id"]: item for item in validated})

        for player in players:
            value = cached.get(player.get("canonical_player_id"))
            if value:
                freshness = _freshness(value.get("market_value_as_of"), self.stale_after)
                player.update(
                    {
                        "market_value_eur": value["market_value_eur"],
                        "market_value": value["market_value_eur"],
                        "market_value_currency": "EUR",
                        "market_value_source": value["market_value_source"],
                        "market_value_as_of": value["market_value_as_of"],
                        "market_value_freshness": freshness,
                        "market_value_status": "available" if freshness == "fresh" else "stale",
                        "market_value_missing_reason": None,
                    }
                )
            else:
                player.update(
                    {
                        "market_value_eur": None,
                        "market_value": None,
                        "market_value_currency": "EUR",
                        "market_value_source": None,
                        "market_value_as_of": None,
                        "market_value_freshness": "missing",
                        "market_value_status": "missing",
                        "market_value_missing_reason": MISSING_VALUE_REASON,
                    }
                )
        context["player_value"] = {
            "provider_configured": bool(self.provider.configured),
            "source": self.provider.source_name,
            "redisplay_authorized": bool(self.provider.redisplay_authorized),
            "coverage": sorted(self.provider.supported_leagues),
            "available_count": sum(1 for player in players if player.get("market_value_eur") is not None),
            "missing_count": sum(1 for player in players if player.get("market_value_eur") is None),
            "status": "available" if any(player.get("market_value_eur") is not None for player in players) else "unavailable",
            "reason": None if any(player.get("market_value_eur") is not None for player in players) else MISSING_VALUE_REASON,
        }
        return context

    def _can_refresh(self, league_key: str) -> bool:
        return bool(
            self.provider.configured
            and self.provider.redisplay_authorized
            and SUPPORTED_LEAGUES.issubset(self.provider.supported_leagues)
            and league_key in self.provider.supported_leagues
        )

    def _cached_values(self, canonical_ids: list[str]) -> dict[str, dict[str, Any]]:
        reader = getattr(self.repository, "player_values", None)
        values = reader(canonical_ids) if callable(reader) else []
        return {item["canonical_player_id"]: item for item in values}


def _validated_value(value: dict[str, Any], source_name: str) -> dict[str, Any]:
    canonical_id = str(value.get("canonical_player_id") or "")
    amount = value.get("market_value_eur")
    as_of = str(value.get("market_value_as_of") or "")
    source = str(value.get("market_value_source") or source_name or "")
    if not canonical_id or not source or not as_of:
        raise ValueError("Player value requires identity, source, and as-of provenance")
    try:
        amount = float(amount)
    except (TypeError, ValueError) as error:
        raise ValueError("Player value must be a numeric EUR amount") from error
    if amount < 0:
        raise ValueError("Player value cannot be negative")
    _parse_datetime(as_of)
    return {
        "canonical_player_id": canonical_id,
        "market_value_eur": round(amount, 2),
        "market_value_source": source,
        "market_value_as_of": as_of,
        "cached_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def _freshness(as_of: Any, stale_after: timedelta) -> str:
    try:
        age = datetime.now(UTC) - _parse_datetime(str(as_of))
    except (TypeError, ValueError):
        return "stale"
    return "fresh" if timedelta(0) <= age <= stale_after else "stale"


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
