"""API-Football match statistics ingestion: mapping, eligibility, idempotency."""

from datetime import datetime, timezone

import pytest

from app.match_stats_sync import pending_match_stats_fixtures, sync_match_stats
from app.provider import ApiFootballProvider


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class StubProvider:
    configured = True

    def __init__(self, results=None, fail_ids: set | None = None) -> None:
        self.results = results or {}
        self.fail_ids = fail_ids or set()
        self.calls: list[str] = []

    async def fixture_statistics(self, fixture_id) -> dict | None:
        self.calls.append(str(fixture_id))
        if str(fixture_id) in self.fail_ids:
            raise RuntimeError("API-Football down")
        return self.results.get(str(fixture_id))


class StubRepository:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = {row["id"]: dict(row) for row in rows}
        self.upserted: list[str] = []

    def list_fixtures(self, league_key: str | None = None) -> list[dict]:
        return [dict(row) for row in self.rows.values()]

    def upsert_fixture(self, fixture: dict, synced_at: str | None = None) -> None:
        self.rows[fixture["id"]] = fixture
        self.upserted.append(fixture["id"])


def _row(row_id: str, **extra) -> dict:
    row = {
        "id": row_id,
        "league_key": "csl",
        "kickoff": "2026-09-12T11:00:00+00:00",
        "status": "finished",
        "external_ids": {"api_football": 9001},
        "xg": {"home": 1.2, "away": 0.8, "source": "understat", "available_at": "2026-09-12T14:00:00+00:00"},
    }
    row.update(extra)
    return row


def test_map_fixture_statistics_parses_labels_and_percent_values() -> None:
    provider = ApiFootballProvider("key", "https://example.test")
    mapped = provider._map_fixture_statistics(
        [
            {"type": "Total Shots", "value": "14"},
            {"type": "Shots on Goal", "value": 6},
            {"type": "Corner Kicks", "value": "5"},
            {"type": "Ball Possession", "value": "55%"},
        ]
    )

    assert mapped == (14, 6, 5)
    # 0 是合法统计值（如角球挂零），不能当缺失丢弃。
    assert provider._map_fixture_statistics(
        [
            {"type": "Total Shots", "value": "30"},
            {"type": "Shots on Goal", "value": 9},
            {"type": "Corner Kicks", "value": 0},
        ]
    ) == (30, 9, 0)
    # 缺任一关键指标则放弃整队，避免写出残缺 match_stats
    assert provider._map_fixture_statistics([{"type": "Total Shots", "value": "9"}]) is None
    # null 值视为缺失
    assert provider._map_fixture_statistics([{"type": "Total Shots", "value": None}]) is None


def test_pending_only_finished_league_rows_with_external_id() -> None:
    repository = StubRepository(
        [
            _row("a"),
            _row("b", status="scheduled"),
            _row("c", external_ids={"dongqiudi": "1"}),
            _row("d", league_key="ucl"),
            _row("e", match_stats={"home_shots": 9}),
            _row("f", match_stats_unavailable_at="2026-09-12T12:00:00+00:00"),
        ]
    )

    pending = pending_match_stats_fixtures(repository, now=_dt("2026-09-12T20:00:00+00:00"))

    # f 在 24h 重试窗口内被标记过，不再进入待办
    assert [row["id"] for row in pending] == ["a"]


def test_pending_retries_after_retry_window() -> None:
    repository = StubRepository([_row("f", match_stats_unavailable_at="2026-09-12T12:00:00+00:00")])

    pending = pending_match_stats_fixtures(repository, now=_dt("2026-09-13T12:00:01+00:00"))

    assert [row["id"] for row in pending] == ["f"]


@pytest.mark.asyncio
async def test_sync_marks_unavailable_rows_for_daily_retry() -> None:
    repository = StubRepository([_row("a", external_ids={"api_football": 1})])
    provider = StubProvider(results={})  # 源上无数据

    result = await sync_match_stats(repository, provider, limit=5)

    assert result["enriched"] == 0
    assert result["unavailable"] == 1
    assert "match_stats_unavailable_at" in repository.rows["a"]
    # 已标记的行当日内不再重试
    assert pending_match_stats_fixtures(repository) == []


@pytest.mark.asyncio
async def test_sync_propagates_stats_to_parallel_rows() -> None:
    from app.team_names import to_chinese_team_name

    repository = StubRepository(
        [
            _row(
                "sportsdb-1",
                external_ids={"api_football": 1},
                home_team={"name": "天津津门虎", "original_name": "Tianjin Jinmen Tiger"},
                away_team={"name": "辽宁铁人", "original_name": "Liaoning Tieren"},
            ),
            # 同一场比赛的 dongqiudi 平行行：中文队名、无外部 ID
            _row(
                "dongqiudi-2",
                external_ids={},
                home_team={"name": "天津津门虎", "original_name": "天津津门虎"},
                away_team={"name": "辽宁铁人", "original_name": "辽宁铁人"},
            ),
        ]
    )
    provider = StubProvider(
        results={"1": {"home_shots": 14, "away_shots": 9, "home_shots_on_target": 6, "away_shots_on_target": 3, "home_corners": 5, "away_corners": 4}}
    )

    result = await sync_match_stats(repository, provider, limit=5, localize=to_chinese_team_name)

    assert result["enriched"] == 1
    assert result["rows_written"] == 2
    for row_id in ("sportsdb-1", "dongqiudi-2"):
        assert repository.rows[row_id]["match_stats"]["home_shots"] == 14


@pytest.mark.asyncio
async def test_sync_enriches_with_limit_and_preserves_xg() -> None:
    repository = StubRepository(
        [
            _row("a", external_ids={"api_football": 1}),
            _row("b", external_ids={"api_football": 2}),
            _row("c", external_ids={"api_football": 3}),
        ]
    )
    provider = StubProvider(
        results={
            "1": {"home_shots": 14, "away_shots": 9, "home_shots_on_target": 6, "away_shots_on_target": 3, "home_corners": 5, "away_corners": 4},
            "2": {"home_shots": 10, "away_shots": 11, "home_shots_on_target": 4, "away_shots_on_target": 5, "home_corners": 6, "away_corners": 7},
        }
    )

    result = await sync_match_stats(repository, provider, limit=2)

    assert result["enriched"] == 2
    assert result["failed"] == 0
    assert repository.upserted == ["a", "b"]
    enriched = repository.rows["a"]
    assert enriched["match_stats"]["home_shots"] == 14
    assert enriched["match_stats"]["source"] == "api-football"
    assert enriched["xg"]["home"] == 1.2


@pytest.mark.asyncio
async def test_sync_survives_provider_failures() -> None:
    repository = StubRepository(
        [
            _row("a", external_ids={"api_football": 1}),
            _row("b", external_ids={"api_football": 2}),
        ]
    )
    provider = StubProvider(
        results={"2": {"home_shots": 10, "away_shots": 11, "home_shots_on_target": 4, "away_shots_on_target": 5, "home_corners": 6, "away_corners": 7}},
        fail_ids={"1"},
    )

    result = await sync_match_stats(repository, provider, limit=10)

    assert result["enriched"] == 1
    assert result["failed"] == 1
    assert repository.upserted == ["b"]
