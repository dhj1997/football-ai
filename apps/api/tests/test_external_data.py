"""外部数据源测试：football-data.co.uk 回填与 ClubElo 评级。"""

import asyncio

import pytest

from app.automation import AutomationRunner
from app.clubeelo_provider import parse_elo_csv, stored_ratings, sync_ratings
from app.config import get_settings
from app.database import PredictionRepository
from app.football_data_provider import parse_season_csv, sync_season
from app.prediction_service import PredictionService

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


def test_clubeelo_parse_and_store_ratings(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "elo.db"))
    repository.initialize()

    result = sync_ratings(repository, SAMPLE_ELO_CSV, localize=lambda name: f"{name}中文名")

    assert result["status"] == "ok" and result["ratings"] == 2
    ratings = stored_ratings(repository)
    assert ratings["Arsenal中文名"] == 2041.0
    assert ratings["Barcelona中文名"] == 2016.0


def test_elo_ratings_prefers_clubeelo_over_local(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "elo-merge.db"), "dual-model-v1")
    repository.initialize()
    sync_ratings(repository, SAMPLE_ELO_CSV, localize=lambda name: name)
    service = PredictionService(None, repository, "deepseek", "dual-model-v1")

    ratings = service._elo_ratings()

    # ClubElo 快照覆盖本地窗口估算；未覆盖的球队没有本地样本时不在表里。
    assert ratings["Arsenal"] == 2041.0
    assert ratings["Barcelona"] == 2016.0


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
