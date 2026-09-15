from datetime import UTC, datetime, timedelta

import pytest

from app.dongqiudi_provider import DongqiudiProvider
from app.data import CHINA_TZ
from app.dongqiudi_sync import DongqiudiSyncService, _dongqiudi_recent_matches, odds_fingerprint


def test_dongqiudi_does_not_map_malaysia_fa_cup_to_china_fa_cup() -> None:
    assert DongqiudiProvider.normalize_league({"name": "马足协杯", "area_name": "马来西亚"}) is None
    assert DongqiudiProvider.normalize_league({"name": "中国足协杯", "area_name": "中国"}) == "cfa_cup"


def test_dongqiudi_maps_requested_international_competitions() -> None:
    assert DongqiudiProvider.normalize_league({"name": "欧冠", "area_name": "欧洲"}) == "ucl"
    assert DongqiudiProvider.normalize_league({"name": "亚冠精英", "area_name": "亚洲"}) == "acl"
    assert DongqiudiProvider.normalize_league({"name": "世界杯", "area_name": "世界"}) == "world_cup"
    assert DongqiudiProvider.normalize_league({"name": "U20女足世界杯", "area_name": "世界"}) is None
    assert DongqiudiProvider.normalize_league({"name": "欧国联", "area_name": "欧洲"}) == "nations_league"


def test_dongqiudi_maps_supported_fixture_from_epoch() -> None:
    result = DongqiudiProvider._map_fixture(
        {
            "match_id": "54524981",
            "match_timestamp": 1788350400,
            "status": "Fixture",
            "competition": {"id": "200", "name": "中国足协杯", "area_name": "中国"},
            "team_A": {"id": "117905", "name": "云南玉昆", "logo": "home.png"},
            "team_B": {"id": "117906", "name": "上海海港", "logo": "away.png"},
        },
        "cfa_cup",
    )

    assert result["id"] == "dongqiudi-54524981"
    assert result["external_ids"]["dongqiudi"] == "54524981"
    assert result["status"] == "scheduled"
    assert result["kickoff"] == datetime.fromtimestamp(1788350400, UTC).isoformat()
    assert result["home_team"]["provider_id"] == 117905


def test_dongqiudi_maps_played_fixture_to_finished_with_score() -> None:
    result = DongqiudiProvider._map_fixture(
        {
            "match_id": "54493217",
            "match_timestamp": 1788796800,
            "status": "Played",
            "competition": {"id": "87", "name": "西甲", "area_name": "西班牙"},
            "team_A": {"id": "1778", "name": "赫塔费", "fs": "1"},
            "team_B": {"id": "1772", "name": "塞尔塔", "fs": "1"},
        },
        "laliga",
    )

    assert result["status"] == "finished"
    assert result["score"] == {"home": 1, "away": 1}


@pytest.mark.asyncio
async def test_dongqiudi_match_result_maps_detail_sample() -> None:
    class Provider(DongqiudiProvider):
        async def _get_json(self, url, *, params):
            assert params["id"] == "54493217"
            return {"matchSample": {"status": "Played", "fs_A": "1", "fs_B": "1"}}

    result = await Provider().match_result("54493217")

    assert result["status"] == "finished"
    assert result["score"] == {"home": 1, "away": 1}


@pytest.mark.asyncio
async def test_dongqiudi_fetch_lineup_maps_real_lineups_and_ignores_forecasts() -> None:
    class Provider(DongqiudiProvider):
        async def _get_json(self, url, *, params):
            assert url.endswith("/soccer/biz/dqd/v1/match/lineup/54565712")
            assert params == {"app": "dqd", "lang": "zh-cn"}
            return {
                "persons": {
                    "team_A": {
                        "formation": "4-3-3",
                        "lineups": [{"person_id": 1, "person": "John Doe", "shirtnumber": "9", "position": "前锋"}],
                        "sub": [{"person_id": 2, "person": "替补甲", "shirtnumber": "12", "position": "门将"}],
                        "forecasts": [{"person_id": 3, "person": "预测甲"}],
                    },
                    "team_B": {
                        "formation": "4-2-3-1",
                        "lineups": [{"person_id": 4, "person": "首发乙", "shirtnumber": "10", "position": "中场"}],
                        "sub": None,
                        "forecasts": [{"person_id": 5, "person": "预测乙"}],
                    },
                }
            }

    result = await Provider().fetch_lineup({"external_ids": {"dongqiudi": "54565712"}})

    lineup = result["lineup"]
    assert result["source"] == "dongqiudi-lineup"
    assert lineup["confirmed"] is True
    assert lineup["home_formation"] == "4-3-3"
    assert [row["starter"] for row in lineup["home_players"]] == [True, False]
    assert lineup["home_players"][0]["provider_player_id"] == "1"
    assert lineup["home_players"][0]["name"] != "John Doe"
    assert all(row["name"] != "预测甲" for row in lineup["home_players"])


@pytest.mark.asyncio
async def test_dongqiudi_fetch_lineup_keeps_unpublished_lineup_unconfirmed() -> None:
    class Provider(DongqiudiProvider):
        async def _get_json(self, url, *, params):
            return {"persons": {"team_A": {"lineups": None}, "team_B": {"lineups": []}}}

    result = await Provider().fetch_lineup({"id": "dongqiudi-54565712"})

    assert result["lineup"]["confirmed"] is False
    assert result["lineup"]["home_players"] == []
    assert result["lineup"]["updated_at"] is None


@pytest.mark.asyncio
async def test_dongqiudi_score_sync_updates_existing_fixture_only() -> None:
    # The score sync only touches fixtures inside the rolling window
    # (Beijing yesterday -> +36h), so the fixture must be dated in-window.
    in_window_date = datetime.now(CHINA_TZ).date().isoformat()

    class Provider:
        configured = True

        async def fixtures(self, start_date, end_date):
            return []

        async def match_result(self, match_id):
            return {
                "match_id": match_id,
                "status": "finished",
                "provider_status": "Played",
                "score": {"home": 1, "away": 1},
            }

    class Repository:
        def __init__(self):
            self.fixture = {
                "id": "sportsdb-2506206",
                "external_ids": {"dongqiudi": "54493217"},
                "league_key": "laliga",
                "fixture_date": in_window_date,
                "kickoff": "2026-09-07T17:00:00+00:00",
                "status": "scheduled",
                "provider_status": "Fixture",
                "score": None,
                "home_team": {"name": "赫塔费"},
                "away_team": {"name": "维戈塞尔塔"},
                "evidence": {"synced_at": "2026-09-08T00:00:00+00:00"},
                "predictions": [{"id": "prediction-1"}],
            }
            self.updates = []

        def list_fixtures(self, league_key=None):
            return [self.fixture]

        def upsert_fixture(self, fixture, synced_at=None):
            self.fixture = fixture
            self.updates.append(fixture)

    repository = Repository()
    service = DongqiudiSyncService(Provider(), repository)

    result = await service.sync_scores()

    assert result["item_count"] == 1
    assert len(repository.updates) == 1
    assert repository.fixture["id"] == "sportsdb-2506206"
    assert repository.fixture["status"] == "finished"
    assert repository.fixture["score"] == {"home": 1, "away": 1}
    assert repository.fixture["evidence"]["synced_at"] == "2026-09-08T00:00:00+00:00"
    assert repository.fixture["predictions"] == [{"id": "prediction-1"}]


def test_dongqiudi_odds_state_normalizes_european_and_asian_fields() -> None:
    european = DongqiudiProvider._map_odds_state({"homeWin": "1.77", "draw": "3.70", "awayWin": "3.50"}, "1x2")
    asian = DongqiudiProvider._map_odds_state({"homeWin": "0.98", "awayWin": "0.88", "draw": "半/一", "draw_value": "0.75"}, "asian_handicap")

    assert european == {"home": 1.77, "draw": 3.70, "away": 3.50, "updated_at": None}
    assert asian["line"] == 0.75
    assert asian["label"] == "半/一"
    # Dongqiudi asian prices are Hong Kong water; the pipeline needs decimal.
    assert asian["home_odd"] == 1.98
    assert asian["away_odd"] == 1.88


def test_dongqiudi_asian_state_keeps_receiving_and_level_lines() -> None:
    receiving = DongqiudiProvider._map_odds_state({"homeWin": "0.80", "awayWin": "1.00", "draw": "受平/半", "draw_value": "-0.25"}, "asian_handicap")
    level = DongqiudiProvider._map_odds_state({"homeWin": "0.97", "awayWin": "0.73", "draw": "平手", "draw_value": "0.00"}, "asian_handicap")

    assert receiving["line"] == -0.25
    assert level["line"] == 0.0


@pytest.mark.asyncio
async def test_dongqiudi_odds_uses_capture_time_when_quote_timestamp_is_missing() -> None:
    class Provider(DongqiudiProvider):
        async def _get_json(self, url, *, params):
            return {
                "euro": [{"area": "36", "begin": {}, "now": {"homeWin": "1.8", "draw": "3.6", "awayWin": "4.2"}}],
                "asia": [],
            }

    result = await Provider().odds("54524981")
    current = result["bookmakers"]["bet365"]["1x2"]["current"]

    assert current["updated_at"] == result["captured_at"]


def test_dongqiudi_sync_keeps_both_bookmakers_and_prefers_primary_source() -> None:
    class Repository:
        def __init__(self) -> None:
            self.snapshots = []

        def save_odds_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

    provider = DongqiudiProvider()
    repository = Repository()
    service = DongqiudiSyncService(provider, repository)
    fixture = {
        "id": "dongqiudi-1",
        "external_ids": {"dongqiudi": "1"},
        "home_team": {"name": "主队"},
        "away_team": {"name": "客队"},
        "evidence": None,
    }
    enriched = {
        "odds": {
            "match_id": "1",
            "captured_at": "2026-09-02T12:00:00+00:00",
            "bookmakers": {
                "crown": {"name": "市场参考B", "1x2": {"current": {"home": 1.8, "draw": 3.6, "away": 4.2}, "initial": {}}, "asian_handicap": {"current": {"line": 0.5, "label": "半球", "home_odd": 0.9, "away_odd": 0.9}, "initial": {}}},
                "bet365": {"name": "市场参考A", "1x2": {"current": {"home": 1.7, "draw": 3.8, "away": 4.5}, "initial": {}}, "asian_handicap": {"current": {"line": 0.5, "label": "半球", "home_odd": 0.95, "away_odd": 0.85}, "initial": {}}},
            },
        },
        "dongqiudi_analysis": {"match_id": "1"},
    }

    updated = service._apply_match_data(fixture, enriched, "initial")
    assert updated["evidence"]["odds"]["bookmaker"] == "市场参考A"
    assert updated["evidence"]["odds"]["asian_handicap"] == -0.5
    assert set(updated["evidence"]["odds_by_bookmaker"]) == {"bet365", "crown"}
    assert updated["dongqiudi_sync"]["initial_synced_at"]
    assert len(repository.snapshots) == 2


def test_dongqiudi_analysis_populates_detail_evidence_without_overwriting_existing() -> None:
    class Repository:
        def save_odds_snapshot(self, snapshot):
            pass

    fixture = {
        "id": "dongqiudi-54577341",
        "external_ids": {"dongqiudi": "54577341"},
        "home_team": {"name": "那不勒斯"},
        "away_team": {"name": "阿森纳"},
        "evidence": {
            "recent_form": {"home": [{"result": "D"}], "away": []},
            "head_to_head": [],
            "availability": {"players": [], "updated_at": None},
        },
    }
    enriched = {
        "odds": {},
        "dongqiudi_analysis": {
            "pre_analysis": {
                "recent_record": {
                    "team_A": [
                        {
                            "start_time": "2026-09-05 16:00:00",
                            "team_A_name": "国际米兰",
                            "team_B_name": "那不勒斯",
                            "score": "3-2",
                            "main_team": "team_B",
                            "color": "win",
                        }
                    ],
                    "team_B": [
                        {
                            "start_time": "2026-09-06 15:30:00",
                            "team_A_name": "阿森纳",
                            "team_B_name": "切尔西",
                            "score": "2-1",
                            "main_team": "team_A",
                            "color": "win",
                        }
                    ],
                },
                "battle_history": {
                    "list": [
                        {
                            "start_time": "2019-04-18 19:00:00",
                            "team_A_name": "那不勒斯",
                            "team_B_name": "阿森纳",
                            "score": "0-1",
                        }
                    ]
                },
                "sideline": {
                    "team_A": [{"name": "麦克托米奈", "href": "dongqiudi:///player/50391373", "reason": "受伤"}],
                    "team_B": [{"name": "萨利巴", "href": "dongqiudi:///player/50458226", "reason": "受伤"}],
                },
            }
        },
    }

    updated = DongqiudiSyncService(object(), Repository())._apply_match_data(fixture, enriched, "initial")
    context = updated["evidence"]

    assert len(context["recent_form"]["home"]) == 1
    assert context["recent_form"]["away"][0]["result"] == "W"
    assert context["recent_form"]["home"][0] == {"result": "D"}
    assert context["recent_form"]["away"][0]["team_is_home"] is True
    assert context["recent_form"]["away_points_per_game"] == 3.0
    assert context["head_to_head"][0] == {
        "date": "2019-04-18",
        "home": "那不勒斯",
        "away": "阿森纳",
        "score": "0 - 1",
        "competition": None,
        "half_time": None,
    }
    assert context["availability"]["home_missing"] == 1
    assert context["availability"]["away_missing"] == 1
    assert context["availability"]["players"][0]["name"] == "麦克托米奈"
    assert context["availability"]["players"][0]["provider_player_id"] == "50391373"


def test_dongqiudi_recent_form_keeps_ten_rows_and_reads_h2h_fallback() -> None:
    rows = [
        {
            "start_time": f"2026-08-{30 - index:02d} 12:00:00",
            "team_A_name": "主队",
            "team_B_name": "对手",
            "score": "1-0",
            "main_team": "team_A",
            "color": "win",
        }
        for index in range(11)
    ]
    mapped = _dongqiudi_recent_matches(rows, "team_A")

    assert len(mapped) == 10
    assert all(row["result"] == "W" for row in mapped)

    fixture = {
        "id": "dongqiudi-2",
        "external_ids": {"dongqiudi": "2"},
        "home_team": {"name": "主队"},
        "away_team": {"name": "对手"},
        "evidence": None,
    }
    enriched = {
        "odds": {},
        "dongqiudi_analysis": {
            "pre_analysis": {
                "recent_record": {"team_A": [], "team_B": []},
                "battle_history": {"list": []},
            },
            "h2h": {
                "list": [
                    {
                        "start_time": "2024-01-01 12:00:00",
                        "team_A_name": "主队",
                        "team_B_name": "对手",
                        "score": "2-1",
                    }
                ]
            },
        },
    }

    class Repository:
        def save_odds_snapshot(self, snapshot):
            pass

    updated = DongqiudiSyncService(object(), Repository())._apply_match_data(fixture, enriched, "initial")

    assert updated["evidence"]["head_to_head"] == [
        {"date": "2024-01-01", "home": "主队", "away": "对手", "score": "2 - 1", "competition": None, "half_time": None}
    ]


def test_dongqiudi_sync_does_not_treat_other_sources_as_dongqiudi() -> None:
    assert DongqiudiSyncService._source_match_id({"id": "sportsdb-42"}) is None
    assert DongqiudiSyncService._source_match_id({"id": "dongqiudi-42"}) == "42"


def test_dongqiudi_sync_matches_provider_aliases() -> None:
    incoming = {
        "league_key": "uel",
        "kickoff": "2026-09-10T16:45:00+00:00",
        "home_team": {"name": "PSV埃因霍温"},
        "away_team": {"name": "顿涅茨克矿工"},
    }
    existing = {
        "id": "sportsdb-2594585",
        "league_key": "uel",
        "kickoff": "2026-09-10T16:45:00+00:00",
        "home_team": {"name": "埃因霍温"},
        "away_team": {"name": "顿涅茨克矿工"},
    }

    class Repository:
        def list_fixtures(self, league_key=None):
            return [existing]

    assert DongqiudiSyncService( object(), Repository())._find_existing(incoming) == existing


def test_dongqiudi_sync_matches_zhejiang_suffix_alias() -> None:
    incoming = {
        "league_key": "csl",
        "kickoff": "2026-09-18T11:35:00+00:00",
        "home_team": {"name": "浙江"},
        "away_team": {"name": "武汉三镇"},
    }
    existing = {
        "id": "sportsdb-2434546",
        "league_key": "csl",
        "kickoff": "2026-09-18T11:35:00+00:00",
        "home_team": {"name": "浙江队"},
        "away_team": {"name": "武汉三镇"},
    }

    class Repository:
        def list_fixtures(self, league_key=None):
            return [existing]

    assert DongqiudiSyncService(object(), Repository())._find_existing(incoming) == existing


@pytest.mark.asyncio
async def test_dongqiudi_prematch_due_uses_24h_phase() -> None:
    kickoff = datetime.now(UTC) + timedelta(hours=12)

    class Provider:
        configured = True

        def __init__(self):
            self.odds_calls = 0
            self.enrich_calls = 0

        async def odds(self, match_id):
            self.odds_calls += 1
            return {"match_id": match_id}

        async def enrich_match(self, match_id):
            self.enrich_calls += 1
            return {"odds": {"match_id": match_id}, "dongqiudi_analysis": {}}

    class Repository:
        def __init__(self):
            self.fixture_data = {
                "id": "sportsdb-1",
                "external_ids": {"dongqiudi": "54577351"},
                "kickoff": kickoff.isoformat(),
                "dongqiudi_sync": {},
                "evidence": {},
            }
            self.calls = []

        def list_fixtures(self):
            return [self.fixture_data]

        def fixture(self, fixture_id):
            return self.fixture_data if fixture_id == self.fixture_data["id"] else None

        def upsert_fixture(self, fixture, synced_at=None):
            self.fixture_data = fixture
            self.calls.append(fixture)

        def save_odds_snapshot(self, snapshot):
            pass

        def team_snapshot(self, league_key, team_id):
            return None

    repository = Repository()
    result = await DongqiudiSyncService(Provider(), repository, prematch_lead_hours=24).sync_prematch_due()

    assert result["candidate_count"] == 1
    assert repository.fixture_data["dongqiudi_sync"]["prematch_24h_synced_at"]


def test_odds_fingerprint_ignores_capture_time_but_tracks_price_changes() -> None:
    first = {
        "bookmaker": "市场参考A",
        "home": 1.8,
        "draw": 3.6,
        "away": 4.2,
        "asian_handicap": -0.5,
        "asian_handicap_home_odd": 0.9,
        "asian_handicap_away_odd": 0.9,
        "captured_at": "2026-09-15T00:00:00+00:00",
        "updated_at": "2026-09-15T00:00:00+00:00",
    }
    same_prices = {**first, "captured_at": "2026-09-15T00:15:00+00:00", "updated_at": "2026-09-15T00:15:00+00:00"}
    changed_price = {**same_prices, "home": 1.75}

    assert odds_fingerprint(first) == odds_fingerprint(same_prices)
    assert odds_fingerprint(first) != odds_fingerprint(changed_price)


@pytest.mark.asyncio
async def test_dongqiudi_prematch_due_repeats_inside_expanded_window() -> None:
    kickoff = datetime.now(UTC) + timedelta(hours=5)

    class Provider:
        configured = True

        def __init__(self):
            self.odds_calls = 0
            self.enrich_calls = 0

        async def odds(self, match_id):
            self.odds_calls += 1
            return {"match_id": match_id}

        async def enrich_match(self, match_id):
            self.enrich_calls += 1
            return {"odds": {"match_id": match_id}, "dongqiudi_analysis": {}}

    class Repository:
        def __init__(self):
            self.fixture_data = {
                "id": "sportsdb-prematch-window",
                "external_ids": {"dongqiudi": "54577352"},
                "kickoff": kickoff.isoformat(),
                "dongqiudi_sync": {},
                "evidence": {},
            }

        def list_fixtures(self):
            return [self.fixture_data]

        def fixture(self, fixture_id):
            return self.fixture_data if fixture_id == self.fixture_data["id"] else None

        def upsert_fixture(self, fixture, synced_at=None):
            self.fixture_data = fixture

        def save_odds_snapshot(self, snapshot):
            pass

        def team_snapshot(self, league_key, team_id):
            return None

    provider = Provider()
    repository = Repository()
    service = DongqiudiSyncService(
        provider,
        repository,
        prematch_window_minutes=360,
        prematch_refresh_minutes=15,
    )

    first = await service.sync_prematch_due()
    assert first["candidate_count"] == 1
    assert repository.fixture_data["dongqiudi_sync"]["prematch_synced_at"]

    repository.fixture_data["dongqiudi_sync"]["prematch_synced_at"] = (
        datetime.now(UTC) - timedelta(minutes=16)
    ).isoformat()
    second = await service.sync_prematch_due()
    assert second["candidate_count"] == 1
    assert provider.odds_calls == 2
    assert provider.enrich_calls == 0


@pytest.mark.asyncio
async def test_fixtures_fetch_future_days_from_schedule_list() -> None:
    """match_list only covers the current cycle; future dates must come from
    schedule_list so fixtures beyond tomorrow morning still get matched."""

    class Provider(DongqiudiProvider):
        base_url = DongqiudiProvider.DEFAULT_BASE_URL

        def __init__(self):
            self.calls = []

        async def _get_json(self, url, *, params):
            self.calls.append((url, dict(params)))
            if url.endswith("/schedule_list"):
                assert params["tab_type"] == "fixture"
                assert params["start"].startswith(("2099-08-26", "2099-08-27", "2099-08-28"))
                return {"data": {"matches": [{
                    "match_id": "54483630",
                    "match_timestamp": int(datetime(2099, 8, 28, 4, 0, tzinfo=UTC).timestamp()),
                    "status": "Fixture",
                    "competition": {"id": "1", "name": "英超", "area_name": "英格兰"},
                    "team_A": {"id": "31", "name": "伯恩茅斯"},
                    "team_B": {"id": "90", "name": "布伦特福德"},
                }]}}
            return {"data": {"matches": [{
                "match_id": "54493234",
                "match_timestamp": int(datetime(2099, 8, 27, 4, 0, tzinfo=UTC).timestamp()),
                "status": "Fixture",
                "competition": {"id": "3", "name": "西甲", "area_name": "西班牙"},
                "team_A": {"id": "1760", "name": "塞维利亚"},
                "team_B": {"id": "1754", "name": "瓦伦西亚"},
            }]}}

    provider = Provider()
    rows = await provider.fixtures(datetime(2099, 8, 26).date(), datetime(2099, 8, 28).date())

    assert any(url.endswith("/schedule_list") for url, _ in provider.calls)
    ids = {row["external_ids"]["dongqiudi"] for row in rows}
    assert ids == {"54493234", "54483630"}
    assert all("2099-08-26" <= row["fixture_date"] <= "2099-08-28" for row in rows)


def test_dongqiudi_native_csl_names_normalize_to_storage_names() -> None:
    """Dongqiudi omits the 队 suffix used by canonical CSL fixtures."""

    from app.team_names import to_chinese_team_name

    assert to_chinese_team_name("河南") == "河南队"
    assert to_chinese_team_name("Henan") == "河南队"
    assert to_chinese_team_name("浙江") == "浙江队"
    assert to_chinese_team_name("Zhejiang FC") == "浙江队"


def test_dongqiudi_over_under_state_normalizes_water_and_line() -> None:
    state = DongqiudiProvider._map_odds_state({"homeWin": "0.70", "awayWin": "0.92", "draw": "2.5"}, "over_under")

    assert state == {"over_odd": 1.70, "under_odd": 1.92, "line": 2.5, "updated_at": None}


def test_dongqiudi_sync_persists_over_under_odds() -> None:
    class Repository:
        def __init__(self) -> None:
            self.snapshots = []

        def save_odds_snapshot(self, snapshot):
            self.snapshots.append(snapshot)

    provider = DongqiudiProvider()
    repository = Repository()
    service = DongqiudiSyncService(provider, repository)
    fixture = {
        "id": "dongqiudi-1",
        "external_ids": {"dongqiudi": "1"},
        "home_team": {"name": "主队"},
        "away_team": {"name": "客队"},
        "evidence": None,
    }
    enriched = {
        "odds": {
            "match_id": "1",
            "captured_at": "2026-09-02T12:00:00+00:00",
            "bookmakers": {
                "bet365": {
                    "name": "市场参考A",
                    "1x2": {"current": {"home": 1.7, "draw": 3.8, "away": 4.5}, "initial": {}},
                    "asian_handicap": {"current": {"line": 0.5, "label": "半球", "home_odd": 1.9, "away_odd": 1.9}, "initial": {}},
                    "over_under": {"current": {"line": 2.5, "over_odd": 1.85, "under_odd": 1.95}, "initial": {}},
                },
            },
        },
        "dongqiudi_analysis": {"match_id": "1"},
    }

    updated = service._apply_match_data(fixture, enriched, "initial")

    odds = updated["evidence"]["odds"]
    assert odds["over_under"] == 2.5
    assert odds["over_odd"] == 1.85
    assert odds["under_odd"] == 1.95
    ou_quotes = [
        (q["market"], q["selection"], q["price"], q["line"])
        for snapshot in repository.snapshots
        for q in snapshot["quotes"]
        if q["market"] == "over_under"
    ]
    assert ("over_under", "over", 1.85, 2.5) in ou_quotes
    assert ("over_under", "under", 1.95, 2.5) in ou_quotes


def test_dongqiudi_over_under_line_parses_compound_goal_labels() -> None:
    state = DongqiudiProvider._map_odds_state({"homeWin": "0.70", "awayWin": "0.92", "draw": "2.5/3"}, "over_under")

    assert state["line"] == 2.75
    assert state["over_odd"] == 1.70
