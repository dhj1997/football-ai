"""Per-match discipline (cards) ingestion and pre-match discipline evidence.

API-Football card events are backfilled onto finished fixtures (``discipline``
payload field, sides attributed by canonical team names). Pre-match evidence
reports each side's most recent finished match before the prediction cutoff —
facts only (how many cards, who was sent off); whether that forces a
suspension is left to the reader, since booking rules differ per competition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .fixture_matching import canonical, find_fixture_rows
from .historical_validation import parse_timestamp
from .recent_form import result_available_at
from .team_names import to_chinese_team_name

DISCIPLINE_LEAGUES: tuple[str, ...] = ("epl", "laliga", "csl", "cfa_cup")
# 源上暂缺的每场只按天重试，避免耗尽每日 API 配额。
RETRY_AFTER = timedelta(hours=24)
_RED_DETAILS = {"red card", "second yellow card", "second yellow"}


async def sync_discipline(
    repository: Any,
    provider: Any,
    *,
    leagues: tuple[str, ...] = DISCIPLINE_LEAGUES,
    limit: int = 25,
    localize: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backfill card events for up to ``limit`` finished fixtures per run."""

    localize = localize or _identity
    current = now or datetime.now(UTC)
    rows = repository.list_fixtures() or []
    pending = _pending_rows(rows, leagues, current)
    enriched = 0
    unavailable = 0
    failed = 0
    rows_written = 0
    now_iso = current.replace(microsecond=0).isoformat()
    for row in pending[: max(0, int(limit))]:
        external_id = row["external_ids"]["api_football"]
        try:
            payload = await provider.fixture_events(external_id)
        except Exception:
            failed += 1
            continue
        if not payload:
            merged = dict(row)
            merged["discipline_unavailable_at"] = now_iso
            repository.upsert_fixture(merged, synced_at=now_iso)
            unavailable += 1
            continue
        discipline = _attribute_sides(row, payload["cards"], localize, current)
        score = row.get("score") if isinstance(row.get("score"), dict) else {}
        siblings = find_fixture_rows(
            rows,
            kickoff=row.get("kickoff"),
            home_title=str((row.get("home_team") or {}).get("name") or ""),
            away_title=str((row.get("away_team") or {}).get("name") or ""),
            localize=localize,
            home_goals=score.get("home"),
            away_goals=score.get("away"),
        )
        targets = {str(s["id"]): s for s in siblings} or {str(row["id"]): row}
        for target in targets.values():
            merged = dict(target)
            merged["discipline"] = discipline
            repository.upsert_fixture(merged, synced_at=now_iso)
            rows_written += 1
        enriched += 1
    return {
        "status": "completed",
        "pending": len(pending),
        "enriched": enriched,
        "unavailable": unavailable,
        "failed": failed,
        "rows_written": rows_written,
        "item_count": enriched,
    }


def attach_discipline(
    repository: Any,
    fixture: Mapping,
    context: dict[str, Any],
    prediction_timestamp: Any = None,
) -> None:
    """Expose each side's latest finished match before the cutoff."""

    cutoff = parse_timestamp(prediction_timestamp) or datetime.now(UTC)
    rows = _rows(repository)
    target_key = _match_key(fixture)
    sides: dict[str, Any] = {}
    for side, team_key in _side_keys(fixture).items():
        latest = _latest_disciplined_match(rows, team_key, cutoff, str(target_key))
        if latest is None:
            sides[side] = None
            continue
        discipline = latest.get("discipline") if isinstance(latest.get("discipline"), dict) else {}
        # 该球队在源比赛里的实际主客归属可能与目标比赛不同
        side_in_match = _team_side_in_match(latest, team_key)
        side_data = discipline.get(side_in_match) if isinstance(discipline.get(side_in_match), dict) else {}
        sides[side] = {
            "last_match_kickoff": latest.get("kickoff"),
            "yellow_cards": side_data.get("yellow_cards"),
            "red_cards": side_data.get("red_cards"),
            "red_card_players": side_data.get("red_card_players") or [],
        }
    if all(value is None for value in sides.values()):
        return
    context["discipline"] = {
        "home": sides.get("home"),
        "away": sides.get("away"),
        "note": "上场红黄牌为事实记录；是否构成停赛由联赛规则决定",
        "source": "api-football",
    }


def _pending_rows(rows: list[dict[str, Any]], leagues: tuple[str, ...], current: datetime) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("league_key") or "") not in leagues:
            continue
        if row.get("status") != "finished":
            continue
        if isinstance(row.get("discipline"), dict) and row.get("discipline"):
            continue
        attempted = parse_timestamp(row.get("discipline_unavailable_at"))
        if attempted is not None and current - attempted < RETRY_AFTER:
            continue
        external_id = (row.get("external_ids") or {}).get("api_football")
        if not external_id:
            continue
        pending.append(row)
    pending.sort(key=lambda row: str(row.get("kickoff") or ""), reverse=True)
    return pending


def _attribute_sides(row: Mapping, cards: list[dict], localize: Any, current: datetime) -> dict[str, Any]:
    home_key = canonical(str((row.get("home_team") or {}).get("name") or ""), localize)
    away_key = canonical(str((row.get("away_team") or {}).get("name") or ""), localize)
    sides = {
        "home": {"yellow_cards": 0, "red_cards": 0, "red_card_players": []},
        "away": {"yellow_cards": 0, "red_cards": 0, "red_card_players": []},
    }
    for card in cards:
        team_key = canonical(str(card.get("team") or ""), localize)
        if home_key and team_key == home_key:
            side = "home"
        elif away_key and team_key == away_key:
            side = "away"
        else:
            continue
        detail = str(card.get("detail") or "").strip().casefold()
        if detail in _RED_DETAILS:
            sides[side]["red_cards"] += 1
            if card.get("player"):
                sides[side]["red_card_players"].append(str(card["player"]))
        else:
            sides[side]["yellow_cards"] += 1
    known_at = result_available_at(row)
    sides["available_at"] = (known_at or (current.replace(microsecond=0))).isoformat()
    sides["source"] = "api-football"
    return sides


def _team_side_in_match(row: Mapping, team_key: str) -> str:
    home = row.get("home_team") if isinstance(row.get("home_team"), dict) else {}
    home_key = canonical(str(home.get("name") or ""), to_chinese_team_name)
    return "home" if team_key == home_key else "away"


def _latest_disciplined_match(
    rows: list[dict[str, Any]],
    team_key: str,
    cutoff: datetime,
    target_key: str,
) -> dict[str, Any] | None:
    best: tuple[str, dict[str, Any]] | None = None
    for row in rows:
        if row.get("status") != "finished":
            continue
        if str(row.get("canonical_fixture_id") or row.get("id") or "") == target_key:
            continue
        available = result_available_at(row)
        if available is None or available > cutoff:
            continue
        if not isinstance(row.get("discipline"), dict) or not row.get("discipline"):
            continue
        if team_key not in _row_team_keys(row):
            continue
        kickoff = str(row.get("kickoff") or "")
        if best is None or kickoff > best[0]:
            best = (kickoff, row)
    return best[1] if best else None


def _row_team_keys(row: Mapping) -> set[str]:
    keys = set()
    for side in ("home_team", "away_team"):
        team = row.get(side) if isinstance(row.get(side), dict) else {}
        for field in ("name", "original_name"):
            key = canonical(str(team.get(field) or ""), to_chinese_team_name)
            if key:
                keys.add(key)
    return keys


def _side_keys(fixture: Mapping) -> dict[str, str]:
    result: dict[str, str] = {}
    for side in ("home", "away"):
        team = fixture.get(f"{side}_team") if isinstance(fixture.get(f"{side}_team"), dict) else {}
        key = canonical(str(team.get("name") or ""), to_chinese_team_name)
        if key:
            result[side] = key
    return result


def _match_key(fixture: Mapping) -> str:
    return str(fixture.get("canonical_fixture_id") or fixture.get("id") or "")


def _rows(repository: Any) -> list[dict[str, Any]]:
    reader = getattr(repository, "list_fixtures", None)
    return list(reader()) if callable(reader) else []


def _identity(value: str) -> str:
    return str(value or "")
