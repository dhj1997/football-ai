"""Public Dongqiudi adapter for schedules, odds, pre-match analysis and teams.

Only the public, free endpoints used by Dongqiudi's web application are read.  The
adapter intentionally ignores paid expert/tip endpoints and keeps the provider's
raw identifiers alongside normalized values.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from .data import CHINA_TZ
from .team_names import to_chinese_player_name, to_chinese_team_name


class DongqiudiProvider:
    """Fetch the small public dataset needed by the match workspace."""

    DEFAULT_BASE_URL = "https://www.dongqiudi.com"
    SPORT_DATA_BASE_URL = "https://beta-sport-data.dongdianqiu.com"
    API_BASE_URL = "https://beta-api.dongdianqiu.com"
    USER_AGENT = "football-ai/0.1 (+public-data-sync)"
    LEAGUE_NAMES = {
        "epl": "英超",
        "laliga": "西甲",
        "csl": "中超",
        "cfa_cup": "中国足协杯",
        "ucl": "欧冠",
        "acl": "亚冠",
        "world_cup": "世界杯",
        "asian_cup": "亚洲杯",
        "euro": "欧洲杯",
        "world_cup_qualifiers": "世预赛",
        "asian_qualifiers": "亚洲预选赛",
        "nations_league": "欧国联",
    }
    _SOURCE_BY_AREA = {"36": "bet365", "皇": "crown"}

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        sport_data_base_url: str = SPORT_DATA_BASE_URL,
        api_base_url: str = API_BASE_URL,
        timeout_seconds: float = 20,
    ) -> None:
        self.base_url = (self.DEFAULT_BASE_URL if base_url is None else base_url).rstrip("/")
        self.sport_data_base_url = (self.SPORT_DATA_BASE_URL if sport_data_base_url is None else sport_data_base_url).rstrip("/")
        self.api_base_url = (self.API_BASE_URL if api_base_url is None else api_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def fixtures(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        """Fetch the public match list and retain supported competitions in the window.

        ``match_list`` only serves the current match cycle, so days beyond it are
        read from ``schedule_list`` — the same endpoint the /match web page uses
        for its future-date tabs.
        """

        payloads = [
            await self._get_json(
                f"{self.base_url}/magicball/v1/list/match_list",
                params={"language": "zh-CN", "cmp_type": "soccer", "tab_type": "all"},
            )
        ]
        today = datetime.now(UTC).astimezone(CHINA_TZ).date()
        day = max(start_date, today + timedelta(days=1))
        while day <= end_date:
            payloads.append(
                await self._get_json(
                    f"{self.base_url}/magicball/v1/list/schedule_list",
                    params={
                        "language": "zh-CN",
                        "cmp_type": "soccer",
                        "tab_type": "fixture",
                        "start": f"{day.isoformat()} 00:00:00",
                    },
                )
            )
            day += timedelta(days=1)
        seen_match_ids: set[str] = set()
        mapped: list[dict[str, Any]] = []
        for payload in payloads:
            items = ((payload.get("data") or {}).get("matches") or [])
            for item in items:
                match_id = str(item.get("match_id") or "")
                if match_id and match_id in seen_match_ids:
                    continue
                league_key = self.normalize_league(item.get("competition") or {})
                if not league_key:
                    continue
                fixture = self._map_fixture(item, league_key)
                fixture_date = fixture.get("fixture_date")
                if fixture_date and start_date.isoformat() <= fixture_date <= end_date.isoformat():
                    seen_match_ids.add(match_id)
                    mapped.append(fixture)
        return sorted(mapped, key=lambda item: item["kickoff"])

    async def match_result(self, match_id: str | int) -> dict[str, Any]:
        """Read one match's current status and score from its public detail endpoint."""

        match_id = str(match_id)
        payload = await self._get_json(
            f"{self.base_url}/magicball/v1/match/app/detail",
            params={"id": match_id, "app": "dqd", "lang": "zh-cn"},
        )
        sample = payload.get("matchSample") or {}
        if not sample:
            raise RuntimeError(f"懂球帝比赛详情为空：{match_id}")
        home_score = _integer(sample.get("fs_A"))
        away_score = _integer(sample.get("fs_B"))
        status = _status(sample.get("status"))
        return {
            "match_id": match_id,
            "status": status,
            "provider_status": sample.get("status"),
            "score": {"home": home_score, "away": away_score}
            if home_score is not None and away_score is not None
            else None,
            "captured_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }

    async def odds(self, match_id: str | int) -> dict[str, Any]:
        """Return only Bet365 and Crown European/Asian/over-under odds."""

        match_id = str(match_id)
        payload = await self._get_json(
            f"{self.sport_data_base_url}/soccer/biz/dqd/v1/match/odds/index/{match_id}",
            params={"app": "dqd", "lang": "zh-cn", "cmp_type": "soccer", "version": "", "platform": "android", "app_type": "dqd"},
        )
        captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        bookmakers: dict[str, dict[str, Any]] = {}
        for market_key, market_name in (("euro", "1x2"), ("asia", "asian_handicap"), ("size", "over_under")):
            for item in payload.get(market_key) or []:
                bookmaker_key = self._SOURCE_BY_AREA.get(str(item.get("area") or "").strip())
                if not bookmaker_key:
                    continue
                bookmakers.setdefault(bookmaker_key, {"name": "Bet365" if bookmaker_key == "bet365" else "皇冠", "source": "dongqiudi", "match_id": match_id})
                bookmakers[bookmaker_key][market_name] = {
                    "initial": self._map_odds_state(item.get("begin") or {}, market_name),
                    "current": self._map_odds_state(item.get("now") or {}, market_name),
                    "provider_name": item.get("name"),
                    "area": item.get("area"),
                    "cid": item.get("cid"),
                    "fixed_odds": item.get("fixed_odds"),
                }
        # The public odds response often omits the per-quote timestamp. The
        # response capture time is still a trustworthy freshness boundary for
        # the quote we just received.
        for bookmaker in bookmakers.values():
            for market_name in ("1x2", "asian_handicap"):
                current = ((bookmaker.get(market_name) or {}).get("current") or {})
                if current and not current.get("updated_at"):
                    current["updated_at"] = captured_at
        return {
            "source": "dongqiudi",
            "match_id": match_id,
            "captured_at": captured_at,
            "updated_at": captured_at,
            "bookmakers": bookmakers,
        }

    async def pre_match_analysis(self, match_id: str | int) -> dict[str, Any]:
        """Fetch free analysis datasets; paid expert recommendation endpoints are excluded."""

        match_id = str(match_id)
        urls = [
            (
                "pre_analysis",
                f"{self.api_base_url}/data/match/pre_analysis_v1/{match_id}",
                {"platform": "", "version": "", "android-channel": ""},
            ),
            (
                "contrast",
                f"{self.sport_data_base_url}/soccer/biz/dqd/match/pre_analyze_data_contrast/{match_id}",
                {"app": "dqd"},
            ),
            (
                "h2h",
                f"{self.sport_data_base_url}/soccer/data/match/h2h",
                {"match_id": match_id, "lang": "zh-cn"},
            ),
        ]
        responses = await asyncio.gather(*(self._get_json(url, params=params) for _, url, params in urls), return_exceptions=True)
        errors = [str(item)[:240] for item in responses if isinstance(item, Exception)]
        normalized = [item if isinstance(item, dict) else {} for item in responses]
        return {
            "source": "dongqiudi",
            "match_id": match_id,
            "captured_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "pre_analysis": normalized[0],
            "contrast": normalized[1].get("data") or normalized[1],
            "h2h": normalized[2].get("data") or normalized[2],
            "errors": errors,
        }

    async def enrich_match(self, match_id: str | int) -> dict[str, Any]:
        odds, analysis = await asyncio.gather(self.odds(match_id), self.pre_match_analysis(match_id), return_exceptions=True)
        if isinstance(odds, Exception) and isinstance(analysis, Exception):
            raise RuntimeError(f"赔率和赛前分析均失败：{odds}; {analysis}")
        return {"odds": {} if isinstance(odds, Exception) else odds, "dongqiudi_analysis": {"errors": [str(odds)[:240]]} if isinstance(analysis, Exception) else analysis}

    async def team(self, team_id: str | int) -> dict[str, Any]:
        """Fetch the public team profile and one-time roster."""

        team_id = str(team_id)
        profile, roster = await asyncio.gather(
            self._get_json(f"{self.base_url}/api/data/v1/detail/team/{team_id}", params={"app": "dqd", "lang": "zh-cn"}),
            self._get_json(f"{self.sport_data_base_url}/soccer/biz/dqd/v1/team/member_v2/{team_id}", params={"app": "dqd"}),
        )
        base = profile.get("base_info") or profile.get("base_info_v_1") or {}
        if not base:
            raise RuntimeError(f"Dongqiudi returned incomplete team profile: {team_id}")
        sections = ((roster.get("data") or {}).get("list") or [])
        players: list[dict[str, Any]] = []
        coaches: list[dict[str, Any]] = []
        for section in sections:
            title = section.get("title") or section.get("type") or ""
            target = coaches if "教练" in title or "工作人员" in title else players
            for item in section.get("data") or []:
                original_name = str(item.get("person_name") or "未知球员")
                mapped = {
                    "id": str(item.get("person_id") or ""),
                    "provider_player_id": str(item.get("person_id") or "") or None,
                    "name": to_chinese_player_name(original_name),
                    "original_name": original_name,
                    "age": _age(item.get("age")),
                    "position": title or item.get("type") or "未知位置",
                    "nationality": item.get("nationality_name"),
                    "photo": item.get("person_logo") or None,
                    "market_value": None,
                    "market_value_currency": "EUR",
                    "market_value_source": None,
                }
                target.append(mapped)
        return {
            "team_id": team_id,
            "team": {
                "name": to_chinese_team_name(base.get("team_name") or "未知球队"),
                "original_name": base.get("team_en_name") or base.get("team_name") or "未知球队",
                "logo": base.get("team_logo"),
                "country": base.get("country"),
                "city": base.get("city"),
                "founded": _integer(base.get("founded")),
                "venue": base.get("venue_name"),
                "capacity": _integer(base.get("venue_capacity")),
                "description": base.get("description"),
                "market_value": base.get("market_value"),
            },
            "roster": players,
            "coach": coaches,
            "roster_count": len(players),
            "source": "dongqiudi",
            "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "raw_profile": profile,
        }

    @classmethod
    def normalize_league(cls, competition: dict[str, Any]) -> str | None:
        name = str(competition.get("name") or "").strip().casefold()
        area = str(competition.get("area_name") or "").strip().casefold()
        if "中超" in name:
            return "csl"
        if name in {"足协杯", "中国足协杯", "china fa cup", "chinese fa cup", "fa cup china"}:
            if not area or area in {"中国", "china", "中国大陆", "mainland china"}:
                return "cfa_cup"
        if name in {"欧冠", "欧洲冠军联赛", "uefa champions league", "champions league"} and area in {"欧洲", "europe"}:
            return "ucl"
        if name in {"亚冠", "亚冠联赛", "亚冠精英", "亚冠精英联赛", "亚冠二级", "亚冠二级联赛", "afc champions league"} and area in {"亚洲", "asia"}:
            return "acl"
        if name in {"世界杯", "fifa world cup", "world cup"} and area in {"世界", "world", "国际", "international"}:
            return "world_cup"
        if name in {"亚洲杯", "亚洲足球杯", "afc asian cup", "asian cup"} and area in {"亚洲", "asia"}:
            return "asian_cup"
        if name in {"欧洲杯", "欧洲足球锦标赛", "uefa euro", "european championship"} and area in {"欧洲", "europe"}:
            return "euro"
        if name in {"世预赛", "世界杯预选赛", "世界杯资格赛", "fifa world cup qualifiers", "world cup qualifiers"}:
            return "world_cup_qualifiers"
        if name in {"亚洲预选赛", "亚洲区预选赛", "亚洲世预赛", "afc qualifiers", "asian qualifiers"}:
            return "asian_qualifiers"
        if name in {"欧国联", "欧洲国家联赛", "uefa nations league", "nations league"} and area in {"欧洲", "europe"}:
            return "nations_league"
        if "英超" in name or "premier league" in name:
            return "epl"
        if "西甲" in name or "laliga" in name or "la liga" in name:
            return "laliga"
        return None

    @classmethod
    def _map_fixture(cls, item: dict[str, Any], league_key: str) -> dict[str, Any]:
        timestamp = _integer(item.get("match_timestamp"))
        if timestamp:
            kickoff = datetime.fromtimestamp(timestamp, UTC)
        else:
            kickoff = datetime.fromisoformat(str(item.get("start_play") or "").replace("Z", "+00:00")).replace(tzinfo=UTC)
        competition = item.get("competition") or {}
        home = item.get("team_A") or {}
        away = item.get("team_B") or {}
        return {
            "id": f"dongqiudi-{item.get('match_id')}",
            "provider_id": _integer(item.get("match_id")),
            "external_ids": {"dongqiudi": str(item.get("match_id") or "")},
            "source": "dongqiudi",
            "league_key": league_key,
            "league": {"id": _integer(competition.get("id")) or 0, "name": cls.LEAGUE_NAMES[league_key], "country": competition.get("area_name") or "中国", "mark": league_key.upper()},
            "fixture_date": kickoff.astimezone(CHINA_TZ).date().isoformat(),
            "kickoff": kickoff.isoformat(),
            "status": _status(item.get("status")),
            "provider_status": item.get("status"),
            "home_team": {"provider_id": _integer(home.get("id")), "name": to_chinese_team_name(home.get("name") or "待定"), "original_name": home.get("name") or "待定", "code": (home.get("name") or "待定")[:3].upper(), "logo": home.get("logo")},
            "away_team": {"provider_id": _integer(away.get("id")), "name": to_chinese_team_name(away.get("name") or "待定"), "original_name": away.get("name") or "待定", "code": (away.get("name") or "待定")[:3].upper(), "logo": away.get("logo")},
            "score": {"home": _integer(home.get("fs")), "away": _integer(away.get("fs"))} if _integer(home.get("fs")) is not None and _integer(away.get("fs")) is not None else None,
            "venue": "待定",
            "lineup_confirmed": False,
            "is_demo": False,
        }

    @staticmethod
    def _map_odds_state(state: dict[str, Any], market: str) -> dict[str, Any]:
        if market == "1x2":
            return {"home": _number(state.get("homeWin")), "draw": _number(state.get("draw")), "away": _number(state.get("awayWin")), "updated_at": _epoch_iso(state.get("ts"))}
        if market == "over_under":
            # size market: homeWin = over water, awayWin = under water, draw = line.
            return {"over_odd": _hongkong_water_to_decimal(state.get("homeWin")), "under_odd": _hongkong_water_to_decimal(state.get("awayWin")), "line": _over_under_line(state), "updated_at": _epoch_iso(state.get("ts"))}
        # Asian prices arrive as Hong Kong water (e.g. 0.93 = win pays 0.93 per
        # unit). The pipeline prices handicap rows in decimal odds, so convert.
        return {"home_odd": _hongkong_water_to_decimal(state.get("homeWin")), "away_odd": _hongkong_water_to_decimal(state.get("awayWin")), "label": state.get("draw"), "line": _number(state.get("draw_value")), "updated_at": _epoch_iso(state.get("ts"))}

    async def _get_json(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"}) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Dongqiudi returned a non-object response")
        return payload


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _hongkong_water_to_decimal(value: Any) -> float | None:
    number = _number(value)
    return round(number + 1, 4) if number is not None else None


def _over_under_line(state: dict[str, Any]) -> float | None:
    """Resolve the total-goals line: numeric field first, then the label,
    which may be a compound goal line like "2.5/3" (= 2.75)."""

    direct = _number(state.get("draw_value"))
    if direct is not None:
        return direct
    raw = str(state.get("draw") or "").strip()
    if "/" in raw:
        parts = [_number(part) for part in raw.split("/")]
        if parts and all(value is not None for value in parts):
            return round(sum(parts) / len(parts), 4)
        return None
    return _number(raw)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _epoch_iso(value: Any) -> str | None:
    timestamp = _integer(value)
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else None


def _age(value: Any) -> int | None:
    raw = str(value or "").replace("岁", "").strip()
    return _integer(raw)


def _status(value: Any) -> str:
    raw = str(value or "").casefold()
    if "postpon" in raw:
        return "postponed"
    if "cancel" in raw:
        return "cancelled"
    if raw in {"fixture", "scheduled", "not started"}:
        return "scheduled"
    if raw in {"finished", "ended", "ft", "aet", "pen", "played", "match finished", "full time"}:
        return "finished"
    if raw in {"live", "playing", "1h", "2h", "ht"}:
        return "live"
    return "scheduled"
