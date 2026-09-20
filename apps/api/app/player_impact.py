"""Deterministic player contribution and absence-impact model."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .player_identity import link_evidence_players
from .team_names import to_chinese_player_name


RULE_VERSION = "player-impact-rule-v1"


def apply_player_impact(context: dict[str, Any]) -> dict[str, Any]:
    """Attach inspectable player contribution and team retention to evidence."""

    link_evidence_players(context)
    result = {
        side: _team_impact(context, side)
        for side in ("home", "away")
    }
    context["player_impact"] = {
        **result,
        "lineup_confirmed": bool((context.get("lineup") or {}).get("confirmed")),
        "method_version": "player-impact-v1",
    }
    return context


def persist_player_impact_rules(
    repository: Any,
    fixture: Mapping[str, Any],
    context: dict[str, Any],
    *,
    cutoff_at: Any | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist cutoff-safe absence rules from already sourced player evidence."""

    apply_player_impact(context)
    generated_at = (created_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    cutoff = _as_utc(cutoff_at) or generated_at
    reasons: dict[str, int] = {}
    if generated_at - cutoff > timedelta(minutes=5):
        return _rule_report(0, 0, 0, {"historical_generation_blocked": 1})

    availability = context.get("availability") if isinstance(context.get("availability"), Mapping) else {}
    availability_at = _latest_timestamp(
        availability.get("updated_at"),
        availability.get("checked_at"),
    )
    availability_rows = [
        row for row in availability.get("players") or [] if isinstance(row, Mapping)
    ]
    availability_by_id: dict[str, Mapping[str, Any]] = {}
    for row in availability_rows:
        for value in _player_identifiers(row):
            availability_by_id.setdefault(value, row)

    candidates: list[tuple[str, str, Mapping[str, Any], Mapping[str, Any]]] = []
    squads = context.get("squads") if isinstance(context.get("squads"), Mapping) else {}
    for side in ("home", "away"):
        team_id = _fixture_team_id(fixture, side)
        for player in squads.get(side) or []:
            if not isinstance(player, Mapping) or player.get("is_available") is not False:
                continue
            player_id = next(iter(_player_identifiers(player)), "")
            availability_row = next(
                (availability_by_id[value] for value in _player_identifiers(player) if value in availability_by_id),
                None,
            )
            if not player_id or availability_row is None:
                _increment(reasons, "unresolved_absence_identity")
                continue
            candidates.append((side, team_id, player, availability_row))

    existing_reader = getattr(repository, "player_impact_rules", None)
    existing_rules = (
        existing_reader(
            player_ids=[next(iter(_player_identifiers(player)), "") for _, _, player, _ in candidates],
            status=None,
        )
        if callable(existing_reader) and candidates
        else []
    )
    existing_by_id = {str(item.get("id") or ""): item for item in existing_rules}
    saver = getattr(repository, "save_player_impact_rule", None)
    if not callable(saver):
        raise RuntimeError("repository does not support player impact rules")

    generated = 0
    reused = 0
    skipped = 0
    fixture_id = str(fixture.get("id") or "")
    for side, team_id, player, availability_row in candidates:
        player_id = next(iter(_player_identifiers(player)), "")
        statistics = player.get("statistics") if isinstance(player.get("statistics"), Mapping) else {}
        statistics_at = _as_utc(player.get("statistics_synced_at"))
        statistics_id = str(player.get("statistics_snapshot_id") or "")
        if not statistics or statistics_at is None or not statistics_id:
            skipped += 1
            _increment(reasons, "player_statistics_unavailable")
            continue
        if availability_at is None:
            skipped += 1
            _increment(reasons, "availability_timestamp_unavailable")
            continue
        source_available_at = max(statistics_at, availability_at)
        if source_available_at > cutoff:
            skipped += 1
            _increment(reasons, "source_after_cutoff")
            continue
        impact = float(player.get("absence_impact") or 0)
        if impact <= 0:
            skipped += 1
            _increment(reasons, "absence_impact_unavailable")
            continue

        display_name = to_chinese_player_name(str(player.get("name") or availability_row.get("name") or "未知球员"))
        availability_record_id = "availability:" + hashlib.sha256(
            _stable(
                {
                    "fixture_id": fixture_id,
                    "player_id": player_id,
                    "available_at": availability_at.isoformat(),
                    "row": dict(availability_row),
                }
            ).encode()
        ).hexdigest()[:24]
        identity = {
            "fixture_id": fixture_id,
            "team_id": team_id,
            "side": side,
            "player_id": player_id,
            "impact_type": "absence",
            "impact_value": round(-impact, 6),
            "statistics_snapshot_id": statistics_id,
            "availability_record_id": availability_record_id,
            "source_available_at": source_available_at.isoformat(),
            "rule_version": RULE_VERSION,
        }
        rule_id = "impact:" + hashlib.sha256(_stable(identity).encode()).hexdigest()[:32]
        if rule_id in existing_by_id:
            reused += 1
            continue
        rule = {
            "id": rule_id,
            "player_id": player_id,
            "display_name": display_name,
            "team_id": team_id,
            "fixture_id": fixture_id,
            "side": side,
            "role": str(player.get("player_role") or player.get("position_group") or "unknown"),
            "impact_type": "absence",
            "impact_value": identity["impact_value"],
            "confidence": 0.9,
            "source": "player-stats+availability",
            "source_record_ids": [statistics_id, availability_record_id],
            "source_timestamps": {
                "player_statistics": statistics_at.isoformat(),
                "availability": availability_at.isoformat(),
            },
            "available_at": source_available_at.isoformat(),
            "rule_version": RULE_VERSION,
            "status": "active",
            "created_at": generated_at.isoformat(),
            "deprecated_at": None,
            "inputs": {
                "position_group": player.get("position_group"),
                "expected_minutes": player.get("expected_minutes"),
                "attack_contribution": player.get("attack_contribution"),
                "defense_contribution": player.get("defense_contribution"),
                "replacement_contribution": player.get("replacement_contribution"),
                "absence_reason": availability_row.get("reason"),
            },
        }
        saver(rule)
        existing_by_id[rule_id] = rule
        generated += 1

    return _rule_report(generated, reused, skipped, reasons)


def _rule_report(generated: int, reused: int, skipped: int, reasons: dict[str, int]) -> dict[str, Any]:
    return {
        "status": "ok" if generated or reused else "insufficient_data",
        "generated_count": generated,
        "reused_count": reused,
        "skipped_count": skipped,
        "reason_counts": dict(sorted(reasons.items())),
        "item_count": generated,
        "rule_version": RULE_VERSION,
    }


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _latest_timestamp(*values: Any) -> datetime | None:
    parsed = [item for value in values if (item := _as_utc(value)) is not None]
    return max(parsed) if parsed else None


def _player_identifiers(player: Mapping[str, Any]) -> list[str]:
    return [
        str(value)
        for key in ("canonical_player_id", "provider_player_id", "player_id", "id")
        if (value := player.get(key)) not in (None, "")
    ]


def _fixture_team_id(fixture: Mapping[str, Any], side: str) -> str:
    team = fixture.get(f"{side}_team")
    if not isinstance(team, Mapping):
        return ""
    for key in ("canonical_team_id", "provider_id", "id", "team_id", "code"):
        if team.get(key) not in (None, ""):
            return str(team[key])
    return ""


def _team_impact(context: dict[str, Any], side: str) -> dict[str, Any]:
    squad = (context.get("squads") or {}).get(side) or []
    lineup = context.get("lineup") or {}
    lineup_rows = lineup.get(f"{side}_players") or []
    lineup_by_id = {
        row.get("canonical_player_id"): row
        for row in lineup_rows
        if row.get("canonical_player_id")
    }
    absent_ids = {
        row.get("canonical_player_id")
        for row in (context.get("availability") or {}).get("players") or []
        if row.get("team") == side and row.get("canonical_player_id")
    }
    confirmed = bool(lineup.get("confirmed"))

    for player in squad:
        stats = _normalized_statistics(player.get("statistics"))
        if stats and not isinstance(player.get("statistics"), Mapping):
            player["statistics"] = stats
        appearances = _number(stats.get("appearances"), 0)
        substitute_appearances = _number(stats.get("substitute_appearances"), 0)
        observed_starts = _optional_number(stats.get("starts"))
        starts = observed_starts if observed_starts is not None else max(0.0, appearances - substitute_appearances)
        observed_minutes = _optional_number(stats.get("minutes"))
        minutes = observed_minutes if observed_minutes is not None else _estimated_minutes(starts, substitute_appearances)
        lineup_row = lineup_by_id.get(player.get("canonical_player_id"))
        start_probability = _start_probability(confirmed, lineup_row, appearances, starts)
        expected_minutes = _expected_minutes(confirmed, lineup_row, start_probability)
        goals_per90 = _per90(stats.get("goals"), minutes)
        assists_per90 = _per90(stats.get("assists"), minutes)
        recent_rating = _optional_number(stats.get("recent_rating") or stats.get("rating"))
        position_group = _position_group(player)
        attack = _attack_contribution(
            position_group, expected_minutes, start_probability, goals_per90, assists_per90, recent_rating
        )
        defense = _defense_contribution(position_group, expected_minutes, start_probability, stats, minutes)
        player.update(
            {
                "position_group": position_group,
                "expected_start_probability": round(start_probability, 4),
                "expected_minutes": round(expected_minutes, 1),
                "appearances": int(appearances),
                "starts": int(starts),
                "minutes": int(minutes),
                "minutes_status": "observed" if observed_minutes is not None else "estimated",
                "goals_per90": round(goals_per90, 3) if goals_per90 is not None else None,
                "assists_per90": round(assists_per90, 3) if assists_per90 is not None else None,
                "attack_contribution": round(attack, 4),
                "defense_contribution": round(defense, 4),
                "recent_performance": round(recent_rating, 2) if recent_rating is not None else None,
                "is_available": player.get("canonical_player_id") not in absent_ids,
            }
        )

    ranked = sorted(squad, key=_role_score, reverse=True)
    star_slots = max(1, min(3, round(len(ranked) * 0.1))) if ranked else 0
    for index, player in enumerate(ranked):
        player["player_role"] = _player_role(player, index < star_slots)

    available = [player for player in squad if player.get("is_available")]
    absent = [player for player in squad if not player.get("is_available")]
    for player in absent:
        replacement = _replacement_for(player, available)
        replacement_value = _replacement_value(player, replacement)
        player["replacement_contribution"] = round(replacement_value, 4)
        player["absence_impact"] = round(max(0.0, _total_contribution(player) - replacement_value), 4)
        player["expected_replacement"] = _player_summary(replacement) if replacement else None
    for player in available:
        player["replacement_contribution"] = None
        player["absence_impact"] = 0.0

    availability_rows = (context.get("availability") or {}).get("players") or []
    squad_by_id = {player.get("canonical_player_id"): player for player in squad}
    for row in availability_rows:
        if row.get("team") != side:
            continue
        matched = squad_by_id.get(row.get("canonical_player_id"))
        if matched:
            for field in (
                "player_role",
                "expected_start_probability",
                "expected_minutes",
                "appearances",
                "starts",
                "minutes",
                "minutes_status",
                "goals_per90",
                "assists_per90",
                "attack_contribution",
                "defense_contribution",
                "replacement_contribution",
                "absence_impact",
                "expected_replacement",
            ):
                row[field] = matched.get(field)

    eligible_available = [
        player
        for player in ranked
        if player.get("is_available") and player.get("player_role") in {"明星球员", "关键主力"}
    ]
    prioritized_available = [
        *[player for player in eligible_available if player.get("player_role") == "明星球员"],
        *[player for player in eligible_available if player.get("position_group") == "attack"],
        *eligible_available,
    ]
    key_available: list[dict[str, Any]] = []
    seen_available: set[str] = set()
    for player in prioritized_available:
        identity = str(player.get("canonical_player_id") or player.get("provider_player_id") or player.get("name"))
        if identity in seen_available:
            continue
        seen_available.add(identity)
        key_available.append(player)
        if len(key_available) == 6:
            break
    key_absent = sorted(absent, key=lambda item: item.get("absence_impact") or 0, reverse=True)[:4]
    replacements = [
        {
            "absent_player": _player_summary(player),
            "replacement": player.get("expected_replacement"),
            "replacement_contribution": player.get("replacement_contribution"),
            "absence_impact": player.get("absence_impact"),
        }
        for player in key_absent
    ]
    retention = _retention(squad, available)
    observed = sum(1 for player in squad if player.get("minutes_status") == "observed")
    return {
        "data_status": "insufficient" if not squad else "complete" if observed >= max(8, len(squad) // 2) else "partial",
        "squad_count": len(squad),
        "resolved_absence_count": len(absent),
        "unresolved_absence_count": sum(
            1
            for row in availability_rows
            if row.get("team") == side and row.get("identity_status") == "unresolved"
        ),
        "key_available_players": [_player_summary(player) for player in key_available],
        "key_absent_players": [_player_summary(player, include_absence=True) for player in key_absent],
        "expected_replacements": replacements,
        **retention,
    }


def _normalized_statistics(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, list):
        return {}
    aliases = {
        "出场": "appearances",
        "首发": "starts",
        "替补": "substitute_appearances",
        "分钟": "minutes",
        "进球": "goals",
        "助攻": "assists",
        "扑救": "saves",
        "评分": "rating",
    }
    normalized: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        for key, raw in item.items():
            canonical = aliases.get(str(key).strip())
            if canonical and raw not in (None, ""):
                normalized[canonical] = raw
    return normalized


def _start_probability(
    confirmed: bool,
    lineup_row: dict[str, Any] | None,
    appearances: float,
    starts: float,
) -> float:
    if confirmed:
        if not lineup_row:
            return 0.0
        return 1.0 if lineup_row.get("starter") else 0.0
    if appearances > 0:
        return _clamp(starts / appearances, 0.05, 0.95)
    return 0.2


def _expected_minutes(confirmed: bool, lineup_row: dict[str, Any] | None, probability: float) -> float:
    if confirmed:
        if not lineup_row:
            return 0.0
        return 82.0 if lineup_row.get("starter") else 18.0
    return probability * 78.0 + (1 - probability) * 16.0


def _estimated_minutes(starts: float, substitute_appearances: float) -> float:
    return starts * 75.0 + substitute_appearances * 22.0


def _per90(value: Any, minutes: float) -> float | None:
    number = _optional_number(value)
    return number * 90 / minutes if number is not None and minutes > 0 else None


def _attack_contribution(
    position: str,
    expected_minutes: float,
    start_probability: float,
    goals_per90: float | None,
    assists_per90: float | None,
    recent_rating: float | None,
) -> float:
    base = {"goalkeeper": 0.01, "defense": 0.05, "midfield": 0.14, "attack": 0.24}[position]
    minutes_weight = expected_minutes / 90
    production = min(0.5, (goals_per90 or 0) * 0.42 + (assists_per90 or 0) * 0.3)
    recent = _rating_bonus(recent_rating)
    return (base + production + recent) * minutes_weight * (0.65 + 0.35 * start_probability)


def _defense_contribution(
    position: str,
    expected_minutes: float,
    start_probability: float,
    stats: dict[str, Any],
    minutes: float,
) -> float:
    base = {"goalkeeper": 0.34, "defense": 0.22, "midfield": 0.1, "attack": 0.03}[position]
    minutes_weight = expected_minutes / 90
    saves_per90 = _per90(stats.get("saves"), minutes) or 0
    goalkeeper_bonus = min(0.16, saves_per90 * 0.025) if position == "goalkeeper" else 0
    return (base + goalkeeper_bonus) * minutes_weight * (0.65 + 0.35 * start_probability)


def _rating_bonus(rating: float | None) -> float:
    if rating is None:
        return 0.0
    return _clamp((rating - 6.5) * 0.04, -0.03, 0.08)


def _player_role(player: dict[str, Any], star_candidate: bool) -> str:
    if star_candidate and player.get("expected_minutes", 0) >= 55 and _total_contribution(player) >= 0.18:
        return "明星球员"
    if player.get("expected_start_probability", 0) >= 0.65 or player.get("expected_minutes", 0) >= 58:
        return "关键主力"
    if player.get("expected_minutes", 0) >= 22:
        return "轮换球员"
    return "边缘球员"


def _role_score(player: dict[str, Any]) -> float:
    recent = _rating_bonus(_optional_number(player.get("recent_performance")))
    return _total_contribution(player) + player.get("expected_minutes", 0) / 90 * 0.22 + recent


def _replacement_for(player: dict[str, Any], available: list[dict[str, Any]]) -> dict[str, Any] | None:
    same_position = [item for item in available if item.get("position_group") == player.get("position_group")]
    candidates = same_position or available
    return max(candidates, key=_role_score, default=None)


def _replacement_value(player: dict[str, Any], replacement: dict[str, Any] | None) -> float:
    if not replacement:
        return 0.0
    minutes_ratio = min(1.0, (player.get("expected_minutes") or 0) / max(1.0, replacement.get("expected_minutes") or 1))
    return min(_total_contribution(player) * 0.85, _total_contribution(replacement) * minutes_ratio * 0.7)


def _retention(squad: list[dict[str, Any]], available: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "attack_retention": _capacity_ratio(squad, available, "attack_contribution", 4),
        "defense_retention": _capacity_ratio(squad, available, "defense_contribution", 5),
        "midfield_retention": _capacity_ratio(
            [item for item in squad if item.get("position_group") == "midfield"],
            [item for item in available if item.get("position_group") == "midfield"],
            None,
            4,
        ),
        "goalkeeper_retention": _capacity_ratio(
            [item for item in squad if item.get("position_group") == "goalkeeper"],
            [item for item in available if item.get("position_group") == "goalkeeper"],
            "defense_contribution",
            1,
        ),
    }


def _capacity_ratio(
    reference: list[dict[str, Any]],
    available: list[dict[str, Any]],
    field: str | None,
    slots: int,
) -> float:
    def value(player: dict[str, Any]) -> float:
        return float(player.get(field) or 0) if field else _total_contribution(player)

    denominator = sum(sorted((value(item) for item in reference), reverse=True)[:slots])
    numerator = sum(sorted((value(item) for item in available), reverse=True)[:slots])
    if denominator <= 0:
        return 1.0
    return round(_clamp(numerator / denominator, 0.0, 1.0), 4)


def _position_group(player: dict[str, Any]) -> str:
    value = str(player.get("position_code") or player.get("position") or "").casefold()
    if value in {"g", "gk"} or "goal" in value or "门将" in value:
        return "goalkeeper"
    if value in {"d", "df"} or "def" in value or "后卫" in value:
        return "defense"
    if value in {"m", "mf"} or "mid" in value or "中场" in value:
        return "midfield"
    return "attack"


def _player_summary(player: dict[str, Any] | None, include_absence: bool = False) -> dict[str, Any] | None:
    if not player:
        return None
    fields = (
        "canonical_player_id",
        "provider_player_id",
        "name",
        "name_status",
        "name_source",
        "position",
        "position_group",
        "player_role",
        "expected_start_probability",
        "expected_minutes",
        "attack_contribution",
        "defense_contribution",
        "market_value_eur",
        "market_value_source",
        "market_value_as_of",
    )
    result = {field: player.get(field) for field in fields}
    if include_absence:
        result.update(
            {
                "replacement_contribution": player.get("replacement_contribution"),
                "absence_impact": player.get("absence_impact"),
                "expected_replacement": player.get("expected_replacement"),
            }
        )
    return result


def _total_contribution(player: dict[str, Any]) -> float:
    return float(player.get("attack_contribution") or 0) + float(player.get("defense_contribution") or 0)


def _number(value: Any, default: float) -> float:
    parsed = _optional_number(value)
    return parsed if parsed is not None else default


def _optional_number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
