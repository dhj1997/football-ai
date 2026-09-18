"""P9 Competition Registry: six-competition domain with capability matrix.

The registry is the single source of truth for which competitions the
platform covers and which capabilities are actually implemented for each
one. A capability status is a statement about current, real support —
never an aspiration. ``unknown`` and ``unavailable`` must never be treated
as ``supported`` by callers (ADR-008, ADR-010).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

CAPABILITIES: tuple[str, ...] = (
    "fixture",
    "standings",
    "stage",
    "team",
    "lineup",
    "injury",
    "odds",
    "historical",
    "prediction",
    "evaluation",
)
CAPABILITY_STATUSES: tuple[str, ...] = ("supported", "partial", "unavailable", "unknown")
COMPETITION_TYPES: tuple[str, ...] = ("league", "knockout", "continental")
SEASON_POLICIES: tuple[str, ...] = ("calendar_year", "fall_spring")

# Capability values below reflect what the current provider adapters and
# historical pipeline actually serve. P5 history and P6/P7 evaluation exist
# only for CSL/EPL/LAL; the cup/continental competitions are fixture-only.
_CAPABILITIES_THREE_LEAGUES: dict[str, str] = {
    "fixture": "supported",
    "standings": "supported",
    "stage": "partial",
    "team": "supported",
    "lineup": "partial",
    "injury": "partial",
    "odds": "partial",
    "historical": "supported",
    "prediction": "supported",
    "evaluation": "supported",
}
_CAPABILITIES_FIXTURE_ONLY: dict[str, str] = {
    "fixture": "supported",
    "standings": "unavailable",
    "stage": "partial",
    "team": "unavailable",
    "lineup": "unavailable",
    "injury": "unavailable",
    "odds": "partial",
    "historical": "unavailable",
    "prediction": "unavailable",
    "evaluation": "unavailable",
}
_UNAVAILABLE_STANDINGS_REASON = {
    "cfa_cup": "knockout competition has no standings table",
    "ucl": "no configured provider serves group standings",
    "acl": "no configured provider serves group standings",
}


class CapabilityGateError(RuntimeError):
    """Raised when a caller requests a capability a competition lacks."""


@dataclass(frozen=True)
class CompetitionDefinition:
    """One competition in the six-competition domain."""

    key: str
    name: str
    mark: str
    competition_type: str
    season_policy: str
    capabilities: Mapping[str, str]
    capability_notes: Mapping[str, str]
    provider_keys: Mapping[str, str | None]

    def capability_status(self, capability: str) -> str:
        return self.capabilities.get(capability, "unknown")

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "mark": self.mark,
            "competition_type": self.competition_type,
            "season_policy": self.season_policy,
            "capabilities": dict(self.capabilities),
            "capability_notes": dict(self.capability_notes),
            "provider_keys": dict(self.provider_keys),
        }


def _definition(
    key: str,
    name: str,
    mark: str,
    competition_type: str,
    season_policy: str,
    *,
    fixture_only: bool,
    provider_keys: dict[str, str | None],
) -> CompetitionDefinition:
    capabilities = dict(_CAPABILITIES_FIXTURE_ONLY if fixture_only else _CAPABILITIES_THREE_LEAGUES)
    notes: dict[str, str] = {}
    if key in _UNAVAILABLE_STANDINGS_REASON:
        notes["standings"] = _UNAVAILABLE_STANDINGS_REASON[key]
    if competition_type in {"knockout", "continental"}:
        notes["stage"] = "round/stage normalized when a provider supplies it; leg and aggregate not populated yet"
    return CompetitionDefinition(
        key=key,
        name=name,
        mark=mark,
        competition_type=competition_type,
        season_policy=season_policy,
        capabilities=capabilities,
        capability_notes=notes,
        provider_keys=provider_keys,
    )


_CSL = _definition(
    "csl", "中国足球超级联赛", "CSL", "league", "calendar_year",
    fixture_only=False,
    provider_keys={"api-football": "csl", "thesportsdb": "csl", "espn": "csl", "dongqiudi": "csl"},
)
_EPL = _definition(
    "epl", "英格兰足球超级联赛", "PL", "league", "fall_spring",
    fixture_only=False,
    provider_keys={"api-football": "epl", "thesportsdb": "epl", "espn": "epl", "dongqiudi": "epl"},
)
_LALIGA = _definition(
    "laliga", "西班牙足球甲级联赛", "LL", "league", "fall_spring",
    fixture_only=False,
    provider_keys={"api-football": "laliga", "thesportsdb": "laliga", "espn": "laliga", "dongqiudi": "laliga"},
)
_CFA_CUP = _definition(
    "cfa_cup", "中国足协杯", "CFA", "knockout", "calendar_year",
    fixture_only=True,
    provider_keys={"api-football": "cfa_cup", "thesportsdb": "cfa_cup", "espn": None, "dongqiudi": "cfa_cup"},
)
_UCL = _definition(
    "ucl", "欧洲冠军联赛", "UCL", "continental", "fall_spring",
    fixture_only=True,
    provider_keys={"api-football": None, "thesportsdb": "ucl", "espn": None, "dongqiudi": "ucl"},
)
_ACL = _definition(
    "acl", "亚冠精英联赛", "ACL", "continental", "fall_spring",
    fixture_only=True,
    provider_keys={"api-football": None, "thesportsdb": None, "espn": None, "dongqiudi": "acl"},
)

_DEFINITIONS: tuple[CompetitionDefinition, ...] = (_CSL, _EPL, _LALIGA, _CFA_CUP, _UCL, _ACL)

# One alias table unifying the three historical vocabularies: browse keys,
# P5 uppercase codes (CSL/EPL/LAL) and common provider labels.
_ALIASES: dict[str, str] = {
    "csl": "csl",
    "中超": "csl",
    "chinese super league": "csl",
    "chinese-super-league": "csl",
    "169": "csl",
    "epl": "epl",
    "英超": "epl",
    "premier league": "epl",
    "english premier league": "epl",
    "39": "epl",
    "lal": "laliga",
    "laliga": "laliga",
    "西甲": "laliga",
    "la liga": "laliga",
    "primera division": "laliga",
    "spanish laliga": "laliga",
    "140": "laliga",
    "cfa_cup": "cfa_cup",
    "cfa cup": "cfa_cup",
    "足协杯": "cfa_cup",
    "中国足协杯": "cfa_cup",
    "china fa cup": "cfa_cup",
    "171": "cfa_cup",
    "ucl": "ucl",
    "欧冠": "ucl",
    "uefa champions league": "ucl",
    "champions league": "ucl",
    "4480": "ucl",
    "acl": "acl",
    "亚冠": "acl",
    "亚冠精英": "acl",
    "亚冠精英联赛": "acl",
    "亚冠二级": "acl",
    "亚冠二级联赛": "acl",
    "afc champions league 2": "acl",
    "afc champions league": "acl",
}


def normalize_competition_key(value: Any) -> str | None:
    """Map every historical league vocabulary onto the six-competition keys."""

    raw = str(value or "").strip().casefold()
    if not raw:
        return None
    return _ALIASES.get(raw)


def season_for(competition_key: Any, on_date: date) -> int:
    """Return the provider season year for a competition and calendar date.

    CSL and the CFA Cup run inside one calendar year; the other four use a
    fall-spring season split in July, matching ApiFootballProvider.season_for.
    """

    definition = COMPETITION_REGISTRY.get(competition_key)
    policy = definition.season_policy if definition else "fall_spring"
    if policy == "calendar_year":
        return on_date.year
    return on_date.year if on_date.month >= 7 else on_date.year - 1


class CompetitionRegistry:
    """Lookup and capability gating for the six-competition domain."""

    def __init__(self, definitions: tuple[CompetitionDefinition, ...] = _DEFINITIONS) -> None:
        self._items: dict[str, CompetitionDefinition] = {item.key: item for item in definitions}

    def definitions(self) -> tuple[CompetitionDefinition, ...]:
        return tuple(self._items[key] for key in self._items)

    def get(self, key: Any) -> CompetitionDefinition | None:
        raw = str(key or "").strip()
        normalized = normalize_competition_key(raw)
        if normalized:
            return self._items.get(normalized)
        # Custom registries may use keys outside the shared alias table.
        return self._items.get(raw.casefold())

    def capability_status(self, key: Any, capability: str) -> str | None:
        definition = self.get(key)
        if definition is None:
            return None
        return definition.capability_status(capability)

    def require(self, key: Any, capability: str) -> CompetitionDefinition:
        """Return the definition only when the capability is fully supported."""

        definition = self.get(key)
        if definition is None:
            raise CapabilityGateError(f"Unknown competition: {key}")
        status = definition.capability_status(capability)
        if status != "supported":
            raise CapabilityGateError(
                f"Competition {definition.key} does not support capability '{capability}' (status: {status})"
            )
        return definition

    def competitions_with_capability(
        self, capability: str, *, status: str = "supported"
    ) -> list[CompetitionDefinition]:
        return [item for item in self.definitions() if item.capability_status(capability) == status]

    def as_dict(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.definitions()]


COMPETITION_REGISTRY = CompetitionRegistry()
