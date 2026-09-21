"""Normalized coverage rules for men's national-team competitions.

This registry is intentionally separate from ``competition_registry``.  The
existing registry drives the six club-competition capability matrix and its
size is part of the production contract.  National fixtures only need a
source-backed schedule identity, eligibility metadata, and a real competition
logo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


API_FOOTBALL_LOGO_BASE = "https://media.api-sports.io/football/leagues"


@dataclass(frozen=True)
class NationalCompetition:
    key: str
    name: str
    confederation: str
    competition_type: str
    age_group: str = "senior"
    api_football_ids: tuple[int, ...] = ()
    thesportsdb_id: int | None = None
    aliases: tuple[str, ...] = ()
    logo_id: int | None = None

    @property
    def logo_url(self) -> str | None:
        if self.logo_id is None:
            return None
        return f"{API_FOOTBALL_LOGO_BASE}/{self.logo_id}.png"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "confederation": self.confederation,
            "competition_type": self.competition_type,
            "gender": "men",
            "age_group": self.age_group,
            "api_football_ids": list(self.api_football_ids),
            "thesportsdb_id": self.thesportsdb_id,
            "logo_url": self.logo_url,
            "logo_source": "api-football" if self.logo_url else None,
        }


_ITEMS = (
    NationalCompetition(
        "world_cup", "世界杯", "FIFA", "tournament", api_football_ids=(1,), aliases=("world cup", "fifa world cup", "世界杯"), logo_id=1
    ),
    NationalCompetition(
        "world_cup_qualifiers",
        "世界杯预选赛",
        "FIFA",
        "qualifier",
        api_football_ids=(29, 30, 31, 32, 33, 34, 37),
        aliases=("world cup qualifiers", "fifa world cup qualifiers", "世界杯预选赛", "世预赛"),
        logo_id=1,
    ),
    NationalCompetition(
        "international_friendlies",
        "国际友谊赛",
        "国际",
        "friendly",
        api_football_ids=(10,),
        thesportsdb_id=4562,
        aliases=("international friendlies", "international friendly", "friendlies", "国际友谊赛", "友谊赛"),
        logo_id=10,
    ),
    NationalCompetition(
        "asian_cup", "亚洲杯", "AFC", "tournament", api_football_ids=(7,), aliases=("asian cup", "afc asian cup", "亚洲杯"), logo_id=7
    ),
    NationalCompetition(
        "asian_qualifiers",
        "亚洲杯预选赛",
        "AFC",
        "qualifier",
        api_football_ids=(35,),
        thesportsdb_id=5513,
        aliases=("asian cup qualification", "asian qualifiers", "asian qualifying", "亚洲杯预选赛", "亚洲预选赛", "亚洲区预选赛"),
        logo_id=35,
    ),
    NationalCompetition(
        "afc_u23_asian_cup",
        "亚足联U23亚洲杯",
        "AFC",
        "tournament",
        age_group="u23",
        api_football_ids=(532,),
        aliases=("afc u23 asian cup", "u23 asian cup", "亚足联u23亚洲杯", "u23亚洲杯"),
        logo_id=532,
    ),
    NationalCompetition(
        "afc_u23_qualifiers",
        "亚足联U23亚洲杯预选赛",
        "AFC",
        "qualifier",
        age_group="u23",
        api_football_ids=(952,),
        aliases=("afc u23 asian cup qualification", "u23 asian qualifiers", "u23亚洲杯预选赛", "u23亚洲预选赛"),
        logo_id=952,
    ),
    NationalCompetition(
        "asian_games_men",
        "亚运男足",
        "AFC",
        "multi_sport",
        age_group="u23",
        api_football_ids=(803,),
        thesportsdb_id=5501,
        aliases=("asian games", "asian games soccer", "亚运男足", "亚运会男足", "亚运会足球"),
        logo_id=803,
    ),
    NationalCompetition(
        "euro", "欧洲杯", "UEFA", "tournament", api_football_ids=(4,), aliases=("euro", "european championship", "uefa euro", "欧洲杯"), logo_id=4
    ),
    NationalCompetition(
        "euro_qualifiers",
        "欧洲杯预选赛",
        "UEFA",
        "qualifier",
        api_football_ids=(960,),
        aliases=("euro qualification", "euro qualifiers", "european championship qualification", "欧洲杯预选赛"),
        logo_id=4,
    ),
    NationalCompetition(
        "copa_america", "美洲杯", "CONMEBOL", "tournament", api_football_ids=(9,), aliases=("copa america", "美洲杯"), logo_id=9
    ),
    NationalCompetition(
        "africa_cup", "非洲杯", "CAF", "tournament", api_football_ids=(6,), aliases=("africa cup of nations", "afcon", "非洲杯"), logo_id=6
    ),
    NationalCompetition(
        "africa_qualifiers",
        "非洲杯预选赛",
        "CAF",
        "qualifier",
        api_football_ids=(36,),
        aliases=("africa cup of nations qualification", "africa qualifiers", "非洲杯预选赛"),
        logo_id=6,
    ),
    NationalCompetition(
        "nations_league",
        "欧国联",
        "UEFA",
        "league",
        api_football_ids=(5,),
        aliases=("uefa nations league", "nations league", "欧国联", "欧洲国家联赛"),
        logo_id=5,
    ),
)

NATIONAL_COMPETITIONS = {item.key: item for item in _ITEMS}
NATIONAL_COMPETITION_KEYS = tuple(NATIONAL_COMPETITIONS)
NATIONAL_API_ID_TO_KEY = {
    provider_id: item.key
    for item in _ITEMS
    for provider_id in item.api_football_ids
}
NATIONAL_THESPORTSDB_ID_TO_KEY = {
    item.thesportsdb_id: item.key
    for item in _ITEMS
    if item.thesportsdb_id is not None
}
_ALIASES = {
    alias.casefold(): item.key
    for item in _ITEMS
    for alias in (item.key, item.name, *item.aliases)
}

_WOMEN_MARKERS = ("women", "woman", "女足", "女子", "女")
_U23_MARKERS = ("u23", "u-23", "u 23", "23岁以下", "亚运")
_U20_MARKERS = ("u20", "u-20", "u 20", "20岁以下")
_EXCLUDED_MARKERS = ("gold cup", "金杯赛", "ofc nations cup", "oceania cup", "大洋洲杯")


def national_competition(value: Any) -> NationalCompetition | None:
    raw = str(value or "").strip().casefold()
    return NATIONAL_COMPETITIONS.get(_ALIASES.get(raw, raw))


def national_competition_from_api_id(value: Any) -> NationalCompetition | None:
    try:
        return NATIONAL_COMPETITIONS.get(NATIONAL_API_ID_TO_KEY.get(int(value)))
    except (TypeError, ValueError):
        return None


def normalize_national_competition(
    value: Any,
    *,
    area: Any = "",
    gender: Any = "",
    age_group: Any = "",
) -> str | None:
    """Normalize a provider competition only when it matches coverage rules."""

    text = " ".join(str(part or "").strip().casefold() for part in (value, area, gender, age_group))
    if any(marker in text for marker in _WOMEN_MARKERS + _U20_MARKERS + _EXCLUDED_MARKERS):
        return None
    key = _ALIASES.get(str(value or "").strip().casefold())
    if not key:
        return None
    item = NATIONAL_COMPETITIONS[key]
    has_u23_signal = any(marker in text for marker in _U23_MARKERS) or item.age_group == "u23"
    if has_u23_signal and item.age_group != "u23":
        return None
    if item.age_group == "u23" and not any(marker in text for marker in ("asia", "亚洲", "afc", "亚运", "u23", "u-23", "u 23")):
        return None
    return key


def national_metadata(key: Any) -> dict[str, Any] | None:
    item = national_competition(key)
    if item is None:
        return None
    return item.as_dict()
