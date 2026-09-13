"""P9 canonical normalization, identity and conflict recording tests."""

from app.data_quality_engine import (
    canonical_fixture_record,
    canonical_stage,
    record_fixture_conflicts,
)
from app.database import PredictionRepository


def sportsdb_row(league_key: str = "epl", **overrides) -> dict:
    row = {
        "id": "sportsdb-9001",
        "provider_id": "9001",
        "source": "thesportsdb",
        "league_key": league_key,
        "kickoff": "2026-09-01T19:30:00+08:00",
        "home_team": {"name": "武汉三镇", "provider_id": "801"},
        "away_team": {"name": "上海海港", "provider_id": "802"},
        "status": "scheduled",
        "captured_at": "2026-08-30T10:00:00+00:00",
    }
    row.update(overrides)
    return row


def dongqiudi_row(league_key: str = "epl", **overrides) -> dict:
    row = {
        "id": "dongqiudi-7001",
        "provider_id": 7001,
        "source": "dongqiudi",
        "league_key": league_key,
        "kickoff": "2026-09-01T19:30:00+08:00",
        "home_team": {"name": "武汉三镇", "provider_id": "301"},
        "away_team": {"name": "上海海港", "provider_id": "302"},
        "status": "scheduled",
        "external_ids": {"dongqiudi": "7001"},
        "captured_at": "2026-08-31T09:00:00+00:00",
    }
    row.update(overrides)
    return row


def test_six_competitions_produce_canonical_fixture_records() -> None:
    cases = [
        ("csl", None),
        ("epl", None),
        ("laliga", None),
        ("cfa_cup", "四分之一决赛"),
        ("ucl", "小组赛"),
        ("acl", "1/4决赛"),
    ]
    for league_key, stage_text in cases:
        row = sportsdb_row(league_key)
        record = canonical_fixture_record(row, league_key, stage_name=stage_text)

        assert record is not None, league_key
        assert record["competition_key"] == league_key
        assert record["canonical_fixture_id"]
        assert record["home_team"]["team_id"] and record["away_team"]["team_id"]
        assert record["home_team"]["team_id"] != record["away_team"]["team_id"]
        assert record["source_refs"]["source"] == "thesportsdb"
        assert record["captured_at"] == "2026-08-30T10:00:00+00:00"


def test_knockout_competitions_never_use_league_round_stage() -> None:
    for league_key in ("cfa_cup", "ucl", "acl"):
        record = canonical_fixture_record(sportsdb_row(league_key), league_key, stage_name="四分之一决赛")

        assert record["stage"]["stage_type"] in {"knockout_round", "group"}
        assert record["stage"]["stage_type"] != "league_round"


def test_stage_normalization_distinguishes_group_and_knockout() -> None:
    group = canonical_stage("ucl", stage_name="小组赛")
    knockout = canonical_stage("ucl", stage_name="半决赛")
    league = canonical_stage("epl", round="12")

    assert group["stage_type"] == "group"
    assert knockout["stage_type"] == "knockout_round"
    assert league["stage_type"] == "league_round"
    assert league["round"] == 12
    assert canonical_stage("epl", round="12")["stage_id"] == league["stage_id"]


def test_same_match_from_two_providers_shares_canonical_identity() -> None:
    first = canonical_fixture_record(sportsdb_row(), "epl")
    second = canonical_fixture_record(dongqiudi_row(), "epl")

    assert first["canonical_fixture_id"] == second["canonical_fixture_id"]
    assert first["home_team"]["team_id"] == second["home_team"]["team_id"]


def test_incomplete_identity_returns_none_instead_of_fabricating() -> None:
    missing_kickoff = sportsdb_row()
    missing_kickoff.pop("kickoff")
    missing_away = sportsdb_row()
    missing_away["away_team"] = {"name": ""}

    assert canonical_fixture_record(missing_kickoff, "epl") is None
    assert canonical_fixture_record(missing_away, "epl") is None
    assert canonical_fixture_record(sportsdb_row(), "bogus_league") is None


def test_record_fixture_conflicts_persists_kickoff_disagreement(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p9.db"))
    repository.initialize()
    existing = sportsdb_row()
    incoming = dongqiudi_row(kickoff="2026-09-01T21:30:00+08:00")

    saved = record_fixture_conflicts(repository, existing, incoming)

    assert len(saved) == 1
    assert saved[0]["conflict_type"] == "kickoff"
    assert saved[0]["source_a"] == "thesportsdb"
    assert saved[0]["source_b"] == "dongqiudi"
    assert saved[0]["resolved"] is False
    rows = repository.fixture_conflicts()
    assert len(rows) == 1
    assert rows[0]["competition_key"] == "epl"


def test_record_fixture_conflicts_is_deterministic_and_deduplicated(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p9.db"))
    repository.initialize()
    existing = sportsdb_row()
    incoming = dongqiudi_row(kickoff="2026-09-01T21:30:00+08:00")

    first = record_fixture_conflicts(repository, existing, incoming)
    second = record_fixture_conflicts(repository, existing, incoming)

    assert first[0]["conflict_id"] == second[0]["conflict_id"]
    assert len(repository.fixture_conflicts()) == 1


def test_same_source_and_agreeing_rows_produce_no_conflict(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p9.db"))
    repository.initialize()

    same_source = record_fixture_conflicts(
        repository,
        sportsdb_row(),
        sportsdb_row(id="sportsdb-9002", kickoff="2026-09-01T21:30:00+08:00"),
    )
    agreeing = record_fixture_conflicts(repository, sportsdb_row(), dongqiudi_row())

    assert same_source == []
    assert agreeing == []
    assert repository.fixture_conflicts() == []


def test_record_fixture_conflicts_detects_score_disagreement(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p9.db"))
    repository.initialize()
    existing = sportsdb_row(status="finished", score={"home": 2, "away": 1})
    incoming = dongqiudi_row(status="finished", score={"home": 1, "away": 1})

    saved = record_fixture_conflicts(repository, existing, incoming)

    assert [item["conflict_type"] for item in saved] == ["score"]
    assert saved[0]["value_a"] == {"home": 2, "away": 1}
    assert saved[0]["value_b"] == {"home": 1, "away": 1}
