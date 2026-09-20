"""Dongqiudi player market-value parsing and cached evidence enrichment."""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .player_identity import link_evidence_players
from .team_names import to_chinese_player_name


SUPPORTED_LEAGUES = frozenset({"epl", "laliga", "csl"})
MISSING_VALUE_REASON = "懂球帝身价缓存尚未覆盖该球员或预测截止时间"


class PlayerValueProvider(Protocol):
    source_name: str | None
    supported_leagues: frozenset[str]

    @property
    def configured(self) -> bool: ...

    async def fetch_player_value(self, player: dict[str, Any]) -> dict[str, Any] | None: ...


class NullPlayerValueProvider:
    source_name = None
    supported_leagues: frozenset[str] = frozenset()
    request_interval_seconds = 0.0

    @property
    def configured(self) -> bool:
        return False

    async def fetch_player_value(self, player: dict[str, Any]) -> dict[str, Any] | None:
        return None


class DongqiudiPlayerValueProvider:
    """Map the public player-detail history into stable EUR evidence."""

    source_name = "dongqiudi"
    supported_leagues = SUPPORTED_LEAGUES

    def __init__(self, client: Any) -> None:
        self.client = client
        self.request_interval_seconds = max(
            0.0,
            float(getattr(client, "player_request_interval_seconds", 0.0)),
        )

    @property
    def configured(self) -> bool:
        return bool(getattr(self.client, "configured", False))

    async def fetch_player_value(self, player: dict[str, Any]) -> dict[str, Any] | None:
        provider_player_id = str(player.get("provider_player_id") or player.get("id") or "")
        canonical_player_id = str(player.get("canonical_player_id") or "")
        if not provider_player_id or not canonical_player_id:
            return None
        detail = await self.client.player_detail(provider_player_id)
        return parse_dongqiudi_player_value(
            detail,
            canonical_player_id=canonical_player_id,
            provider_player_id=provider_player_id,
            source_url=f"{str(getattr(self.client, 'base_url', '')).rstrip('/')}/player/{provider_player_id}",
        )


class PlayerValueService:
    """Attach cutoff-safe cached values without blocking on provider requests."""

    def __init__(
        self,
        provider: PlayerValueProvider,
        repository: Any,
        stale_after_days: int = 14,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.stale_after = timedelta(days=max(1, stale_after_days))

    async def enrich(
        self,
        context: dict[str, Any],
        league_key: str,
        cutoff_at: Any | None = None,
    ) -> dict[str, Any]:
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
        cached = self._cached_values(canonical_ids, cutoff_at)

        for player in players:
            value = cached.get(player.get("canonical_player_id"))
            if value:
                freshness = _freshness(value.get("cached_at"), self.stale_after)
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
        available_count = sum(1 for player in players if player.get("market_value_eur") is not None)
        context["player_value"] = {
            "provider_configured": bool(self.provider.configured),
            "source": self.provider.source_name,
            "coverage": sorted(self.provider.supported_leagues),
            "cutoff_at": _isoformat(cutoff_at),
            "available_count": available_count,
            "missing_count": len(players) - available_count,
            "status": "available" if available_count else "unavailable",
            "reason": None if available_count else MISSING_VALUE_REASON,
        }
        return context

    def _cached_values(
        self,
        canonical_ids: list[str],
        cutoff_at: Any | None,
    ) -> dict[str, dict[str, Any]]:
        reader = getattr(self.repository, "player_values", None)
        values = reader(canonical_ids, as_of=cutoff_at) if callable(reader) else []
        return {item["canonical_player_id"]: item for item in values}


def parse_dongqiudi_player_value(
    detail: dict[str, Any],
    *,
    canonical_player_id: str,
    provider_player_id: str,
    source_url: str,
    captured_at: str | None = None,
) -> dict[str, Any] | None:
    """Flatten one public player response and retain every valid dated value."""

    captured = captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    base_info = detail.get("base_info") or detail.get("base_info_v_1") or {}
    original_name = str(base_info.get("person_name") or "未知球员")
    player_name = to_chinese_player_name(original_name)
    groups = detail.get("history_market_values") or {}
    raw_groups = groups.values() if isinstance(groups, dict) else groups if isinstance(groups, list) else []
    history: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for group in raw_groups:
        if not isinstance(group, list):
            continue
        for raw in group:
            if not isinstance(raw, dict):
                continue
            record_date = str(raw.get("record_date") or "")[:10]
            try:
                amount = float(raw.get("market_value"))
                _parse_datetime(record_date)
            except (TypeError, ValueError):
                continue
            if amount < 0:
                continue
            key = (record_date, amount)
            if key in seen:
                continue
            seen.add(key)
            person_info = raw.get("person_info") or {}
            history.append(
                {
                    "market_value_eur": round(amount, 2),
                    "market_value_currency": "EUR",
                    "market_value_source": "dongqiudi",
                    "market_value_as_of": record_date,
                    "provider_player_id": provider_player_id,
                    "provider_person_id": str(person_info.get("id") or base_info.get("person_id") or "") or None,
                    "player_name": player_name,
                    "source_url": source_url,
                    "captured_at": captured,
                }
            )
    if not history:
        return None
    history.sort(key=lambda item: _parse_datetime(item["market_value_as_of"]))
    latest = history[-1]
    return {
        "canonical_player_id": canonical_player_id,
        "provider_player_id": provider_player_id,
        "provider_person_id": str(base_info.get("person_id") or "") or None,
        "player_name": player_name,
        "market_value_eur": latest["market_value_eur"],
        "market_value_currency": "EUR",
        "market_value_source": "dongqiudi",
        "market_value_as_of": latest["market_value_as_of"],
        "source_url": source_url,
        "cached_at": captured,
        "history": history,
    }


def _freshness(cached_at: Any, stale_after: timedelta) -> str:
    try:
        age = datetime.now(UTC) - _parse_datetime(str(cached_at))
    except (TypeError, ValueError):
        return "stale"
    return "fresh" if timedelta(0) <= age <= stale_after else "stale"


def _isoformat(value: Any | None) -> str | None:
    if value is None:
        return None
    return _parse_datetime(str(value)).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
