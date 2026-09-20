"""外部数据源测试：football-data.co.uk 回填与 ClubElo 评级。"""

import asyncio
from datetime import UTC, datetime

import pytest

from app.automation import AutomationRunner
from app.clubeelo_provider import parse_elo_csv, refresh_ratings, stored_ratings, sync_ratings
from app.config import get_settings
from app.database import PredictionRepository
from app.football_data_provider import parse_season_csv, sync_season
from app.prediction_service import PredictionService
from app.team_stats import attach_team_stats, team_stat_profiles

SAMPLE_FD_CSV = """Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,B365H,B365D,B365A,AvgH,AvgD,AvgA,AHh,B365AHH,B365AHA,PSCH,PSCD,PSCA
E0,13/09/2026,Arsenal,Nottingham,2,1,H,1,0,1.5,4.2,6.5,1.52,4.1,6.2,-1.0,2.05,1.85,1.48,4.3,6.8
E0,14/09/2026,Chelsea,Liverpool,1,1,D,0,0,2.6,3.4,2.7,2.55,3.3,2.75,-0.5,1.95,1.95,2.5,3.5,2.8
"""

SAMPLE_ELO_CSV = """From,To,Club,Country,Level,Rank,Rating
2026-09-13,2026-09-20,Arsenal,ENG,ENG1,1,2041
2026-09-13,2026-09-20,Barcelona,ESP,ESP1,4,2016
"""


def test_parse_season_csv_maps_results_stats_and_odds() -> None:
    rows = parse_season_csv(SAMPLE_FD_CSV, 2026)

    assert len(rows) == 2
    first = rows[0]
    assert first["home"] == "Arsenal"
    assert first["away"] == "Nottingham"
    assert first["home_goals"] == 2 and first["away_goals"] == 1
    assert first["result"] == "H"
    assert first["half_time"] == "1 - 0"
    assert first["date"].startswith("2026-09-13")
    assert first["odds"]["b365"]["home"] == 1.5
    assert first["odds"]["avg"]["away"] == 6.2
    assert first["odds"]["closing"]["home"] == 1.48
    assert first["odds"]["asian_handicap"]["line"] == -1.0
    assert first["odds"]["asian_handicap"]["b365_home"] == 2.05


def test_sync_season_ingests_fixtures_and_closing_odds(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "fd.db"))
    repository.initialize()

    first = sync_season(repository, SAMPLE_FD_CSV, "epl", 2026, chinese_name=lambda name: name)
    second = sync_season(repository, SAMPLE_FD_CSV, "epl", 2026, chinese_name=lambda name: name)

    assert first["matches"] == 2 and first["odds_snapshots"] == 6  # 每场 3 个庄家组快照
    assert second["matches"] == 2
    # 幂等：重复入库不产生重复赔率快照错误。
    fixtures = repository.list_fixtures()
    assert len(fixtures) == 2
    assert fixtures[0]["source"] == "football-data"
    all_selections = {
        quote["market"] + ":" + quote["selection"]
        for snapshot in repository.odds_snapshots(fixtures[0]["id"])
        for quote in snapshot["quotes"]
    }
    assert "1x2:home" in all_selections and "asian_handicap:away" in all_selections
    snapshots = repository.odds_snapshots(fixtures[0]["id"])
    assert snapshots[0]["captured_at"] == fixtures[0]["kickoff"]


def test_schedule_window_replace_keeps_football_data_rows(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "fd-protect.db"))
    repository.initialize()
    sync_season(repository, SAMPLE_FD_CSV, "epl", 2026, chinese_name=lambda name: name)

    # 当日窗口的赛程同步不得清掉 football-data 历史行。
    dummy = {
        "id": "sportsdb-dummy",
        "provider_id": 1,
        "league_key": "epl",
        "fixture_date": "2026-09-13",
        "kickoff": "2026-09-13T15:00:00+00:00",
        "status": "scheduled",
        "home_team": {"name": "X"},
        "away_team": {"name": "Y"},
        "is_demo": False,
    }
    repository.replace_fixtures("2026-09-13", "2026-09-14", [dummy], datetime.now(UTC).isoformat())

    surviving = [row for row in repository.list_fixtures() if str(row.get("id", "")).startswith("fd-")]
    assert len(surviving) == 2


SAMPLE_FD_CSV_WITH_STATS = """Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HS,AS,HST,AST,HC,AC,B365H,B365D,B365A
E0,13/09/2026,Arsenal,Nottingham,2,1,H,1,0,15,8,6,2,7,3,1.5,4.2,6.5
E0,20/09/2026,Nottingham,Arsenal,0,3,A,0,1,9,14,3,8,4,6,4.5,3.6,1.8
"""


def test_football_data_team_aliases_translate_to_chinese() -> None:
    from app.team_names import to_chinese_team_name

    for alias, expected in (
        ("Man United", "曼彻斯特联"),
        ("Nott'm Forest", "诺丁汉森林"),
        ("Sociedad", "皇家社会"),
        ("Ath Bilbao", "毕尔巴鄂竞技"),
        ("Betis", "皇家贝蒂斯"),
        ("Celta", "维戈塞尔塔"),
        ("Vallecano", "巴列卡诺"),
        ("La Coruna", "拉科鲁尼亚"),
        ("Wolves", "狼队"),
        ("West Ham", "西汉姆联"),
    ):
        assert to_chinese_team_name(alias) == expected, alias


def test_team_stat_profiles_average_only_prior_matches(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "stats.db"))
    repository.initialize()
    sync_season(repository, SAMPLE_FD_CSV_WITH_STATS, "epl", 2026)

    profiles = team_stat_profiles(repository, before_iso="2026-09-20T00:00:00+00:00", min_matches=1)
    arsenal = profiles["Arsenal"]

    assert arsenal["matches"] == 1
    assert arsenal["shots_for"] == 15 and arsenal["shots_against"] == 8
    assert arsenal["corners_for"] == 7 and arsenal["goals_for"] == 2

    # as-of 在比赛前：没有任何画像（不用未来数据）。
    assert team_stat_profiles(repository, before_iso="2026-09-01T00:00:00+00:00", min_matches=1) == {}


def test_attach_team_stats_injects_context_for_supported_league(tmp_path) -> None:
    from app import team_stats as team_stats_module

    team_stats_module._CACHE.clear()
    repository = PredictionRepository(str(tmp_path / "stats-inject.db"))
    repository.initialize()
    sync_season(repository, SAMPLE_FD_CSV_WITH_STATS, "epl", 2026)
    fixture = {
        "id": "upcoming-1",
        "league_key": "epl",
        "is_demo": False,
        "home_team": {"name": "Arsenal"},
        "away_team": {"name": "Nottingham"},
    }
    context: dict = {}

    attach_team_stats(
        repository,
        fixture,
        context,
        prediction_timestamp="2026-09-25T00:00:00+00:00",
        min_matches=1,
    )

    assert context["team_stats"]["home"]["shots_for"] == pytest.approx((15 + 14) / 2)
    assert context["team_stats"]["away"]["corners_against"] == pytest.approx((7 + 6) / 2)

    # 非支持联赛不注入。
    other = {**fixture, "league_key": "ucl", "home_team": {"name": "Arsenal"}, "away_team": {"name": "Nottingham"}}
    other_context: dict = {}
    attach_team_stats(
        repository,
        other,
        other_context,
        prediction_timestamp="2026-09-25T00:00:00+00:00",
        min_matches=1,
    )
    assert "team_stats" not in other_context


def test_team_stat_profiles_dedupe_parallel_rows_and_span_leagues(tmp_path) -> None:
    from app import team_stats as team_stats_module

    team_stats_module._CACHE.clear()
    repository = PredictionRepository(str(tmp_path / "stats-dedup.db"))
    repository.initialize()

    def match_row(row_id: str, source: str, league_key: str, home_shots: int) -> dict:
        return {
            "id": row_id,
            "source": source,
            "league_key": league_key,
            "fixture_date": "2026-09-12",
            "kickoff": "2026-09-12T11:00:00+00:00",
            "status": "finished",
            "home_team": {"name": "上海海港"},
            "away_team": {"name": "上海申花"},
            "score": {"home": 2, "away": 1},
            "match_stats": {"home_shots": home_shots, "away_shots": 9, "home_shots_on_target": 5, "away_shots_on_target": 3, "home_corners": 6, "away_corners": 4},
        }

    # 同一场比赛的两个平行行：football-data 优先，只计一次。
    repository.upsert_fixture(match_row("dqyd-1", "dongqiudi", "csl", 11))
    repository.upsert_fixture(match_row("fd-1", "football-data", "csl", 15))

    profiles = team_stat_profiles(repository, before_iso="2026-09-20T00:00:00+00:00", min_matches=1)

    assert profiles["上海海港"]["matches"] == 1.0
    assert profiles["上海海港"]["shots_for"] == 15
    assert profiles["上海海港"]["source"] == "football-data"


def test_clubeelo_parse_and_store_ratings(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "elo.db"))
    repository.initialize()

    result = sync_ratings(repository, SAMPLE_ELO_CSV, localize=lambda name: f"{name}中文名")

    assert result["status"] == "ok" and result["ratings"] == 2
    ratings = stored_ratings(repository)
    assert ratings["Arsenal中文名"] == 2041.0
    assert ratings["Barcelona中文名"] == 2016.0


@pytest.mark.asyncio
async def test_clubeelo_refresh_records_failure_and_preserves_last_good(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "elo-health.db"))
    repository.initialize()
    sync_ratings(repository, SAMPLE_ELO_CSV, localize=lambda name: name)

    class FailingProvider:
        async def fetch_on(self) -> str:
            raise TimeoutError("ClubElo timed out")

    with pytest.raises(TimeoutError, match="timed out"):
        await refresh_ratings(repository, FailingProvider(), localize=lambda name: name)

    assert stored_ratings(repository)["Arsenal"] == 2041.0
    run = repository.data_sync_runs(provider="clubeelo", limit=1)[0]
    assert run["status"] == "failed"
    assert run["error_category"] == "TimeoutError"


def test_elo_ratings_prefers_clubeelo_over_local(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "elo-merge.db"), "dual-model-v1")
    repository.initialize()
    sync_ratings(repository, SAMPLE_ELO_CSV, localize=lambda name: name)
    service = PredictionService(None, repository, "deepseek", "dual-model-v1")

    ratings = service._elo_ratings()

    # ClubElo 快照覆盖本地窗口估算；未覆盖的球队没有本地样本时不在表里。
    assert ratings["Arsenal"] == 2041.0
    assert ratings["Barcelona"] == 2016.0
    assert ratings["sources"]["Arsenal"] == "clubeelo"
    assert ratings["source"] == "clubeelo"


def test_elo_ratings_labels_local_completed_match_fallback(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "elo-local.db"), "dual-model-v1")
    repository.initialize()
    repository.upsert_fixture(
        {
            "id": "dongqiudi-finished-1",
            "source": "dongqiudi",
            "league_key": "epl",
            "status": "finished",
            "fixture_date": "2026-09-01",
            "kickoff": "2026-09-01T12:00:00+00:00",
            "home_team": {"name": "阿森纳"},
            "away_team": {"name": "切尔西"},
            "score": {"home": 2, "away": 0},
        }
    )
    repository.upsert_fixture(
        {
            "id": "future-finished-result",
            "source": "dongqiudi",
            "league_key": "epl",
            "status": "finished",
            "fixture_date": "2026-09-30",
            "kickoff": "2026-09-30T12:00:00+00:00",
            "home_team": {"name": "利物浦"},
            "away_team": {"name": "曼联"},
            "score": {"home": 1, "away": 0},
        }
    )

    ratings = PredictionService(None, repository, "deepseek", "dual-model-v1")._elo_ratings(
        "2026-09-20T12:00:00+00:00"
    )

    assert isinstance(ratings["阿森纳"], float)
    assert ratings["sources"]["阿森纳"] == "completed-match-results/local-elo"
    assert ratings["source"] == "completed-match-results/local-elo"
    assert ratings["source_record_ids"] == ["dongqiudi-finished-1"]


def test_football_data_backfill_job_ingests_pending_season(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "fd-job.db"), "dual-model-v1")
    repository.initialize()

    class FakeFdService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        async def fetch_season_csv(self, division: str, season: int) -> str | None:
            self.calls.append((division, season))
            if len(self.calls) == 1:
                return SAMPLE_FD_CSV
            return None  # 模拟赛季未发布 → 打 0 样记号跳过

    fake = FakeFdService()
    automation = AutomationRunner(
        get_settings(),
        repository,
        schedule_sync=None,
        league_sync=None,
        evidence_provider=None,
        prediction_service=None,
        bankroll_service=None,
        settlement_service=None,
        football_data_service=fake,
    )

    first = asyncio.run(automation._sync_football_data())
    assert first["matches"] == 2
    assert fake.calls[0] == ("epl", 2026)
    assert repository.sync_marker("fd:epl:2026")

    second = asyncio.run(automation._sync_football_data())
    # 首个赛季已入库记号 → 跳过；下一赛季 404 → 记 0 继续；再无待处理项时 complete。
    assert second["item_count"] == 0 or second["status"] in {"complete", "completed"}
