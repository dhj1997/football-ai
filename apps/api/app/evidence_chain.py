"""Ordered evidence-provider fallback policy."""

from typing import Any

from .team_names import to_chinese_player_name


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
        failures: list[dict[str, str]] = []
        for name, provider in (("espn", self.secondary), ("thesportsdb-partial", self.public)):
            configured = bool(getattr(provider, "configured", False)) or bool(getattr(provider, "public_configured", False))
            if not configured:
                continue
            method = getattr(provider, "fetch", None) if name == "espn" else getattr(provider, "fetch_public", None)
            if not callable(method):
                continue
            try:
                return _with_failures(await method(fixture), failures)
            except Exception as error:
                failures.append({"provider": name, "error": _bounded_error(error)})
        raise RuntimeError("public evidence providers failed: " + "; ".join(item["provider"] for item in failures))

    async def fetch_secondary(self, fixture: dict[str, Any]) -> dict[str, Any]:
        """Refresh from ESPN/public sources without spending API-Football quota."""

        return await self.fetch_public(fixture)


def evidence_needs_enrichment(context: dict[str, Any] | None) -> bool:
    """Identify cached evidence that cannot support a useful recent-form view."""

    if not context:
        return True
    recent = context.get("recent_form") or {}
    home = recent.get("home") or []
    away = recent.get("away") or []
    return len(home) < 3 or len(away) < 3


def should_use_secondary(context: dict[str, Any] | None) -> bool:
    """Use the quota-free refresh only for known provider-backed evidence."""

    source = str((context or {}).get("source") or "")
    return source.startswith("api-football") or source == "thesportsdb-partial"


def localize_evidence_players(context: dict[str, Any]) -> dict[str, Any]:
    """Apply the reviewed Chinese aliases to every player-bearing evidence block."""

    for side in ("home", "away"):
        for player in (context.get("squads") or {}).get(side) or []:
            _localize_player(player)
        for player in (context.get("lineup") or {}).get(f"{side}_players") or []:
            _localize_player(player)
    for player in (context.get("availability") or {}).get("players") or []:
        _localize_player(player)
    return context


def _localize_player(player: dict[str, Any]) -> None:
    original_name = player.get("original_name")
    if original_name:
        player["name"] = to_chinese_player_name(str(original_name))


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
        merged["source"] = f"{previous['source']}+{incoming['source']}"
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
        return len(value) + localized * 2
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
