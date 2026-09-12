"""Persistence and cadence policy for Dongqiudi data."""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .data import CHINA_TZ, unavailable_context
from .team_names import to_chinese_player_name, to_chinese_team_name


class DongqiudiSyncService:
    """Keep schedule, team, odds and free pre-match analysis synchronized."""

    def __init__(
        self,
        provider: Any,
        repository: Any,
        lookahead_hours: int = 36,
        prematch_window_minutes: int = 50,
        concurrency: int = 2,
        prematch_lead_hours: int = 24,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.lookahead_hours = max(1, int(lookahead_hours))
        self.prematch_window = timedelta(minutes=max(1, int(prematch_window_minutes)))
        self.prematch_lead = timedelta(hours=max(1, int(prematch_lead_hours)))
        self._semaphore = asyncio.Semaphore(max(1, int(concurrency)))
        self._lock = asyncio.Lock()
        self._team_locks: dict[str, asyncio.Lock] = {}

    @property
    def configured(self) -> bool:
        return bool(getattr(self.provider, "configured", False))

    async def sync_schedule(self, force: bool = False) -> dict[str, Any]:
        """Fetch today's public schedule and enrich newly seen matches once."""

        if not self.configured:
            raise RuntimeError("懂球帝数据源未配置")
        async with self._lock:
            now = datetime.now(UTC)
            start = now.astimezone(CHINA_TZ).date() - timedelta(days=1)
            end = (now + timedelta(hours=self.lookahead_hours)).astimezone(CHINA_TZ).date()
            rows = await self.provider.fixtures(start, end)
            inserted = 0
            for incoming in rows:
                existing = self._find_existing(incoming)
                if existing:
                    incoming = self._merge_fixture(existing, incoming)
                else:
                    inserted += 1
                self.repository.upsert_fixture(incoming)
            enrichment = await self.sync_initial_missing(force=force)
            return {
                "status": "updated",
                "item_count": len(rows),
                "inserted_count": inserted,
                "enriched_count": enrichment["synced_count"],
                "errors": enrichment["errors"],
                "last_synced_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "from": start.isoformat(),
                "to": end.isoformat(),
            }

    async def sync_scores(self) -> dict[str, Any]:
        """Refresh status and scores for existing fixtures from Dongqiudi."""

        if not self.configured:
            raise RuntimeError("懂球帝数据源未配置")
        async with self._lock:
            now = datetime.now(UTC)
            start = now.astimezone(CHINA_TZ).date() - timedelta(days=1)
            end = (now + timedelta(hours=self.lookahead_hours)).astimezone(CHINA_TZ).date()
            rows = await self.provider.fixtures(start, end)
            existing = [
                fixture
                for fixture in self.repository.list_fixtures()
                if self._source_match_id(fixture)
                and start.isoformat() <= str(fixture.get("fixture_date") or "") <= end.isoformat()
            ]
            existing_by_match = {
                self._source_match_id(fixture): fixture
                for fixture in existing
                if self._source_match_id(fixture)
            }
            results_by_match = {
                str(row.get("external_ids", {}).get("dongqiudi")): row
                for row in rows
                if row.get("external_ids", {}).get("dongqiudi")
            }
            detail_errors: list[str] = []
            fetcher = getattr(self.provider, "match_result", None)
            if callable(fetcher):
                details = await asyncio.gather(
                    *(fetcher(self._source_match_id(fixture)) for fixture in existing),
                    return_exceptions=True,
                )
                for fixture, detail in zip(existing, details, strict=True):
                    if isinstance(detail, Exception):
                        detail_errors.append(f"{fixture['id']}: {detail}")
                        continue
                    results_by_match[self._source_match_id(fixture)] = detail
            matched_count = 0
            updated_count = 0
            synced_at = now.replace(microsecond=0).isoformat()
            for incoming in results_by_match.values():
                score = incoming.get("score")
                if incoming.get("status") not in {"live", "finished"} and score is None:
                    continue
                existing = existing_by_match.get(str(incoming.get("match_id"))) or self._find_existing(incoming)
                if not existing:
                    continue
                matched_count += 1
                updated = dict(existing)
                updated["status"] = incoming.get("status") or existing.get("status")
                updated["provider_status"] = incoming.get("provider_status")
                if score is not None:
                    updated["score"] = score
                updated["result_source"] = "dongqiudi"
                updated["result_synced_at"] = synced_at
                if (
                    updated.get("status") != existing.get("status")
                    or updated.get("provider_status") != existing.get("provider_status")
                    or updated.get("score") != existing.get("score")
                ):
                    self.repository.upsert_fixture(updated, synced_at=synced_at)
                    updated_count += 1
            return {
                "status": "updated",
                "source_count": len(rows),
                "matched_count": matched_count,
                "updated_count": updated_count,
                "item_count": updated_count,
                "last_synced_at": synced_at,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "errors": detail_errors[:20],
            }

    async def sync_initial_missing(self, force: bool = False) -> dict[str, Any]:
        fixtures = [item for item in self.repository.list_fixtures() if self._source_match_id(item)]
        results = await asyncio.gather(*(self.sync_match(item["id"], phase="initial", force=force) for item in fixtures if force or not self._state(item).get("initial_synced_at")), return_exceptions=True)
        errors = [str(item) for item in results if isinstance(item, Exception)]
        return {"synced_count": sum(1 for item in results if isinstance(item, dict) and item.get("status") == "synced"), "errors": errors[:20]}

    async def sync_prematch_due(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        due: list[tuple[dict[str, Any], str]] = []
        for fixture in self.repository.list_fixtures():
            match_id = self._source_match_id(fixture)
            kickoff = _as_utc(fixture.get("kickoff"))
            if not match_id or kickoff is None:
                continue
            delta = kickoff - now
            if not timedelta(0) <= delta <= self.prematch_lead:
                continue
            state = self._state(fixture)
            if delta <= self.prematch_window and not state.get("prematch_synced_at"):
                due.append((fixture, "prematch"))
            elif delta > self.prematch_window and not state.get("prematch_24h_synced_at"):
                due.append((fixture, "prematch_24h"))
        results = await asyncio.gather(*(self.sync_match(item["id"], phase=phase) for item, phase in due), return_exceptions=True)
        errors = [str(item) for item in results if isinstance(item, Exception)]
        return {"candidate_count": len(due), "synced_count": sum(1 for item in results if isinstance(item, dict) and item.get("status") == "synced"), "item_count": len(due), "errors": errors[:20]}

    async def sync_match(self, fixture_id: str, phase: str = "manual", force: bool = True) -> dict[str, Any]:
        fixture = self.repository.fixture(fixture_id)
        if not fixture:
            raise ValueError("未找到比赛")
        match_id = self._source_match_id(fixture)
        if not match_id:
            raise ValueError("比赛没有懂球帝编号")
        state = self._state(fixture)
        marker = (
            "prematch_synced_at"
            if phase == "prematch"
            else "prematch_24h_synced_at"
            if phase == "prematch_24h"
            else "initial_synced_at"
        )
        if not force and state.get(marker):
            return {"status": "skipped", "fixture_id": fixture_id}
        async with self._semaphore:
            try:
                enriched = await self.provider.enrich_match(match_id)
                fixture = self._apply_match_data(fixture, enriched, phase)
                self.repository.upsert_fixture(fixture)
                await self._sync_teams(fixture)
                return {"status": "synced", "fixture_id": fixture_id, "match_id": match_id, "phase": phase}
            except Exception as error:
                state = self._state(fixture)
                state["last_error"] = str(error)[:500]
                state["last_attempt_at"] = datetime.now(UTC).isoformat()
                fixture["dongqiudi_sync"] = state
                self.repository.upsert_fixture(fixture)
                raise

    def _apply_match_data(self, fixture: dict[str, Any], enriched: dict[str, Any], phase: str) -> dict[str, Any]:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        odds = enriched.get("odds") or {}
        analysis = enriched.get("dongqiudi_analysis") or {}
        context = dict(fixture.get("evidence") or unavailable_context())
        context["odds_by_bookmaker"] = odds.get("bookmakers") or {}
        preferred = _preferred_odds(
            odds.get("bookmakers") or {},
            captured_at=odds.get("captured_at") or odds.get("updated_at") or now,
        )
        if preferred:
            context["odds"] = preferred
        _apply_dongqiudi_analysis(context, analysis, now)
        context["dongqiudi_analysis"] = analysis
        context["source"] = _join_sources(context.get("source"), "dongqiudi")
        context["synced_at"] = now
        fixture["evidence"] = context
        fixture["evidence_synced_at"] = now
        fixture["dongqiudi"] = {"odds": odds, "analysis": analysis, "updated_at": now}
        state = self._state(fixture)
        state.update({"source_match_id": str(odds.get("match_id") or self._source_match_id(fixture) or ""), "last_synced_at": now, "last_error": None})
        if phase == "initial":
            state["initial_synced_at"] = now
        elif phase == "prematch":
            state["prematch_synced_at"] = now
        elif phase == "prematch_24h":
            state["prematch_24h_synced_at"] = now
        else:
            state["manual_synced_at"] = now
            state.setdefault("initial_synced_at", now)
        fixture["dongqiudi_sync"] = state
        _save_odds_snapshots(self.repository, fixture["id"], odds)
        return fixture

    async def _sync_teams(self, fixture: dict[str, Any]) -> None:
        league_key = str(fixture.get("league_key") or "unknown")
        free_data = dict(fixture.get("free_team_data") or {})
        context = fixture.get("evidence") or unavailable_context()
        results = await asyncio.gather(
            *(self._sync_one_team(league_key, side, (fixture.get(f"{side}_team") or {}).get("provider_id")) for side in ("home", "away")),
        )
        errors: list[str] = []
        for side, cached, error in results:
            if error:
                errors.append(f"{side}: {error}")
                continue
            if not cached:
                continue
            free_data[side] = {"profile": cached.get("team") or {}, "squad": cached.get("roster") or [], "source": "dongqiudi"}
            context.setdefault("teams", {})[side] = cached.get("team") or {}
            context.setdefault("squads", {})[side] = cached.get("roster") or []
        fixture["free_team_data"] = free_data
        fixture["free_team_data_synced_at"] = fixture.get("dongqiudi_sync", {}).get("last_synced_at")
        if errors:
            fixture.setdefault("dongqiudi_sync", {})["team_errors"] = errors
        fixture["evidence"] = context
        self.repository.upsert_fixture(fixture)

    async def _sync_one_team(self, league_key: str, side: str, team_id: Any) -> tuple[str, dict[str, Any] | None, str | None]:
        if not team_id:
            return side, None, None
        lock = self._team_locks.setdefault(f"{league_key}:{team_id}", asyncio.Lock())
        async with lock:
            cached = self.repository.team_snapshot(league_key, str(team_id))
            if cached:
                return side, cached, None
            try:
                cached = await self.provider.team(team_id)
                cached["league_key"] = league_key
                self.repository.save_team_snapshot(cached)
                return side, cached, None
            except Exception as error:
                return side, None, str(error)[:240]

    def _find_existing(self, incoming: dict[str, Any]) -> dict[str, Any] | None:
        for item in self.repository.list_fixtures(league_key=incoming.get("league_key")):
            if _same_fixture(item, incoming):
                return item
        return None

    @staticmethod
    def _merge_fixture(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing)
        merged.update(incoming)
        merged["id"] = existing["id"]
        merged["external_ids"] = {**(existing.get("external_ids") or {}), **(incoming.get("external_ids") or {})}
        for field in ("evidence", "evidence_synced_at", "lineup_confirmed", "dongqiudi", "dongqiudi_sync", "free_team_data", "free_team_data_synced_at"):
            if field in existing and field not in incoming:
                merged[field] = existing[field]
        return merged

    @staticmethod
    def _state(fixture: dict[str, Any]) -> dict[str, Any]:
        return dict(fixture.get("dongqiudi_sync") or {})

    @staticmethod
    def _source_match_id(fixture: dict[str, Any]) -> str | None:
        value = (fixture.get("external_ids") or {}).get("dongqiudi")
        if value:
            return str(value)
        fixture_id = str(fixture.get("id") or "")
        return fixture_id.removeprefix("dongqiudi-") if fixture_id.startswith("dongqiudi-") else None


def _preferred_odds(bookmakers: dict[str, Any], *, captured_at: str | None = None) -> dict[str, Any] | None:
    fallback: dict[str, Any] | None = None
    for key in ("bet365", "crown"):
        item = bookmakers.get(key) or {}
        euro = (item.get("1x2") or {}).get("current") or {}
        asia = (item.get("asian_handicap") or {}).get("current") or {}
        if euro.get("home") and euro.get("draw") and euro.get("away"):
            candidate = {
                "bookmaker": item.get("name") or ("Bet365" if key == "bet365" else "皇冠"),
                "home": euro["home"], "draw": euro["draw"], "away": euro["away"],
                "asian_handicap": _canonical_line(asia.get("line"), euro),
                "asian_handicap_label": asia.get("label"),
                "asian_handicap_home_odd": asia.get("home_odd"),
                "asian_handicap_away_odd": asia.get("away_odd"),
                "updated_at": euro.get("updated_at") or asia.get("updated_at") or item.get("updated_at") or captured_at,
                "captured_at": captured_at,
                "source": "dongqiudi",
                "is_demo": False,
            }
            if fallback is None:
                fallback = candidate
            if asia.get("line") is not None and asia.get("home_odd") and asia.get("away_odd"):
                return candidate
    return fallback


def _apply_dongqiudi_analysis(context: dict[str, Any], analysis: dict[str, Any], updated_at: str) -> None:
    """Project Dongqiudi's raw analysis into the canonical detail-page fields."""

    pre_analysis = analysis.get("pre_analysis") or {}
    if not isinstance(pre_analysis, dict):
        return

    recent = _dongqiudi_recent_form(pre_analysis.get("recent_record") or {}, updated_at)
    current_recent = dict(context.get("recent_form") or {})
    if len(recent["home"]) > len(current_recent.get("home") or []):
        current_recent["home"] = recent["home"]
        current_recent["home_points_per_game"] = recent["home_points_per_game"]
    if len(recent["away"]) > len(current_recent.get("away") or []):
        current_recent["away"] = recent["away"]
        current_recent["away_points_per_game"] = recent["away_points_per_game"]
    if current_recent.get("home") or current_recent.get("away"):
        if current_recent.get("home") and not current_recent.get("home_points_per_game"):
            current_recent["home_points_per_game"] = _points_per_game(current_recent["home"])
        else:
            current_recent.setdefault("home_points_per_game", 0.0)
        if current_recent.get("away") and not current_recent.get("away_points_per_game"):
            current_recent["away_points_per_game"] = _points_per_game(current_recent["away"])
        else:
            current_recent.setdefault("away_points_per_game", 0.0)
        if not current_recent.get("updated_at"):
            current_recent["updated_at"] = updated_at
        context["recent_form"] = current_recent

    if not context.get("head_to_head"):
        h2h_rows = ((pre_analysis.get("battle_history") or {}).get("list") or [])
        if not h2h_rows:
            h2h_rows = _analysis_match_rows(analysis.get("h2h"))
        h2h = _dongqiudi_head_to_head(h2h_rows)
        if h2h:
            context["head_to_head"] = h2h

    current_availability = dict(context.get("availability") or {})
    if not current_availability.get("players") and not current_availability.get("updated_at") and not current_availability.get("checked_at"):
        availability = _dongqiudi_availability(pre_analysis.get("sideline") or {}, updated_at)
        if availability["players"] or availability["updated_at"]:
            context["availability"] = availability


def _dongqiudi_recent_form(payload: dict[str, Any], updated_at: str) -> dict[str, Any]:
    result = {
        "home": _dongqiudi_recent_matches(payload.get("team_A") or [], "team_A"),
        "away": _dongqiudi_recent_matches(payload.get("team_B") or [], "team_B"),
        "home_points_per_game": 0.0,
        "away_points_per_game": 0.0,
        "updated_at": updated_at,
    }
    result["home_points_per_game"] = _points_per_game(result["home"])
    result["away_points_per_game"] = _points_per_game(result["away"])
    return result


def _dongqiudi_recent_matches(rows: list[dict[str, Any]], tracked_side: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        score = _normalize_score(row.get("score"))
        if not score:
            continue
        home = to_chinese_team_name(row.get("team_A_name") or "未知球队")
        away = to_chinese_team_name(row.get("team_B_name") or "未知球队")
        team_is_home = row.get("main_team") == "team_A"
        result = _dongqiudi_result(row.get("color"), score, team_is_home)
        if not result:
            continue
        matches.append(
            {
                "date": _dongqiudi_date(row),
                "home": home,
                "away": away,
                "score": score,
                "result": result,
                "team_is_home": team_is_home,
            }
        )
    return matches


def _dongqiudi_head_to_head(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        score = _normalize_score(row.get("score"))
        if not score:
            continue
        matches.append(
            {
                "date": _dongqiudi_date(row),
                "home": to_chinese_team_name(row.get("team_A_name") or "未知球队"),
                "away": to_chinese_team_name(row.get("team_B_name") or "未知球队"),
                "score": score,
            }
        )
    return matches


def _analysis_match_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("list", "matches", "events", "items", "records"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _dongqiudi_availability(payload: dict[str, Any], updated_at: str) -> dict[str, Any]:
    players: list[dict[str, Any]] = []
    notes: list[str] = []
    for side_key, side in (("team_A", "home"), ("team_B", "away")):
        for row in payload.get(side_key) or []:
            if not isinstance(row, dict):
                continue
            original_name = str(row.get("name") or "未知球员")
            name = to_chinese_player_name(original_name)
            reason = str(row.get("reason") or "缺阵")
            href = str(row.get("href") or "")
            provider_player_id = next(iter(re.findall(r"/player/(\d+)", href)), None)
            players.append(
                {
                    "team": side,
                    "provider_player_id": provider_player_id,
                    "name": name,
                    "original_name": original_name,
                    "reason": reason,
                }
            )
            notes.append(f"{name}：{reason}")
    return {
        "home_missing": sum(1 for player in players if player["team"] == "home"),
        "away_missing": sum(1 for player in players if player["team"] == "away"),
        "notes": notes[:12],
        "players": players[:24],
        "updated_at": updated_at,
        "checked_at": updated_at,
    }


def _dongqiudi_result(color: Any, score: str, team_is_home: bool) -> str | None:
    result = {"win": "W", "draw": "D", "lose": "L", "平": "D", "胜": "W", "负": "L"}.get(str(color or "").strip().casefold())
    if result:
        return result
    values = [int(value) for value in re.split(r"\s*[-:]\s*", score)]
    if len(values) != 2:
        return None
    team_score, opponent_score = (values if team_is_home else values[::-1])
    return "W" if team_score > opponent_score else "D" if team_score == opponent_score else "L"


def _normalize_score(value: Any) -> str | None:
    match = re.match(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$", str(value or ""))
    return f"{match.group(1)} - {match.group(2)}" if match else None


def _dongqiudi_date(row: dict[str, Any]) -> str:
    start_time = str(row.get("start_time") or "")
    if len(start_time) >= 10 and start_time[4] == "-":
        return start_time[:10]
    year = str(row.get("year") or "")
    month_day = str(row.get("date") or "").strip()
    if year and re.match(r"^\d{1,2}-\d{1,2}$", month_day):
        month, day = (int(value) for value in month_day.split("-"))
        return f"{int(year):04d}-{month:02d}-{day:02d}"
    return month_day or start_time[:10]


def _points_per_game(matches: list[dict[str, Any]]) -> float:
    if not matches:
        return 0.0
    points = sum(3 if match.get("result") == "W" else 1 if match.get("result") == "D" else 0 for match in matches)
    return round(points / len(matches), 2)


def _save_odds_snapshots(repository: Any, fixture_id: str, odds: dict[str, Any]) -> None:
    captured_at = odds.get("captured_at") or datetime.now(UTC).isoformat()
    for bookmaker_key, item in (odds.get("bookmakers") or {}).items():
        quotes: list[dict[str, Any]] = []
        euro = item.get("1x2") or {}
        current_euro = euro.get("current") or {}
        initial_euro = euro.get("initial") or {}
        for selection in ("home", "draw", "away"):
            if current_euro.get(selection) is not None:
                quotes.append({"market": "1x2", "selection": selection, "line": None, "price": current_euro[selection], "initial_price": initial_euro.get(selection), "bookmaker": item.get("name") or bookmaker_key, "source": "dongqiudi", "captured_at": captured_at, "source_updated_at": current_euro.get("updated_at") or captured_at})
        asia = item.get("asian_handicap") or {}
        current_asia = asia.get("current") or {}
        initial_asia = asia.get("initial") or {}
        line = _canonical_line(current_asia.get("line"), current_euro)
        if line is not None:
            for selection, key in (("home_handicap", "home_odd"), ("away_handicap", "away_odd")):
                if current_asia.get(key) is not None:
                    quotes.append({"market": "asian_handicap", "selection": selection, "line": line, "line_label": current_asia.get("label"), "price": current_asia[key], "initial_price": initial_asia.get(key), "initial_line": _canonical_line(initial_asia.get("line"), initial_euro), "bookmaker": item.get("name") or bookmaker_key, "source": "dongqiudi", "captured_at": captured_at, "source_updated_at": current_asia.get("updated_at") or captured_at})
        if not quotes:
            continue
        encoded = json.dumps({"fixture_id": fixture_id, "bookmaker": bookmaker_key, "quotes": quotes}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        repository.save_odds_snapshot({"id": f"odds:dongqiudi:{fixture_id}:{hashlib.sha256(encoded).hexdigest()[:32]}", "fixture_id": fixture_id, "captured_at": captured_at, "source_updated_at": captured_at, "source": "dongqiudi", "bookmaker": item.get("name") or bookmaker_key, "quotes": quotes})


def _same_fixture(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("league_key") != right.get("league_key"):
        return False
    left_kickoff = _as_utc(left.get("kickoff"))
    right_kickoff = _as_utc(right.get("kickoff"))
    if left_kickoff is None or right_kickoff is None or abs((left_kickoff - right_kickoff).total_seconds()) > 900:
        return False
    return _team_name(left.get("home_team")) == _team_name(right.get("home_team")) and _team_name(left.get("away_team")) == _team_name(right.get("away_team"))


def _canonical_line(value: Any, euro: dict[str, Any]) -> float | None:
    try:
        line = float(value)
    except (TypeError, ValueError):
        return None
    if line == 0:
        return 0.0
    try:
        home = float(euro.get("home"))
        away = float(euro.get("away"))
    except (TypeError, ValueError):
        return abs(line)
    return -abs(line) if home < away else abs(line)


def _team_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    name = to_chinese_team_name(str(value.get("name") or ""))
    return " ".join(name.casefold().split())


def _join_sources(left: Any, right: str) -> str:
    parts = [item for item in str(left or "").split("+") if item]
    return "+".join(dict.fromkeys([*parts, right]))


def _as_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None
