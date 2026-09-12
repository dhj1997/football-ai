"""Ordered evidence-provider fallback policy."""

from datetime import UTC, datetime, timedelta
from typing import Any

from .player_identity import link_evidence_players


class EvidenceProviderChain:
    """Try API-Football, then ESPN, then TheSportsDB partial evidence."""

    def __init__(self, primary: Any, secondary: Any, public: Any) -> None:
        self.primary = primary
        self.secondary = secondary
        self.public = public

    @property
    def configured(self) -> bool:
        return any(bool(getattr(provider, "configured", False)) for provider in (self.primary, self.secondary, self.public))

    @property
    def secondary_configured(self) -> bool:
        return bool(getattr(self.secondary, "configured", False))

    @property
    def sources(self) -> list[str]:
        return [
            name
            for name, provider in (
                ("api-football", self.primary),
                ("espn", self.secondary),
                ("thesportsdb-partial", self.public),
            )
            if bool(getattr(provider, "configured", False)) or bool(getattr(provider, "public_configured", False))
        ]

    async def fetch(self, fixture: dict[str, Any]) -> dict[str, Any]:
        failures: list[dict[str, str]] = []
        for name, provider in (("api-football", self.primary), ("espn", self.secondary)):
            if not bool(getattr(provider, "configured", False)):
                continue
            try:
                return _with_failures(await provider.fetch(fixture), failures)
            except Exception as error:
                failures.append({"provider": name, "error": _bounded_error(error)})
        if bool(getattr(self.public, "public_configured", False)):
            try:
                return _with_failures(await self.public.fetch_public(fixture), failures)
            except Exception as error:
                failures.append({"provider": "thesportsdb-partial", "error": _bounded_error(error)})
        raise RuntimeError("all evidence providers failed: " + "; ".join(item["provider"] for item in failures))

    async def fetch_public(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Fetch partial evidence only from TheSportsDB."""

        method = getattr(self.public, "fetch_public", None)
        if not bool(getattr(self.public, "public_configured", False)) or not callable(method):
            raise RuntimeError("TheSportsDB public evidence provider is not configured")
        return await method(fixture)

    async def fetch_secondary(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Refresh from TheSportsDB without spending provider quota."""

        return await self.fetch_public(fixture)

    async def fetch_lineup(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Fetch only lineup data, falling back across configured providers."""

        failures: list[dict[str, str]] = []
        for name, provider in (("api-football", self.primary), ("espn", self.secondary)):
            if not bool(getattr(provider, "configured", False)):
                continue
            method = getattr(provider, "fetch_lineup", None)
            if not callable(method):
                failures.append({"provider": name, "error": "lineup-only endpoint unavailable"})
                continue
            try:
                return _with_failures(await method(fixture), failures)
            except Exception as error:
                failures.append({"provider": name, "error": _bounded_error(error)})
        raise RuntimeError("lineup providers failed: " + "; ".join(item["provider"] for item in failures))


def evidence_needs_enrichment(context: dict[str, Any] | None) -> bool:
    """Identify cached evidence that cannot support a useful recent-form view."""

    if not context:
        return True
    recent = context.get("recent_form") or {}
    home = recent.get("home") or []
    away = recent.get("away") or []
    return len(home) < 3 or len(away) < 3


def evidence_needs_daily_refresh(
    context: dict[str, Any] | None,
    now: datetime | None = None,
    max_age_minutes: int = 1440,
) -> bool:
    """Return whether daily pre-match evidence is incomplete or stale."""

    if not context:
        return True
    current = now or datetime.now(UTC)
    synced_at = _as_utc(context.get("synced_at"))
    if synced_at is None or current.astimezone(UTC) - synced_at >= timedelta(minutes=max(1, int(max_age_minutes))):
        return True
    recent = context.get("recent_form") or {}
    if len(recent.get("home") or []) < 3 or len(recent.get("away") or []) < 3:
        return True
    if not (context.get("head_to_head") or []):
        return True
    availability = context.get("availability") or {}
    if str(context.get("source") or "").startswith("thesportsdb-partial"):
        return True
    if not availability.get("checked_at") and not availability.get("updated_at") and not availability.get("players"):
        return True
    teams = context.get("teams") or {}
    if not (teams.get("home") or {}) or not (teams.get("away") or {}):
        return True
    return False


def should_use_secondary(context: dict[str, Any] | None) -> bool:
    """Use the quota-free refresh only for known provider-backed evidence."""

    source = str((context or {}).get("source") or "")
    return source.startswith("api-football") or source == "thesportsdb-partial"


def localize_evidence_players(context: dict[str, Any]) -> dict[str, Any]:
    """Apply reviewed aliases and stable identity links to all player evidence."""

    if context.get("source"):
        context["source"] = _merged_sources("", str(context["source"]))
    return link_evidence_players(context)


def merge_evidence(previous: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge a richer refresh without discarding already collected fields."""

    if not previous:
        return incoming
    merged = dict(previous)
    changed = False

    old_recent = previous.get("recent_form") or {}
    new_recent = incoming.get("recent_form") or {}
    if _form_count(new_recent) >= _form_count(old_recent) and new_recent:
        merged["recent_form"] = new_recent
        changed = merged["recent_form"] != old_recent

    for field in ("head_to_head", "availability", "lineup", "teams", "squads", "odds"):
        old_value = previous.get(field)
        new_value = incoming.get(field)
        should_replace = field == "odds" and bool(new_value) or _evidence_field_score(new_value) > _evidence_field_score(old_value)
        if should_replace:
            merged[field] = new_value
            changed = True

    for field in ("provider_failures", "fallback_from"):
        if incoming.get(field):
            merged[field] = incoming[field]
    if incoming.get("synced_at"):
        merged["synced_at"] = incoming["synced_at"]
    if changed and previous.get("source") and incoming.get("source"):
        merged["source"] = _merged_sources(str(previous["source"]), str(incoming["source"]))
    elif incoming.get("source") and not previous.get("source"):
        merged["source"] = incoming["source"]
    return merged


def _form_count(value: dict[str, Any]) -> int:
    return min(len(value.get("home") or []), 5) + min(len(value.get("away") or []), 5)


def _evidence_field_score(value: Any) -> int:
    if isinstance(value, list):
        localized = sum(
            1
            for item in value
            if isinstance(item, dict)
            and item.get("original_name")
            and item.get("name") != item.get("original_name")
        )
        stable_ids = sum(
            1
            for item in value
            if isinstance(item, dict) and (item.get("provider_player_id") or item.get("id"))
        )
        performance = sum(
            1
            for item in value
            if isinstance(item, dict)
            and isinstance(item.get("statistics"), dict)
            and any((item["statistics"].get(key) or 0) > 0 for key in ("appearances", "minutes", "goals", "assists", "saves"))
        )
        return len(value) + localized * 2 + stable_ids + performance * 4
    if isinstance(value, dict):
        if "home" in value or "away" in value:
            return sum(_evidence_field_score(value.get(side)) for side in ("home", "away"))
        if "players" in value:
            return len(value.get("players") or []) + int(bool(value.get("updated_at")))
        if "confirmed" in value:
            return int(bool(value.get("confirmed"))) * 100 + len(value.get("home_players") or []) + len(value.get("away_players") or [])
        return sum(1 for item in value.values() if item not in (None, "", [], {}))
    return int(bool(value))


def _with_failures(context: dict[str, Any], failures: list[dict[str, str]]) -> dict[str, Any]:
    result = dict(context)
    if failures:
        result["provider_failures"] = [*(result.get("provider_failures") or []), *failures][:4]
        result["fallback_from"] = failures[-1]["provider"]
    return result


def _bounded_error(error: Exception) -> str:
    return str(error)[:240] or error.__class__.__name__


def _as_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _merged_sources(previous: str, incoming: str) -> str:
    parts = [item for item in [*previous.split("+"), *incoming.split("+")] if item]
    return "+".join(dict.fromkeys(parts))
