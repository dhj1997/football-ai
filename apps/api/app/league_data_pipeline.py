"""Bounded three-league historical data pipeline for P5."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Protocol

from .historical_validation import (
    HistoricalBackfillService,
    RollingBacktestService,
    build_historical_snapshot,
    build_raw_data_record,
    parse_timestamp,
)
from .player_identity import public_payload
from .team_names import to_chinese_team_name


SUPPORTED_LEAGUES: dict[str, dict[str, Any]] = {
    "CSL": {
        "name": "中国足球超级联赛",
        "aliases": ("csl", "chinese super league", "chinese-super-league", "169", "中超"),
        "provider_keys": {"api-football": "csl", "thesportsdb": "csl", "espn": "csl"},
    },
    "EPL": {
        "name": "英格兰足球超级联赛",
        "aliases": ("epl", "premier league", "english premier league", "39", "英超"),
        "provider_keys": {"api-football": "epl", "thesportsdb": "epl", "espn": "epl"},
    },
    "LAL": {
        "name": "西班牙足球甲级联赛",
        "aliases": ("lal", "laliga", "la liga", "primera division", "140", "西甲"),
        "provider_keys": {"api-football": "laliga", "thesportsdb": "laliga", "espn": "laliga"},
    },
}

ALLOWED_FIXTURE_STATUSES = frozenset({"scheduled", "live", "finished", "postponed", "cancelled", "unknown"})
DEFAULT_LEAGUE_LIMIT = 100
DEFAULT_TOTAL_LIMIT = 300
DEFAULT_PAGE_SIZE = 20


class FixtureProvider(Protocol):
    async def historical_fixtures(self, **kwargs: Any) -> Any: ...


class TeamProvider(Protocol):
    async def historical_teams(self, **kwargs: Any) -> Any: ...


class LeagueProvider(Protocol):
    async def historical_leagues(self, **kwargs: Any) -> Any: ...


class ResultProvider(Protocol):
    async def historical_results(self, **kwargs: Any) -> Any: ...


class OddsProvider(Protocol):
    async def historical_odds(self, **kwargs: Any) -> Any: ...


def normalize_league_code(value: Any) -> str | None:
    """Return one of P5's uppercase codes, or None for an unsupported league."""

    raw = str(value or "").strip().casefold()
    if not raw:
        return None
    for code, item in SUPPORTED_LEAGUES.items():
        if raw == code.casefold() or raw in {str(alias).casefold() for alias in item["aliases"]}:
            return code
    return None


def provider_league_key(code: str, provider: str) -> str:
    normalized = normalize_league_code(code)
    if normalized is None:
        raise ValueError(f"Unsupported P5 league: {code}")
    return str(SUPPORTED_LEAGUES[normalized]["provider_keys"].get(provider, normalized.casefold()))


def _normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    text = re.sub(r"\b(fc|cf|club|football|afc)\b", " ", text)
    compact = re.sub(r"[^a-z0-9]+", "", text)
    # Common provider alias that otherwise defeats the canonical team key.
    return {"barca": "barcelona"}.get(compact, compact)


def _team_name(team: Any) -> str:
    if isinstance(team, Mapping):
        return str(team.get("original_name") or team.get("name") or team.get("display_name") or "")
    return str(team or "")


def _source_id(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _stable_id(prefix: str, *values: Any) -> str:
    encoded = "|".join(str(value or "") for value in values)
    return f"{prefix}:{hashlib.sha256(encoded.encode()).hexdigest()[:32]}"


def canonical_team_id(
    team: Mapping[str, Any] | str,
    league: str,
    season: Any,
    *,
    source_team_id: Any | None = None,
) -> str | None:
    """Resolve a canonical team only when a source ID and name are present."""

    normalized = _normalize_name(_team_name(team))
    source_id = str(source_team_id or (team.get("provider_id") if isinstance(team, Mapping) else "") or "")
    if not normalized or not source_id or normalize_league_code(league) is None:
        return None
    # Season/source are mapping dimensions; canonical identity remains stable across providers.
    return _stable_id("team", normalize_league_code(league), normalized)


def canonical_fixture_id(
    fixture: Mapping[str, Any],
    league: str,
    season: Any,
    home_team_id: str | None,
    away_team_id: str | None,
) -> str | None:
    kickoff = parse_timestamp(fixture.get("kickoff") or fixture.get("kickoff_at"))
    if not kickoff or not home_team_id or not away_team_id:
        return None
    code = normalize_league_code(league)
    if code is None:
        return None
    return _stable_id("fixture", code, season, home_team_id, away_team_id, kickoff.isoformat())


def normalize_fixture_status(value: Any, *, score: Mapping[str, Any] | None = None) -> str:
    status = str(value or "").strip().casefold()
    aliases = {
        "ns": "scheduled",
        "tbd": "scheduled",
        "ft": "finished",
        "aet": "finished",
        "pen": "finished",
        "pst": "postponed",
        "susp": "postponed",
        "int": "postponed",
        "canc": "cancelled",
        "abd": "cancelled",
        "wo": "cancelled",
        "awd": "cancelled",
    }
    normalized = aliases.get(status, status)
    if normalized not in ALLOWED_FIXTURE_STATUSES:
        normalized = "finished" if score and score.get("home") is not None and score.get("away") is not None else "unknown"
    return normalized


def fixture_source_conflicts(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Find provider disagreement for the same league/season/team pairing."""

    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        code = normalize_league_code(record.get("canonical_league") or record.get("league_code") or record.get("league_key"))
        home = _team_name(record.get("home_team") or record.get("home"))
        away = _team_name(record.get("away_team") or record.get("away"))
        season = str(record.get("season") or "unknown")
        if not code or not _normalize_name(home) or not _normalize_name(away):
            continue
        groups.setdefault((code, season, _normalize_name(home), _normalize_name(away)), []).append(record)
    conflicts: list[dict[str, Any]] = []
    for key, rows in groups.items():
        kickoffs = {str(parse_timestamp(row.get("kickoff_at") or row.get("kickoff") or row.get("date")) or "") for row in rows}
        scores = {json.dumps(row.get("score"), sort_keys=True, default=str) for row in rows if row.get("score") is not None}
        if len(kickoffs) <= 1 and len(scores) <= 1:
            continue
        conflicts.append(
            {
                "league": key[0],
                "season": key[1],
                "home": key[2],
                "away": key[3],
                "conflict_type": "kickoff_or_result",
                "source_a": rows[0].get("source"),
                "source_b": next((row.get("source") for row in rows[1:] if row.get("source") != rows[0].get("source")), None),
                "value_a": {"kickoff": rows[0].get("kickoff"), "score": rows[0].get("score")},
                "value_b": {"kickoff": rows[-1].get("kickoff"), "score": rows[-1].get("score")},
                "resolution_method": "configured_source_priority_then_manual_review",
                "resolved_value": None,
            }
        )
    return conflicts


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_leagues: tuple[str, ...] = ()
    supports_seasons: bool = False
    supports_fixtures: bool = False
    supports_results: bool = False
    supports_odds: bool = False
    supports_lineups: bool = False
    supports_injuries: bool = False
    supports_pagination: bool = False
    supports_limit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "supports_leagues": list(self.supports_leagues),
            "supports_seasons": self.supports_seasons,
            "supports_fixtures": self.supports_fixtures,
            "supports_results": self.supports_results,
            "supports_odds": self.supports_odds,
            "supports_lineups": self.supports_lineups,
            "supports_injuries": self.supports_injuries,
            "supports_pagination": self.supports_pagination,
            "supports_limit": self.supports_limit,
        }


@dataclass
class ProviderDescriptor:
    name: str
    provider: Any
    capabilities: ProviderCapabilities
    source_priority: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(getattr(self.provider, "configured", True))

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "configured": self.configured,
            "capabilities": self.capabilities.as_dict(),
            "source_priority": {key: list(value) for key, value in self.source_priority.items()},
        }


class P5ProviderRegistry:
    """Central registry for P5 provider capabilities and priority policy."""

    def __init__(self) -> None:
        self._items: dict[str, ProviderDescriptor] = {}

    def register(
        self,
        name: str,
        provider: Any,
        capabilities: ProviderCapabilities,
        source_priority: Mapping[str, Iterable[str]] | None = None,
    ) -> ProviderDescriptor:
        descriptor = ProviderDescriptor(
            name=name,
            provider=provider,
            capabilities=capabilities,
            source_priority={key: tuple(value) for key, value in (source_priority or {}).items()},
        )
        self._items[name] = descriptor
        return descriptor

    def get(self, name: str) -> ProviderDescriptor | None:
        return self._items.get(name)

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    def as_dict(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.descriptors()]


def build_default_provider_registry(
    api_football: Any | None = None,
    thesportsdb: Any | None = None,
    espn: Any | None = None,
) -> P5ProviderRegistry:
    registry = P5ProviderRegistry()
    all_leagues = tuple(SUPPORTED_LEAGUES)
    priority = {"fixture": ("api-football", "espn", "thesportsdb"), "result": ("api-football", "espn", "thesportsdb"), "team": ("espn", "api-football", "thesportsdb"), "league": ("espn", "api-football", "thesportsdb"), "odds": ("api-football", "espn", "thesportsdb")}
    if api_football is not None:
        registry.register(
            "api-football",
            api_football,
            ProviderCapabilities(all_leagues, True, True, True, False, False, False, True, True),
            priority,
        )
    if espn is not None:
        registry.register(
            "espn",
            espn,
            # The current ESPN adapter exposes standings only; do not claim
            # historical fixture/result/odds support it does not implement.
            ProviderCapabilities(all_leagues, True, False, False, False, False, False, False, False),
            priority,
        )
    if thesportsdb is not None:
        registry.register(
            "thesportsdb",
            thesportsdb,
            ProviderCapabilities(all_leagues, False, True, True, False, False, False, False, True),
            priority,
        )
    return registry


def _extract_items(value: Any) -> tuple[list[dict[str, Any]], Any | None, bool | None]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)], None, None
    if not isinstance(value, Mapping):
        return [], None, False
    items = value.get("items") or value.get("fixtures") or value.get("results") or value.get("teams") or value.get("response") or value.get("data") or []
    if isinstance(items, Mapping):
        items = list(items.values())
    paging = value.get("paging") or {}
    next_cursor = value.get("next_cursor") or value.get("nextCursor") or paging.get("next_cursor")
    has_more = value.get("has_more") if "has_more" in value else value.get("hasMore")
    if has_more is None and paging:
        current = int(paging.get("current") or 0)
        total = int(paging.get("total") or 0)
        has_more = bool(current and total and current < total)
    return [dict(item) for item in items if isinstance(item, Mapping)], next_cursor, has_more


async def _invoke_provider(provider: Any, method_names: Iterable[str], **kwargs: Any) -> Any:
    method = next((getattr(provider, name, None) for name in method_names if callable(getattr(provider, name, None))), None)
    if method is None:
        raise AttributeError(f"Provider does not expose any of: {', '.join(method_names)}")
    parameters = inspect.signature(method).parameters
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    call_kwargs = kwargs if accepts_kwargs else {key: value for key, value in kwargs.items() if key in parameters}
    result = method(**call_kwargs)
    return await result if inspect.isawaitable(result) else result


def _error_category(error: Exception) -> str:
    message = str(error).casefold()
    if "429" in message or "rate" in message:
        return "rate_limit"
    if isinstance(error, (ValueError, KeyError, TypeError, AttributeError)):
        return "data_quality_error"
    if "timeout" in message or "connection" in message or "network" in message:
        return "transient_error"
    return "permanent_error"


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None


class HistoricalLeagueDataService:
    """Fetch and persist bounded P5 data without replacing historical windows."""

    def __init__(
        self,
        repository: Any,
        registry: P5ProviderRegistry,
        *,
        max_per_league: int = DEFAULT_LEAGUE_LIMIT,
        max_total: int = DEFAULT_TOTAL_LIMIT,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.max_per_league = min(max(1, int(max_per_league)), DEFAULT_LEAGUE_LIMIT)
        self.max_total = min(max(1, int(max_total)), DEFAULT_TOTAL_LIMIT)
        self.page_size = max(1, int(page_size))

    def coverage(self) -> dict[str, Any]:
        canonical_by_league: dict[str, set[str]] = {code: set() for code in SUPPORTED_LEAGUES}
        reader = getattr(self.repository, "fixture_identities", None)
        rows = reader(limit=10000) if callable(reader) else []
        for row in rows:
            code = normalize_league_code(row.get("league"))
            canonical = row.get("canonical_fixture_id")
            if code and canonical:
                canonical_by_league[code].add(str(canonical))
        counts = {code: len(values) for code, values in canonical_by_league.items()}
        return {
            "leagues": counts,
            "total": sum(counts.values()),
            "limits": {"per_league": self.max_per_league, "total": self.max_total},
            "within_limits": all(value <= self.max_per_league for value in counts.values()) and sum(counts.values()) <= self.max_total,
        }

    def _start_run(self, provider: str, league: str | None, entity_type: str, config: Mapping[str, Any]) -> dict[str, Any]:
        run = {
            "run_id": f"sync:{uuid.uuid4()}",
            "provider": provider,
            "league": league,
            "entity_type": entity_type,
            "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "finished_at": None,
            "status": "running",
            "records_seen": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_rejected": 0,
            "error_category": None,
            "errors": [],
            "config": dict(config),
        }
        saver = getattr(self.repository, "save_data_sync_run", None)
        if callable(saver):
            saver(run)
        return run

    def _finish_run(self, run: dict[str, Any], **updates: Any) -> dict[str, Any]:
        run.update(updates)
        run["finished_at"] = run.get("finished_at") or datetime.now(UTC).replace(microsecond=0).isoformat()
        if run.get("status") == "running":
            run["status"] = "completed" if not run.get("errors") else "partial"
        updater = getattr(self.repository, "update_data_sync_run", None)
        if callable(updater):
            updater(run["run_id"], run)
        return run

    def _existing_fixture_ids(self, code: str) -> set[str]:
        reader = getattr(self.repository, "fixture_identities", None)
        rows = reader(code, 10000) if callable(reader) else []
        return {str(row.get("canonical_fixture_id")) for row in rows if row.get("canonical_fixture_id")}

    def _existing_fixture_for_pair(self, code: str, season: Any, home: Any, away: Any) -> dict[str, Any] | None:
        reader = getattr(self.repository, "list_fixtures", None)
        if not callable(reader):
            return None
        home_key = _normalize_name(_team_name(home))
        away_key = _normalize_name(_team_name(away))
        rows = reader(league_key=code.casefold())
        return next(
            (
                row
                for row in rows
                if normalize_league_code(row.get("canonical_league") or row.get("league_key")) == code
                and str(row.get("season") or "") == str(season)
                and _normalize_name(_team_name(row.get("home_team"))) == home_key
                and _normalize_name(_team_name(row.get("away_team"))) == away_key
            ),
            None,
        )

    async def _fetch_pages(
        self,
        descriptor: ProviderDescriptor,
        method_names: Iterable[str],
        *,
        code: str,
        season: Any | None,
        start_date: Any | None,
        end_date: Any | None,
        limit: int,
        cursor: Any | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not descriptor.configured:
            raise RuntimeError(f"provider {descriptor.name} unavailable")
        if not descriptor.capabilities.supports_pagination and not descriptor.capabilities.supports_limit and limit > self.page_size:
            # A provider that cannot bound a request is not safe for P5 history.
            raise RuntimeError("provider does not support bounded historical pagination")
        rows: list[dict[str, Any]] = []
        rejected: list[str] = []
        seen_source_ids: set[str] = set()
        page = 1
        next_cursor = cursor
        max_pages = max(1, (limit + self.page_size - 1) // self.page_size + 2)
        while len(rows) < limit and page <= max_pages:
            response = await _invoke_provider(
                descriptor.provider,
                method_names,
                league=provider_league_key(code, descriptor.name),
                league_code=code,
                season=season,
                start_date=_date_value(start_date),
                end_date=_date_value(end_date),
                date_from=_date_value(start_date),
                date_to=_date_value(end_date),
                page=page,
                cursor=next_cursor,
                # Keep provider pagination stable. The service truncates the
                # collected page to the remaining cap below.
                limit=self.page_size,
            )
            items, response_cursor, has_more = _extract_items(response)
            if not items:
                break
            new_count = 0
            for item in items:
                source_id = _source_id(item, "source_record_id", "provider_id", "id", "fixture_id", "team_id")
                if source_id and source_id in seen_source_ids:
                    continue
                if source_id:
                    seen_source_ids.add(source_id)
                rows.append(item)
                new_count += 1
                if len(rows) >= limit:
                    break
            if new_count == 0 or has_more is False:
                break
            next_cursor = response_cursor
            page += 1
            if response_cursor is not None and not descriptor.capabilities.supports_pagination:
                break
        return rows[:limit], rejected

    def _raw_capture_time(self, item: Mapping[str, Any]) -> str:
        value = item.get("captured_at") or item.get("source_captured_at") or item.get("ingested_at") or item.get("synced_at")
        return parse_timestamp(value).isoformat() if parse_timestamp(value) else datetime.now(UTC).replace(microsecond=0).isoformat()

    def _save_raw(self, entity_type: str, provider: str, item: Mapping[str, Any]) -> None:
        saver = getattr(self.repository, "save_raw_data_record", None)
        if not callable(saver):
            return
        source_id = _source_id(item, "source_record_id", "provider_id", "id", "fixture_id", "team_id")
        if not source_id:
            return
        saver(build_raw_data_record(entity_type, provider, source_id, item, self._raw_capture_time(item)))

    def _team_identity(self, team: Mapping[str, Any], code: str, season: Any, provider: str, conflict: bool = False) -> dict[str, Any]:
        source_id = _source_id(team, "source_team_id", "provider_id", "id", "team_id")
        original = _team_name(team)
        canonical = canonical_team_id(team, code, season, source_team_id=source_id)
        item = {
            "canonical_team_id": canonical or _stable_id("unresolved-team", provider, source_id, original),
            "league": code,
            "season": str(season or "unknown"),
            "source": provider,
            "source_team_id": source_id or f"unresolved:{_normalize_name(original)}",
            "normalized_name": _normalize_name(original),
            "display_name": to_chinese_team_name(original) if original else "待核验球队",
            "identity_status": "resolved" if canonical else "unresolved",
            "conflict": conflict,
        }
        saver = getattr(self.repository, "save_team_identity", None)
        if callable(saver):
            saver(item)
        return item

    def _normalize_fixture(self, raw: Mapping[str, Any], code: str, season: Any, provider: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
        raw_code = raw.get("canonical_league") or raw.get("league_code") or raw.get("league_key")
        if raw_code is not None and normalize_league_code(raw_code) != code:
            return None, None, [{"reason": "unsupported_or_mismatched_league", "value": raw_code}]
        home = raw.get("home_team") or raw.get("home") or {}
        away = raw.get("away_team") or raw.get("away") or {}
        home_map = self._team_identity(home if isinstance(home, Mapping) else {"name": home}, code, season, provider)
        away_map = self._team_identity(away if isinstance(away, Mapping) else {"name": away}, code, season, provider)
        kickoff = parse_timestamp(raw.get("kickoff_at") or raw.get("kickoff") or raw.get("date"))
        canonical = canonical_fixture_id(raw, code, season, home_map["canonical_team_id"] if home_map["identity_status"] == "resolved" else None, away_map["canonical_team_id"] if away_map["identity_status"] == "resolved" else None)
        if not canonical or home_map["identity_status"] != "resolved" or away_map["identity_status"] != "resolved" or not kickoff:
            return None, None, [{"reason": "unresolved_fixture_identity", "source_record_id": _source_id(raw, "provider_id", "id")}]
        score = raw.get("score") if isinstance(raw.get("score"), Mapping) else None
        fixture = {
            **dict(raw),
            "source": provider,
            "id": str(raw.get("id") or f"{provider}-{_source_id(raw, 'provider_id', 'source_record_id') or uuid.uuid4()}"),
            "provider_id": raw.get("provider_id") or raw.get("id"),
            "league_key": code.casefold(),
            "canonical_league": code,
            "season": str(season),
            "canonical_fixture_id": canonical,
            "kickoff": kickoff.isoformat(),
            "fixture_date": kickoff.date().isoformat(),
            "home_team": {**(dict(home) if isinstance(home, Mapping) else {"name": home}), "canonical_team_id": home_map["canonical_team_id"], "name": home_map["display_name"], "original_name": _team_name(home)},
            "away_team": {**(dict(away) if isinstance(away, Mapping) else {"name": away}), "canonical_team_id": away_map["canonical_team_id"], "name": away_map["display_name"], "original_name": _team_name(away)},
            "status": normalize_fixture_status(raw.get("status") or raw.get("provider_status"), score=score),
            "is_demo": False,
        }
        identity = {
            "canonical_fixture_id": canonical,
            "league": code,
            "season": str(season),
            "source": provider,
            "source_fixture_id": _source_id(raw, "source_fixture_id", "provider_id", "id"),
            "kickoff_at": kickoff.isoformat(),
            "identity_status": "resolved",
            "conflict": False,
        }
        return fixture, identity, []

    async def sync_leagues(self, provider_name: str) -> dict[str, Any]:
        descriptor = self.registry.get(provider_name)
        if descriptor is None:
            return {"status": "provider_unavailable", "provider": provider_name, "records_rejected": 0}
        run = self._start_run(provider_name, None, "league", {})
        try:
            rows, _ = await self._fetch_pages(descriptor, ("historical_leagues", "leagues"), code="EPL", season=None, start_date=None, end_date=None, limit=len(SUPPORTED_LEAGUES))
        except Exception as error:
            return self._finish_run(run, status="unavailable", error_category=_error_category(error), errors=[str(error)], records_rejected=0)
        accepted = [row for row in rows if normalize_league_code(row.get("code") or row.get("league_key") or row.get("name"))]
        return self._finish_run(run, records_seen=len(rows), records_inserted=len(accepted), records_rejected=len(rows) - len(accepted))

    async def sync_fixtures(
        self,
        provider_name: str,
        league: str,
        season: Any,
        *,
        start_date: Any | None = None,
        end_date: Any | None = None,
        limit: int | None = None,
        since: Any | None = None,
        until: Any | None = None,
        cursor: Any | None = None,
    ) -> dict[str, Any]:
        code = normalize_league_code(league)
        descriptor = self.registry.get(provider_name)
        if code is None:
            return {"status": "rejected", "league": str(league), "reason": "unsupported_league", "records_rejected": 1}
        start_date = start_date or since
        end_date = end_date or until
        requested = min(int(limit or self.max_per_league), self.max_per_league)
        coverage = self.coverage()
        remaining = min(requested, max(0, self.max_per_league - coverage["leagues"].get(code, 0)), max(0, self.max_total - coverage["total"]))
        run = self._start_run(provider_name, code, "fixture", {"season": season, "start_date": start_date, "end_date": end_date, "limit": requested, "remaining": remaining})
        if descriptor is None or not descriptor.capabilities.supports_fixtures:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["fixture provider unavailable"], records_rejected=0)
        if season is not None and not descriptor.capabilities.supports_seasons and start_date is None and end_date is None:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["provider does not support season-scoped history"])
        if remaining <= 0:
            return self._finish_run(run, status="capped", records_seen=0, records_inserted=0, records_rejected=0)
        try:
            rows, _ = await self._fetch_pages(descriptor, ("historical_fixtures", "fetch_fixtures", "fixtures"), code=code, season=season, start_date=start_date, end_date=end_date, limit=remaining, cursor=cursor)
        except Exception as error:
            return self._finish_run(run, status="unavailable", error_category=_error_category(error), errors=[str(error)])
        existing = self._existing_fixture_ids(code)
        conflicts = fixture_source_conflicts(rows)
        conflict_keys = {(item["league"], item["season"], item["home"], item["away"]): item for item in conflicts}
        seen: set[str] = set()
        inserted = updated = rejected = 0
        errors: list[dict[str, Any]] = []
        for raw in rows:
            run["records_seen"] += 1
            self._save_raw("fixture", provider_name, raw)
            fixture, identity, item_errors = self._normalize_fixture(raw, code, season, provider_name)
            if fixture is None or identity is None:
                rejected += 1
                errors.extend(item_errors)
                continue
            existing_pair = self._existing_fixture_for_pair(
                code,
                season,
                raw.get("home_team") or raw.get("home"),
                raw.get("away_team") or raw.get("away"),
            )
            if existing_pair and str(existing_pair.get("source") or "") and str(existing_pair.get("source")) != provider_name:
                prior_kickoff = parse_timestamp(existing_pair.get("kickoff"))
                incoming_kickoff = parse_timestamp(fixture.get("kickoff"))
                fixture["id"] = str(existing_pair.get("id") or fixture["id"])
                fixture["canonical_fixture_id"] = existing_pair.get("canonical_fixture_id") or fixture["canonical_fixture_id"]
                identity["canonical_fixture_id"] = fixture["canonical_fixture_id"]
                if prior_kickoff and incoming_kickoff and prior_kickoff != incoming_kickoff:
                    conflict = {
                        "conflict_type": "kickoff",
                        "source_a": existing_pair.get("result_source") or "existing",
                        "source_b": provider_name,
                        "value_a": prior_kickoff.isoformat(),
                        "value_b": incoming_kickoff.isoformat(),
                        "resolved_value": None,
                        "resolution_method": "configured_source_priority_then_manual_review",
                    }
                    identity["conflict"] = True
                    fixture["identity_conflict"] = conflict
                    # Keep the first canonical window; the conflicting value remains in Raw.
                    fixture["provider_kickoff_at"] = incoming_kickoff.isoformat()
                    fixture["kickoff"] = existing_pair["kickoff"]
                    fixture["fixture_date"] = existing_pair["fixture_date"]
            canonical = identity["canonical_fixture_id"]
            conflict_key = (
                code,
                str(season),
                _normalize_name(_team_name(raw.get("home_team") or raw.get("home"))),
                _normalize_name(_team_name(raw.get("away_team") or raw.get("away"))),
            )
            if conflict_key in conflict_keys:
                identity["conflict"] = True
                fixture["identity_conflict"] = conflict_keys[conflict_key]
            if canonical in seen:
                continue
            seen.add(canonical)
            if canonical in existing:
                updated += 1
            else:
                inserted += 1
                existing.add(canonical)
            fixture_saver = getattr(self.repository, "upsert_fixture", None)
            if callable(fixture_saver):
                fixture_saver(fixture)
            identity_saver = getattr(self.repository, "save_fixture_identity", None)
            if callable(identity_saver):
                identity_saver(identity)
        return self._finish_run(run, records_inserted=inserted, records_updated=updated, records_rejected=rejected, errors=errors)

    async def sync_teams(
        self,
        provider_name: str,
        league: str,
        season: Any,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        code = normalize_league_code(league)
        descriptor = self.registry.get(provider_name)
        if code is None:
            return {"status": "rejected", "league": str(league), "reason": "unsupported_league"}
        run = self._start_run(provider_name, code, "team", {"season": season, "limit": limit})
        if descriptor is None:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["provider unavailable"])
        if season is not None and not descriptor.capabilities.supports_seasons:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["provider does not support season-scoped teams"])
        try:
            rows, _ = await self._fetch_pages(descriptor, ("historical_teams", "fetch_teams", "teams"), code=code, season=season, start_date=None, end_date=None, limit=min(limit, self.max_per_league))
        except Exception as error:
            return self._finish_run(run, status="unavailable", error_category=_error_category(error), errors=[str(error)])
        inserted = 0
        for row in rows:
            run["records_seen"] += 1
            self._save_raw("team", provider_name, row)
            item = self._team_identity(row, code, season, provider_name)
            inserted += int(item["identity_status"] == "resolved")
        return self._finish_run(run, records_inserted=inserted, records_rejected=len(rows) - inserted)

    async def sync_results(
        self,
        provider_name: str,
        league: str,
        season: Any,
        *,
        fixture_ids: Iterable[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        code = normalize_league_code(league)
        descriptor = self.registry.get(provider_name)
        if code is None:
            return {"status": "rejected", "league": str(league), "reason": "unsupported_league"}
        run = self._start_run(provider_name, code, "result", {"season": season, "limit": limit})
        if descriptor is None or not descriptor.capabilities.supports_results:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["result provider unavailable"])
        if season is not None and not descriptor.capabilities.supports_seasons:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["provider does not support season-scoped results"])
        try:
            rows, _ = await self._fetch_pages(descriptor, ("historical_results", "fetch_results", "results"), code=code, season=season, start_date=None, end_date=None, limit=min(limit, self.max_per_league))
        except Exception as error:
            return self._finish_run(run, status="unavailable", error_category=_error_category(error), errors=[str(error)])
        wanted = {str(value) for value in fixture_ids or ()}
        updated = rejected = 0
        for row in rows:
            run["records_seen"] += 1
            source_id = _source_id(row, "fixture_id", "provider_fixture_id", "provider_id", "id")
            if wanted and source_id not in wanted:
                continue
            self._save_raw("result", provider_name, row)
            fixture = self._find_fixture(provider_name, source_id, code)
            if not fixture:
                rejected += 1
                continue
            score = row.get("score") if isinstance(row.get("score"), Mapping) else {"home": row.get("home_score"), "away": row.get("away_score")}
            next_status = normalize_fixture_status(row.get("status") or row.get("provider_status"), score=score)
            if fixture.get("status") == "postponed" and next_status == "finished":
                rejected += 1
                continue
            previous_score = fixture.get("score")
            previous_status = fixture.get("status")
            previous_version = int(fixture.get("result_version") or 0)
            changed = previous_score != score or previous_status != next_status
            fixture.update(
                {
                    "score": score,
                    "status": next_status,
                    "result_source": provider_name,
                    "result_captured_at": self._raw_capture_time(row),
                    "result_version": previous_version + 1 if changed else max(previous_version, 1),
                    "previous_result_version": previous_version or None,
                }
            )
            saver = getattr(self.repository, "upsert_fixture", None)
            if callable(saver):
                saver(fixture)
            updated += 1
        return self._finish_run(run, records_updated=updated, records_rejected=rejected)

    def _find_fixture(self, provider_name: str, source_id: str, code: str | None) -> dict[str, Any] | None:
        fixture_reader = getattr(self.repository, "fixture", None)
        if not callable(fixture_reader):
            return None
        prefixes = (f"{provider_name}-{source_id}", f"{provider_name.split('-')[0]}-{source_id}", source_id)
        for fixture_id in prefixes:
            fixture = fixture_reader(fixture_id)
            if fixture:
                return fixture
        list_reader = getattr(self.repository, "list_fixtures", None)
        rows = list_reader(league_key=code.casefold()) if callable(list_reader) and code else []
        return next(
            (
                fixture
                for fixture in rows
                if str(fixture.get("provider_id") or "") == source_id
                or str(fixture.get("id") or "") in prefixes
            ),
            None,
        )

    async def sync_odds(
        self,
        provider_name: str,
        league: str,
        season: Any,
        *,
        fixture_ids: Iterable[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        code = normalize_league_code(league)
        descriptor = self.registry.get(provider_name)
        if code is None:
            return {"status": "rejected", "league": str(league), "reason": "unsupported_league"}
        run = self._start_run(provider_name, code, "odds", {"season": season, "limit": limit})
        if descriptor is None or not descriptor.capabilities.supports_odds:
            return self._finish_run(run, status="unavailable", error_category="permanent_error", errors=["historical odds unavailable from provider"])
        try:
            rows, _ = await self._fetch_pages(descriptor, ("historical_odds", "fetch_odds", "odds"), code=code, season=season, start_date=None, end_date=None, limit=min(limit, self.max_per_league))
        except Exception as error:
            return self._finish_run(run, status="unavailable", error_category=_error_category(error), errors=[str(error)])
        wanted = {str(value) for value in fixture_ids or ()}
        saver = getattr(self.repository, "save_odds_snapshot", None)
        inserted = rejected = 0
        for row in rows:
            run["records_seen"] += 1
            self._save_raw("odds", provider_name, row)
            fixture_id = _source_id(row, "fixture_id", "provider_fixture_id")
            if wanted and fixture_id not in wanted:
                continue
            captured = parse_timestamp(row.get("captured_at"))
            if captured is None:
                rejected += 1
                continue
            snapshot = dict(row)
            snapshot.setdefault("snapshot_id", _stable_id("odds", provider_name, fixture_id, captured.isoformat(), row.get("market")))
            snapshot.setdefault("fixture_id", fixture_id)
            snapshot.setdefault("source", provider_name)
            snapshot.setdefault("quotes", row.get("quotes") or [row])
            if callable(saver):
                saver(snapshot)
            inserted += 1
        return self._finish_run(run, records_inserted=inserted, records_rejected=rejected)

    async def sync_league_history(
        self,
        provider_name: str,
        league: str,
        season: Any,
        *,
        start_date: Any | None = None,
        end_date: Any | None = None,
        limit: int = 100,
        prediction_runner: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        leagues = await self.sync_leagues(provider_name)
        teams = await self.sync_teams(provider_name, league, season, limit=limit)
        fixtures = await self.sync_fixtures(provider_name, league, season, start_date=start_date, end_date=end_date, limit=limit)
        code = normalize_league_code(league)
        fixture_reader = getattr(self.repository, "fixture_identities", None)
        fixture_ids = [
            row.get("source_fixture_id")
            for row in fixture_reader(code, limit)
            if row.get("source_fixture_id") and str(row.get("season") or "") == str(season)
        ] if callable(fixture_reader) and code else []
        results = await self.sync_results(provider_name, league, season, fixture_ids=fixture_ids, limit=limit)
        odds = await self.sync_odds(provider_name, league, season, fixture_ids=fixture_ids, limit=limit)
        snapshots: list[dict[str, Any]] = []
        fixture_rows = self.repository.list_fixtures(league_key=code.casefold()) if code and callable(getattr(self.repository, "list_fixtures", None)) else []
        fixture_rows = [row for row in fixture_rows if str(row.get("season") or "") == str(season)]
        evidence_reader = getattr(self.repository, "evidence_snapshots", None)
        odds_reader = getattr(self.repository, "odds_snapshots", None)
        saver = getattr(self.repository, "save_historical_snapshot", None)
        backfill_results: list[dict[str, Any]] = []
        backfill_service = HistoricalBackfillService(self.repository, prediction_runner) if prediction_runner else None
        for fixture in fixture_rows[: self.max_per_league]:
            kickoff = parse_timestamp(fixture.get("kickoff"))
            if kickoff is None:
                continue
            as_of = kickoff - timedelta(hours=24)
            snapshot = build_historical_snapshot(
                fixture,
                as_of,
                evidence_snapshots=evidence_reader(fixture["id"]) if callable(evidence_reader) else [],
                odds_snapshots=odds_reader(fixture["id"]) if callable(odds_reader) else [],
                source_versions={"fixture": provider_name, "result": fixture.get("result_source"), "odds": provider_name if odds["status"] == "completed" else None},
            )
            if callable(saver):
                saver(snapshot)
            snapshots.append(snapshot)
            if backfill_service is not None:
                backfill_results.append(await backfill_service.backfill(fixture["id"], as_of))
        return {
            "status": "completed",
            "league": code,
            "leagues": leagues,
            "teams": teams,
            "fixtures": fixtures,
            "results": results,
            "odds": odds,
            "historical_snapshots": len(snapshots),
            "historical_predictions": backfill_results,
            "coverage": self.coverage(),
        }


def split_settlements_by_league(
    settlements: Iterable[Mapping[str, Any]],
    *,
    fixture_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Partition settlement rows into the three canonical P5 leagues."""

    grouped = {code: [] for code in SUPPORTED_LEAGUES}
    for row in settlements:
        item = dict(row)
        code = normalize_league_code(item.get("canonical_league") or item.get("league") or item.get("league_key"))
        if code is None and fixture_reader:
            fixture = fixture_reader(str(item.get("fixture_id") or ""))
            code = normalize_league_code((fixture or {}).get("canonical_league") or (fixture or {}).get("league_key"))
        if code:
            grouped[code].append(item)
    return grouped


def run_three_league_backtest(
    settlements: Iterable[Mapping[str, Any]],
    *,
    start: Any,
    end: Any,
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 30,
    fixture_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Reuse P4 rolling validation for independent and global P5 reports."""

    grouped = split_settlements_by_league(settlements, fixture_reader=fixture_reader)
    reports: dict[str, Any] = {}
    for code in SUPPORTED_LEAGUES:
        reports[code] = RollingBacktestService(grouped[code]).run(
            start=start,
            end=end,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
        )
    reports["global"] = RollingBacktestService([row for code in SUPPORTED_LEAGUES for row in grouped[code]]).run(
        start=start,
        end=end,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
    )
    reports["coverage"] = {code: len(grouped[code]) for code in SUPPORTED_LEAGUES}
    return reports


def public_registry(registry: P5ProviderRegistry) -> dict[str, Any]:
    return public_payload({"supported_leagues": SUPPORTED_LEAGUES, "providers": registry.as_dict(), "limits": {"per_league": DEFAULT_LEAGUE_LIMIT, "total": DEFAULT_TOTAL_LIMIT}})


# Public name used by the P5 operator/integration boundary.
DataSyncService = HistoricalLeagueDataService


__all__ = [
    "ALLOWED_FIXTURE_STATUSES",
    "DEFAULT_LEAGUE_LIMIT",
    "DEFAULT_TOTAL_LIMIT",
    "DataSyncService",
    "FixtureProvider",
    "HistoricalBackfillService",
    "HistoricalLeagueDataService",
    "LeagueProvider",
    "OddsProvider",
    "P5ProviderRegistry",
    "ProviderCapabilities",
    "ProviderDescriptor",
    "ResultProvider",
    "SUPPORTED_LEAGUES",
    "TeamProvider",
    "build_default_provider_registry",
    "canonical_fixture_id",
    "canonical_team_id",
    "fixture_source_conflicts",
    "normalize_fixture_status",
    "normalize_league_code",
    "provider_league_key",
    "public_registry",
    "run_three_league_backtest",
    "split_settlements_by_league",
]
