"""Stable player identity linking and public name sanitization."""

import hashlib
import re
import unicodedata
from copy import deepcopy
from typing import Any

from .team_names import is_reviewed_player_name, to_chinese_player_name


PLAYER_COLLECTION_KEYS = {
    "roster",
    "squad",
    "players",
    "home_players",
    "away_players",
    "key_available_players",
    "key_absent_players",
    "expected_replacements",
}


def link_evidence_players(context: dict[str, Any]) -> dict[str, Any]:
    """Localize players and link availability/lineup rows to squad identities."""

    provider = _provider_from_source(context.get("source"))
    squads = context.setdefault("squads", {})
    indexes: dict[str, dict[str, dict[str, Any]]] = {}
    resolved_count = 0
    unresolved: list[dict[str, str]] = []

    for side in ("home", "away"):
        side_squad = squads.setdefault(side, [])
        for player in side_squad:
            localize_player_record(player, provider)
        indexes[side] = _squad_index(side_squad)

    lineup = context.setdefault("lineup", {})
    for side in ("home", "away"):
        for player in lineup.get(f"{side}_players") or []:
            localize_player_record(player, provider)
            match = _match_player(player, indexes[side])
            if match:
                _merge_identity(player, match)
                resolved_count += 1
            else:
                player["identity_status"] = "unresolved"
                unresolved.append({"team": side, "name": player["name"], "source": "lineup"})

    availability = context.setdefault("availability", {})
    for player in availability.get("players") or []:
        side = str(player.get("team") or "unknown")
        localize_player_record(player, provider)
        match = _match_player(player, indexes.get(side, {}))
        if match:
            _merge_identity(player, match)
            resolved_count += 1
        else:
            player["identity_status"] = "unresolved"
            unresolved.append({"team": side, "name": player["name"], "source": "availability"})

    availability["notes"] = [
        f"{player['name']}：{player.get('reason') or '原因待核验'}"
        for player in availability.get("players") or []
    ]

    availability["unresolved_count"] = sum(
        1 for item in availability.get("players") or [] if item.get("identity_status") == "unresolved"
    )
    context["player_identity"] = {
        "resolved_count": resolved_count,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }
    return context


def localize_player_record(player: dict[str, Any], provider: str = "unknown") -> dict[str, Any]:
    """Apply the reviewed display name and stable identity fields to one player."""

    source_name = str(player.get("original_name") or player.get("name") or "未知球员")
    player.setdefault("original_name", source_name)
    reviewed = is_reviewed_player_name(source_name)
    provider_id = player.get("provider_player_id")
    if provider_id in (None, ""):
        provider_id = player.get("id")
    player["provider_player_id"] = str(provider_id) if provider_id not in (None, "") else None
    reviewed_name = to_chinese_player_name(source_name)
    player["canonical_player_id"] = player.get("canonical_player_id") or _canonical_player_id(
        reviewed_name, provider, player["provider_player_id"], source_name
    )
    machine_name = str(player.get("machine_chinese_name") or "").strip()
    if reviewed:
        player["name"] = reviewed_name
        player["name_status"] = "resolved"
        player["name_source"] = "reviewed_alias"
    elif _contains_chinese(machine_name):
        player["name"] = to_chinese_player_name(machine_name)
        player["name_status"] = "machine_translated"
        player["name_source"] = player.get("machine_name_source") or "machine_translated"
    else:
        player["name"] = to_chinese_player_name(_unresolved_display_name(player))
        player["name_status"] = "unresolved"
        player["name_source"] = "pending_review"
    player.setdefault("identity_status", "resolved" if player["provider_player_id"] else "unresolved")
    return player


def public_payload(value: Any) -> Any:
    """Return a copy without supplier names or internal matching identifiers."""

    return _sanitize(deepcopy(value))


def _sanitize(value: Any, collection_key: str | None = None) -> Any:
    if isinstance(value, list):
        items = []
        for item in value:
            if collection_key in PLAYER_COLLECTION_KEYS and isinstance(item, dict):
                localize_player_record(item)
            items.append(_sanitize(item))
        return items
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"original_name", "transfermarkt_id", "machine_chinese_name", "machine_name_source"}:
            continue
        result[key] = _sanitize(item, key)
    return result


def _squad_index(squad: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for player in squad:
        for key in _identity_keys(player):
            result.setdefault(key, player)
    return result


def _match_player(player: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return next((index[key] for key in _identity_keys(player) if key in index), None)


def _identity_keys(player: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    provider_id = player.get("provider_player_id") or player.get("id")
    if provider_id not in (None, ""):
        keys.append(f"id:{provider_id}")
    canonical_id = player.get("canonical_player_id")
    if canonical_id:
        keys.append(f"canonical:{canonical_id}")
    for name in (player.get("original_name"), player.get("name")):
        normalized = _normalize_name(name)
        if normalized and normalized not in {"unknownplayer", "未知球员", "待核验球员"}:
            keys.append(f"name:{normalized}")
    return keys


def _merge_identity(target: dict[str, Any], squad_player: dict[str, Any]) -> None:
    provider_ids = [
        str(value)
        for value in (target.get("provider_player_id"), squad_player.get("provider_player_id"))
        if value not in (None, "")
    ]
    target["canonical_player_id"] = squad_player["canonical_player_id"]
    target["provider_player_id"] = squad_player.get("provider_player_id")
    target["provider_player_ids"] = list(dict.fromkeys(provider_ids))
    target["identity_status"] = "resolved"
    target["name"] = squad_player["name"]
    target["name_status"] = squad_player.get("name_status", "resolved")
    target["name_source"] = squad_player.get("name_source")
    for field in (
        "position",
        "position_code",
        "age",
        "number",
        "statistics",
        "market_value_eur",
        "market_value",
        "market_value_currency",
        "market_value_source",
        "market_value_as_of",
        "market_value_freshness",
    ):
        if target.get(field) in (None, "", {}, []) and squad_player.get(field) not in (None, "", {}, []):
            target[field] = squad_player[field]


def _canonical_player_id(name: str, provider: str, provider_id: str | None, source_name: str) -> str:
    if name not in {"未知球员", "待核验球员"}:
        seed = f"name:{_normalize_name(name)}"
    elif provider_id:
        seed = f"provider:{provider}:{provider_id}"
    else:
        seed = f"unresolved:{provider}:{_normalize_name(source_name)}"
    return f"player-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _provider_from_source(source: Any) -> str:
    value = str(source or "").casefold()
    if "api-football" in value:
        return "api-football"
    if "espn" in value:
        return "espn"
    if "sportsdb" in value:
        return "thesportsdb"
    return "unknown"


def _unresolved_display_name(player: dict[str, Any]) -> str:
    number = player.get("number")
    stable_seed = str(
        player.get("provider_player_id")
        or player.get("canonical_player_id")
        or player.get("original_name")
        or "unresolved"
    )
    stable_number = int(hashlib.sha256(stable_seed.encode("utf-8")).hexdigest()[:12], 16) % 1_000_000
    position = _position_label(player.get("position") or player.get("position_code"))
    suffix = f" #{number}" if number not in (None, "") else ""
    detail_parts = [part for part in (position, f"编号{stable_number:06d}") if part]
    detail = f"（{'，'.join(detail_parts)}）"
    return f"待核验球员{suffix}{detail}"


def _position_label(value: Any) -> str:
    normalized = str(value or "").casefold()
    if normalized in {"g", "gk"} or "goal" in normalized or "门将" in normalized:
        return "门将"
    if normalized in {"d", "df"} or "def" in normalized or "后卫" in normalized:
        return "后卫"
    if normalized in {"m", "mf"} or "mid" in normalized or "中场" in normalized:
        return "中场"
    if normalized in {"a", "f", "fw"} or "att" in normalized or "forw" in normalized or "前锋" in normalized:
        return "前锋"
    return ""


def _contains_chinese(value: Any) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in str(value or ""))


def _normalize_name(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    latin = re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())
    if latin:
        return latin
    return "".join(character for character in str(value or "") if character.isalnum()).casefold()
