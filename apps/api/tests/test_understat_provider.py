"""Understat xG/xPoints ingestion: parsing, matching, and point-in-time stamping."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.team_names import to_chinese_team_name
from app.understat_provider import (
    UnderstatProviderError,
    parse_league_data,
    sync_understat_xg,
)


def _league_payload() -> dict:
    return {
        "dates": [
            {
                "id": "28778",
                "isResult": True,
                "h": {"id": "87", "title": "Liverpool", "short_title": "LIV"},
                "a": {"id": "73", "title": "Bournemouth", "short_title": "BOU"},
                "goals": {"h": "4", "a": "2"},
                "xG": {"h": "2.33007", "a": "1.57303"},
                "datetime": "2025-08-15 19:00:00",
            },
            {
                "id": "28779",
                "isResult": False,
                "h": {"id": "87", "title": "Liverpool", "short_title": "LIV"},
                "a": {"id": "44", "title": "Newcastle United", "short_title": "NEW"},
                "goals": {},
                "xG": {},
                "datetime": "2025-08-25 19:00:00",
            },
        ],
        "teams": {
            "87": {
                "id": "87",
                "title": "Liverpool",
                "history": [
                    {"h_a": "h", "xG": 2.33, "xGA": 1.57, "xpts": 2.14, "date": "2025-08-15 19:00:00"}
                ],
            },
            "73": {
                "id": "73",
                "title": "Bournemouth",
                "history": [
                    {"h_a": "a", "xG": 1.57, "xGA": 2.33, "xpts": 0.63, "date": "2025-08-15 19:00:00"}
                ],
            },
        },
    }


class StubRepository:
    def __init__(self, fixtures: list[dict]) -> None:
        self.fixtures = {row["id"]: json.loads(json.dumps(row)) for row in fixtures}
        self.upserts: list[str] = []

    def list_fixtures(self, league_key: str | None = None) -> list[dict]:
        return [row for row in self.fixtures.values() if row.get("league_key") == league_key]

    def upsert_fixture(self, fixture: dict, synced_at: str | None = None) -> None:
        self.fixtures[fixture["id"]] = fixture
        self.upserts.append(fixture["id"])


def _fixture(fixture_id: str, home: dict, away: dict, **extra) -> dict:
    row = {
        "id": fixture_id,
        "league_key": "epl",
        "kickoff": "2025-08-15T19:00:00+00:00",
        "status": "finished",
        "home_team": home,
        "away_team": away,
        "evidence": {"squad": {"x": 1}},
    }
    row.update(extra)
    return row


def test_parse_flattens_only_finished_matches_with_xpts() -> None:
    matches = parse_league_data(_league_payload())

    assert len(matches) == 1
    match = matches[0]
    assert match["understat_id"] == "28778"
    assert match["kickoff"] == "2025-08-15T19:00:00+00:00"
    assert match["home_xg"] == pytest.approx(2.33007)
    assert match["away_xg"] == pytest.approx(1.57303)
    assert match["home_xpts"] == pytest.approx(2.14)
    assert match["away_xpts"] == pytest.approx(0.63)


def test_parse_rejects_non_object_payload() -> None:
    with pytest.raises(UnderstatProviderError):
        parse_league_data(["not", "an", "object"])  # type: ignore[arg-type]


def test_sync_enriches_fixtures_across_provider_spellings() -> None:
    repository = StubRepository(
        [
            # sportsdb 风格：中文展示名 + 英文 original_name
            _fixture(
                "sportsdb-1",
                {"name": "利物浦", "original_name": "Liverpool"},
                {"name": "伯恩茅斯", "original_name": "Bournemouth"},
                result_captured_at="2025-08-15T21:45:00+00:00",
            ),
            # dongqiudi 风格：同一 physical match 的平行行，original_name 也是中文
            _fixture(
                "dongqiudi-2",
                {"name": "利物浦", "original_name": "利物浦"},
                {"name": "伯恩茅斯", "original_name": "伯恩茅斯"},
                result_captured_at="2025-08-15T21:45:00+00:00",
            ),
        ]
    )

    result = sync_understat_xg(
        repository,
        _league_payload(),
        "epl",
        localize=to_chinese_team_name,
    )

    # 同一场比赛的跨源平行行都要写回，保证特征序列完整
    assert result["fixtures_matched"] == 2
    assert result["xg_enriched"] == 2
    assert result["xpoints_enriched"] == 2
    assert result["unmatched_titles"] == []
    for fixture_id in ("sportsdb-1", "dongqiudi-2"):
        enriched = repository.fixtures[fixture_id]
        assert enriched["xg"]["home"] == pytest.approx(2.33007)
        assert enriched["xg"]["away"] == pytest.approx(1.57303)
        assert enriched["xg"]["source"] == "understat"
        assert enriched["xpoints"]["home"] == pytest.approx(2.14)
        assert enriched["xpoints"]["away"] == pytest.approx(0.63)
        # 既有字段不被破坏
        assert enriched["evidence"] == {"squad": {"x": 1}}


def test_sync_available_at_follows_result_policy_not_kickoff() -> None:
    captured = "2025-08-15T21:45:00+00:00"
    repository = StubRepository(
        [_fixture("sportsdb-1", {"name": "利物浦"}, {"name": "伯恩茅斯"}, result_captured_at=captured)]
    )
    sync_understat_xg(repository, _league_payload(), "epl", localize=to_chinese_team_name)
    assert repository.fixtures["sportsdb-1"]["xg"]["available_at"] == captured

    fallback_repository = StubRepository(
        [_fixture("sportsdb-2", {"name": "利物浦"}, {"name": "伯恩茅斯"})]
    )
    sync_understat_xg(fallback_repository, _league_payload(), "epl", localize=to_chinese_team_name)
    available = fallback_repository.fixtures["sportsdb-2"]["xg"]["available_at"]
    assert datetime.fromisoformat(available) == datetime(2025, 8, 15, 22, 0, tzinfo=UTC)


def test_sync_is_idempotent_and_rejects_score_conflicts() -> None:
    repository = StubRepository(
        [
            _fixture(
                "sportsdb-1",
                {"name": "利物浦"},
                {"name": "伯恩茅斯"},
                score={"home": 3, "away": 2},  # 与 Understat 4-2 冲突
            )
        ]
    )

    result = sync_understat_xg(repository, _league_payload(), "epl", localize=to_chinese_team_name)
    assert result["fixtures_matched"] == 0
    assert "xg" not in repository.fixtures["sportsdb-1"]

    repository.fixtures["sportsdb-1"]["score"] = {"home": 4, "away": 2}
    first = sync_understat_xg(repository, _league_payload(), "epl", localize=to_chinese_team_name)
    assert first["xg_enriched"] == 1
    snapshot = json.dumps(repository.fixtures["sportsdb-1"], sort_keys=True)
    second = sync_understat_xg(repository, _league_payload(), "epl", localize=to_chinese_team_name)
    assert second["xg_enriched"] == 1
    assert json.dumps(repository.fixtures["sportsdb-1"], sort_keys=True) == snapshot


def test_sync_matches_fixture_kickoff_one_day_offset() -> None:
    repository = StubRepository(
        [_fixture("sportsdb-1", {"name": "利物浦"}, {"name": "伯恩茅斯"}, kickoff="2025-08-16T11:30:00+00:00")]
    )
    result = sync_understat_xg(repository, _league_payload(), "epl", localize=to_chinese_team_name)
    assert result["fixtures_matched"] == 1
