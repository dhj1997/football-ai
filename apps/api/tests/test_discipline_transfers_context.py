"""Discipline, transfers, and match-context evidence layers."""

import pytest

from app.discipline_sync import (
    _attribute_sides,
    attach_discipline,
    sync_discipline,
)
from app.prediction_service import _attach_match_context
from app.team_names import to_chinese_player_name, to_chinese_team_name
from app.transfers_sync import attach_transfers, sync_transfers


class StubRepository:
    def __init__(self, rows) -> None:
        self.rows = {row["id"]: dict(row) for row in rows}

    def list_fixtures(self, league_key=None):
        return [dict(row) for row in self.rows.values()]

    def upsert_fixture(self, fixture, synced_at=None):
        self.rows[fixture["id"]] = fixture


class StubEventsProvider:
    def __init__(self, results=None, fail_ids=None) -> None:
        self.results = results or {}
        self.fail_ids = fail_ids or set()

    async def fixture_events(self, fixture_id):
        if str(fixture_id) in self.fail_ids:
            raise RuntimeError("quota")
        return self.results.get(str(fixture_id))


class StubTransfersProvider:
    def __init__(self, results=None, fail_ids=None) -> None:
        self.results = results or {}
        self.fail_ids = fail_ids or set()
        self.calls: list[str] = []

    async def team_transfers(self, team_id):
        self.calls.append(str(team_id))
        if str(team_id) in self.fail_ids:
            raise RuntimeError("quota")
        return self.results.get(str(team_id), [])


def _finished(row_id, home, away, kickoff="2026-09-12T11:00:00+00:00", **extra):
    row = {
        "id": row_id,
        "league_key": "epl",
        "status": "finished",
        "kickoff": kickoff,
        "fixture_date": kickoff[:10],
        "home_team": {"name": home, "original_name": home},
        "away_team": {"name": away, "original_name": away},
        "external_ids": {"api_football": 1},
    }
    row.update(extra)
    return row


def test_attribute_sides_counts_cards_by_canonical_team() -> None:
    row = _finished(
        "a",
        "托特纳姆热刺",
        "埃弗顿",
        score={"home": 1, "away": 0},
    )
    cards = [
        {"team": "Tottenham Hotspur", "detail": "Yellow Card", "player": "Player A"},
        {"team": "Tottenham Hotspur", "detail": "Second Yellow card", "player": "Player B"},
        {"team": "Everton", "detail": "Red Card", "player": "Player C"},
        {"team": "Unknown FC", "detail": "Yellow Card", "player": "Ghost"},
    ]

    discipline = _attribute_sides(row, cards, to_chinese_team_name, _dt("2026-09-12T14:00:00+00:00"))

    assert discipline["home"]["yellow_cards"] == 1
    assert discipline["home"]["red_cards"] == 1
    assert discipline["home"]["red_card_players"] == ["Player B"]
    assert discipline["away"]["red_cards"] == 1
    assert discipline["away"]["red_card_players"] == ["Player C"]
    assert discipline["available_at"].startswith("2026-09-12T14:00")


def _dt(value):
    from datetime import datetime

    return datetime.fromisoformat(value)


@pytest.mark.asyncio
async def test_discipline_sync_writes_siblings_and_marks_unavailable() -> None:
    rows = [
        _finished("sportsdb-1", "托特纳姆热刺", "埃弗顿", external_ids={"api_football": 1}),
        # dongqiudi 平行行
        _finished("dongqiudi-2", "托特纳姆热刺", "埃弗顿", external_ids={}),
        _finished("done", "利物浦", "曼城", external_ids={"api_football": 2}, discipline={"home": {"yellow_cards": 1}}),
        _finished("stale-marker", "切尔西", "阿森纳", external_ids={"api_football": 3}, discipline_unavailable_at="2026-09-19T10:00:00+00:00"),
    ]
    repository = StubRepository(rows)
    provider = StubEventsProvider(results={"1": {"cards": [{"team": "Everton", "detail": "Red Card", "player": "DCL"}]}})

    result = await sync_discipline(
        repository,
        provider,
        limit=10,
        localize=to_chinese_team_name,
        now=_dt("2026-09-19T12:00:00+00:00"),
    )

    assert result["enriched"] == 1
    assert result["rows_written"] == 2  # 平行行都写
    assert result["unavailable"] == 0
    # 24h 内已尝试且无数据的行跳过
    assert "discipline" not in repository.rows["stale-marker"]
    assert repository.rows["sportsdb-1"]["discipline"]["away"]["red_card_players"] == ["DCL"]
    assert repository.rows["dongqiudi-2"]["discipline"]["away"]["red_card_players"] == ["DCL"]


def test_attach_discipline_is_cutoff_safe_and_excludes_target() -> None:
    target = _finished("target", "托特纳姆热刺", "埃弗顿", kickoff="2026-09-20T11:00:00+00:00")
    target["status"] = "scheduled"
    rows = [
        # cutoff 前最后一场：红牌
        _finished(
            "older",
            "埃弗顿",
            "利物浦",
            kickoff="2026-09-13T11:00:00+00:00",
            discipline={"home": {"yellow_cards": 2, "red_cards": 1, "red_card_players": ["DCL"]}},
        ),
        # cutoff 后不可用（泄漏防护）
        _finished(
            "newer",
            "埃弗顿",
            "切尔西",
            kickoff="2026-09-25T11:00:00+00:00",
            discipline={"home": {"yellow_cards": 0, "red_cards": 5, "red_card_players": ["Future"]}},
        ),
    ]
    repository = StubRepository(rows)
    context: dict = {}

    attach_discipline(repository, target, context, "2026-09-19T12:00:00+00:00")

    away = context["discipline"]["away"]
    assert away["red_card_players"] == ["DCL"]
    assert away["last_match_kickoff"].startswith("2026-09-13")
    # 主队（热刺）最近一场无纪律数据
    assert context["discipline"]["home"] is None


def test_attach_transfers_filters_by_recent_window() -> None:
    class TransferRepository:
        def __init__(self, rows):
            self.rows = rows

        def team_transfers_row(self, team_id, season):
            return self.rows.get(str(team_id))

    fixture = {
        "league_key": "epl",
        "evidence": {"team_ids": {"home": 42, "away": 43}},
    }
    repository = TransferRepository(
        {
            "42": {
                "synced_at": "2026-09-19T00:00:00+00:00",
                "transfers": [
                    {"player": "New Guy", "date": "2026-09-01", "in_team_id": 42, "out_team": "Old FC"},
                    {"player": "Old News", "date": "2026-01-15", "in_team_id": 42, "out_team": "Far FC"},
                    {"player": "Leaver", "date": "2026-08-20", "out_team_id": 42, "in_team": "Rivals"},
                ],
            }
        }
    )
    context: dict = {}

    attach_transfers(repository, fixture, context, now=_dt("2026-09-19T12:00:00+00:00"))

    home = context["transfers"]["home"]
    assert home["transfers_in"] == [f"{to_chinese_player_name('New Guy')}（2026-09-01，自 Old FC）"]
    assert home["transfers_out"] == [f"{to_chinese_player_name('Leaver')}（2026-08-20，至 Rivals）"]
    assert context["transfers"]["away"] is None


@pytest.mark.asyncio
async def test_transfers_sync_uses_evidence_team_ids_and_staleness() -> None:
    fixture_rows = [
        {
            "id": "f1",
            "league_key": "epl",
            "status": "scheduled",
            "kickoff": "2026-09-21T12:00:00+00:00",
            "evidence": {"team_ids": {"home": 42, "away": 43}},
        }
    ]
    repository = StubRepository(fixture_rows)
    saved = {}

    def save_team_transfers(team_id, season, transfers, synced_at=None):
        saved[str(team_id)] = transfers
        return len(transfers)

    repository.save_team_transfers = save_team_transfers
    repository.team_transfers_row = lambda team_id, season: None
    provider = StubTransfersProvider(results={"42": [{"player": "New Guy", "date": "2026-09-01", "type": "N", "in_team": "Hotspur", "in_team_id": 42, "out_team": "Old", "out_team_id": 9}]})

    result = await sync_transfers(
        repository,
        provider,
        leagues=("epl",),
        limit=5,
        now=_dt("2026-09-20T12:00:00+00:00"),
    )

    assert result["teams_fetched"] == 2
    assert result["records_saved"] == 1
    assert saved["42"][0]["player"] == to_chinese_player_name("New Guy")
    assert saved["43"] == []


@pytest.mark.asyncio
async def test_transfers_sync_resolves_stored_api_football_identity() -> None:
    repository = StubRepository(
        [
            {
                "id": "f1",
                "league_key": "epl",
                "status": "scheduled",
                "kickoff": "2026-09-21T12:00:00+00:00",
                "home_team": {"name": "曼彻斯特城"},
                "away_team": {"name": "未知升班球队"},
                "evidence": {},
            }
        ]
    )
    repository.team_identities = lambda limit=1000: [
        {
            "source": "api-football",
            "source_team_id": "50",
            "league": "EPL",
            "display_name": "曼彻斯特城",
            "identity_status": "resolved",
            "conflict": False,
        }
    ]
    repository.team_transfers_row = lambda *_args: None
    repository.save_team_transfers = lambda *_args, **_kwargs: None
    provider = StubTransfersProvider(results={"50": []})

    result = await sync_transfers(
        repository,
        provider,
        leagues=("epl",),
        limit=5,
        now=_dt("2026-09-20T12:00:00+00:00"),
    )

    assert result["teams_targeted"] == 1
    assert result["identity_resolved"] == 1
    assert result["provider_id_missing"] == 1
    assert provider.calls == ["50"]


def test_attach_transfers_resolves_stored_api_football_identity() -> None:
    class IdentityTransferRepository:
        def team_identities(self, limit=1000):
            return [
                {
                    "source": "api-football",
                    "source_team_id": "50",
                    "league": "EPL",
                    "display_name": "曼彻斯特城",
                    "identity_status": "resolved",
                    "conflict": False,
                }
            ]

        def team_transfers_row(self, team_id, season):
            if str(team_id) != "50":
                return None
            return {
                "transfers": [
                    {"player": "New Guy", "date": "2026-09-01", "in_team_id": 50, "out_team": "Old FC"}
                ]
            }

    fixture = {
        "league_key": "epl",
        "home_team": {"name": "曼彻斯特城"},
        "away_team": {"name": "未知升班球队"},
        "evidence": {},
    }
    context: dict = {}

    attach_transfers(
        IdentityTransferRepository(),
        fixture,
        context,
        now=_dt("2026-09-20T12:00:00+00:00"),
    )

    assert context["transfers"]["home"]["transfers_in"] == [
        f"{to_chinese_player_name('New Guy')}（2026-09-01，自 Old FC）"
    ]
    assert context["transfers"]["away"] is None


@pytest.mark.asyncio
async def test_transfers_sync_bounds_failed_attempts_and_reports_missing_ids() -> None:
    fixture_rows = [
        {
            "id": "f1",
            "league_key": "epl",
            "status": "scheduled",
            "kickoff": "2026-09-21T12:00:00+00:00",
            "evidence": {"team_ids": {"home": 41, "away": 42}},
        },
        {
            "id": "f2",
            "league_key": "epl",
            "status": "scheduled",
            "kickoff": "2026-09-22T12:00:00+00:00",
            "evidence": {"team_ids": {"home": 43}},
        },
    ]
    repository = StubRepository(fixture_rows)
    repository.team_transfers_row = lambda *_args: None
    calls: list[str] = []

    class FailingProvider:
        async def team_transfers(self, team_id):
            calls.append(str(team_id))
            raise RuntimeError("quota unavailable")

    result = await sync_transfers(
        repository,
        FailingProvider(),
        leagues=("epl",),
        limit=2,
        now=_dt("2026-09-20T12:00:00+00:00"),
    )

    assert result["status"] == "failed"
    assert result["teams_attempted"] == 2
    assert result["failed"] == 2
    assert result["provider_id_missing"] == 1
    assert calls == ["41", "42"]


@pytest.mark.asyncio
async def test_transfers_sync_reports_zero_targets_without_calling_provider() -> None:
    repository = StubRepository(
        [
            {
                "id": "past",
                "league_key": "epl",
                "status": "finished",
                "kickoff": "2026-09-19T12:00:00+00:00",
                "evidence": {"team_ids": {"home": 1, "away": 2}},
            }
        ]
    )
    provider = StubTransfersProvider(results={})

    result = await sync_transfers(
        repository,
        provider,
        leagues=("epl",),
        now=_dt("2026-09-20T12:00:00+00:00"),
    )

    assert result["status"] == "zero_targets"
    assert result["teams_targeted"] == 0
    assert provider.calls == []


def test_attach_match_context_marks_cups_and_round() -> None:
    league_fixture = {
        "league_key": "epl",
        "league": {"name": "英超"},
        "evidence": {"competition": {"name": "Premier League", "round": "Regular Season - 5", "season": "2026"}},
    }
    context: dict = {}
    _attach_match_context(league_fixture, context)
    assert context["match_context"]["round"] == "Regular Season - 5"
    assert context["match_context"]["is_cup"] is False

    cup_fixture = {"league_key": "cfa_cup", "league": {"name": "中国足协杯"}, "evidence": {}}
    cup_context: dict = {}
    _attach_match_context(cup_fixture, cup_context)
    assert cup_context["match_context"]["is_cup"] is True
    assert cup_context["match_context"]["round"] is None
