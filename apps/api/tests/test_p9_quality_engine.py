"""P9 data quality rules and provider reliability tests."""

from datetime import UTC, datetime, timedelta

from app.data_quality_engine import (
    evaluate_fixture_quality,
    provider_reliability,
    record_fixture_conflicts,
)
from app.database import PredictionRepository

NOW = "2026-09-01T12:00:00+00:00"


def canonical_record(**overrides) -> dict:
    from app.data_quality_engine import canonical_fixture_record

    row = {
        "id": "sportsdb-9001",
        "source": "thesportsdb",
        "league_key": "epl",
        "kickoff": "2026-09-01T19:30:00+08:00",
        "home_team": {"name": "武汉三镇", "provider_id": "801"},
        "away_team": {"name": "上海海港", "provider_id": "802"},
        "status": "scheduled",
        "captured_at": "2026-09-01T10:00:00+00:00",
    }
    row.update(overrides)
    return canonical_fixture_record(row, "epl", round="5")


def rule_status(result: dict, rule: str) -> str:
    return next(item["status"] for item in result["rules"] if item["rule"] == rule)


def test_clean_scheduled_fixture_passes_all_applicable_rules() -> None:
    result = evaluate_fixture_quality(canonical_record(), now=NOW)

    assert result["status"] == "pass"
    assert rule_status(result, "score_completeness") == "not_applicable"
    assert rule_status(result, "odds_timestamp_ordering") == "not_applicable"
    assert result["freshness"]["status"] == "ok"


def test_finished_fixture_without_score_fails_score_completeness() -> None:
    result = evaluate_fixture_quality(canonical_record(status="finished"), now=NOW)

    assert rule_status(result, "score_completeness") == "fail"
    assert rule_status(result, "status_score_consistency") == "warn"
    assert result["status"] == "fail"


def test_scheduled_fixture_cannot_carry_a_score() -> None:
    result = evaluate_fixture_quality(
        canonical_record(score={"home": 1, "away": 0}),
        now=NOW,
    )

    assert rule_status(result, "status_score_consistency") == "fail"
    assert result["status"] == "fail"


def test_missing_provenance_fails_freshness_but_completeness_stays_explicit() -> None:
    record = canonical_record()
    record.pop("captured_at")
    result = evaluate_fixture_quality(record, now=NOW)

    assert rule_status(result, "freshness_sla") == "fail"
    assert result["freshness"]["status"] == "unknown"
    # Completeness is reported separately from freshness.
    assert result["completeness"]["captured_at"] is False
    assert result["completeness"]["teams"] is True


def test_stale_capture_warns_without_touching_completeness() -> None:
    result = evaluate_fixture_quality(
        canonical_record(captured_at="2026-08-20T10:00:00+00:00"),
        now=NOW,
    )

    assert rule_status(result, "freshness_sla") == "warn"
    assert result["freshness"]["status"] == "stale"
    # Completeness is reported separately from freshness.
    assert result["completeness"]["captured_at"] is True
    assert result["completeness"]["teams"] is True


def test_duplicate_same_source_rows_fail_and_cross_source_agreement_passes() -> None:
    record = canonical_record()
    sibling_same_source = dict(record, fixture_id="sportsdb-9002")
    result = evaluate_fixture_quality(record, group=[sibling_same_source], now=NOW)

    assert rule_status(result, "duplicate_detection") == "fail"

    sibling_other_source = dict(record, fixture_id="dongqiudi-7001")
    sibling_other_source["source_refs"] = {"source": "dongqiudi", "external_ids": {}}
    result = evaluate_fixture_quality(record, group=[sibling_other_source], now=NOW)

    assert rule_status(result, "duplicate_detection") == "pass"
    assert rule_status(result, "cross_provider_conflict") == "pass"


def test_cross_source_kickoff_disagreement_is_reported_not_resolved() -> None:
    record = canonical_record()
    sibling = dict(record, fixture_id="dongqiudi-7001", kickoff_at="2026-09-01T21:30:00+08:00")
    sibling["source_refs"] = {"source": "dongqiudi", "external_ids": {}}
    result = evaluate_fixture_quality(record, group=[sibling], now=NOW)

    assert rule_status(result, "cross_provider_conflict") == "fail"
    detail = next(item["detail"] for item in result["rules"] if item["rule"] == "cross_provider_conflict")
    assert detail[0]["conflict_type"] == "kickoff"
    assert detail[0]["resolution_method"] == "configured_source_priority_then_manual_review"


def test_odds_captured_after_kickoff_fail_timestamp_ordering() -> None:
    good_odds = [{"snapshot_id": "odds-1", "captured_at": "2026-09-01T08:00:00+00:00"}]
    result = evaluate_fixture_quality(canonical_record(), odds=good_odds, now=NOW)

    assert rule_status(result, "odds_timestamp_ordering") == "pass"

    future_odds = [{"snapshot_id": "odds-2", "captured_at": "2026-09-01T14:00:00+00:00"}]
    result = evaluate_fixture_quality(canonical_record(), odds=future_odds, now=NOW)

    assert rule_status(result, "odds_timestamp_ordering") == "fail"


def test_knockout_stage_semantics_are_enforced() -> None:
    league_record = canonical_record()
    assert rule_status(evaluate_fixture_quality(league_record, now=NOW), "stage_validity") == "pass"

    # A league fixture must not be staged as a knockout round.
    league_record["stage"]["stage_type"] = "knockout_round"
    assert rule_status(evaluate_fixture_quality(league_record, now=NOW), "stage_validity") == "fail"

    # A cup fixture must not be staged as a league round and needs round info.
    cup_record = dict(league_record, competition_type="knockout")
    cup_record["stage"] = {"stage_id": "stage|cfa_cup|league_round|5|", "stage_type": "league_round", "round": 5, "round_label": None, "leg": None}
    assert rule_status(evaluate_fixture_quality(cup_record, now=NOW), "stage_validity") == "fail"
    cup_record["stage"] = {"stage_id": "stage|cfa_cup|knockout_round|unknown|", "stage_type": "knockout_round", "round": None, "round_label": None, "leg": None}
    assert rule_status(evaluate_fixture_quality(cup_record, now=NOW), "stage_validity") == "warn"


def test_provider_reliability_aggregates_sync_runs() -> None:
    started = datetime.now(UTC) - timedelta(hours=2)
    runs = [
        {
            "run_id": "sync:1",
            "provider": "thesportsdb",
            "league": "epl",
            "entity_type": "fixture",
            "started_at": started.isoformat(),
            "finished_at": (started + timedelta(seconds=30)).isoformat(),
            "status": "completed",
            "records_seen": 10,
            "records_inserted": 8,
            "records_updated": 0,
            "records_rejected": 2,
            "error_category": None,
            "errors": [],
        },
        {
            "run_id": "sync:2",
            "provider": "thesportsdb",
            "league": "epl",
            "entity_type": "fixture",
            "started_at": started.isoformat(),
            "finished_at": (started + timedelta(seconds=90)).isoformat(),
            "status": "unavailable",
            "records_seen": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "records_rejected": 0,
            "error_category": "data_quality_error",
            "errors": ["schema changed"],
        },
    ]
    conflicts = [{"source_a": "thesportsdb", "source_b": "dongqiudi"}]

    report = provider_reliability(runs, fixture_conflicts=conflicts)

    assert len(report) == 1
    row = report[0]
    assert row["provider"] == "thesportsdb"
    assert row["competition"] == "epl"
    assert row["capability"] == "fixture"
    assert row["runs"] == 2
    assert row["completed"] == 1
    assert row["failed"] == 1
    assert row["success_rate"] == 0.5
    assert row["avg_latency_seconds"] == 60.0
    assert row["schema_error_rate"] == 0.5
    assert row["conflict_count"] == 1
    assert row["freshness"]


def test_conflicts_recorded_through_repository_surface_in_reliability(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p9.db"))
    repository.initialize()
    record_fixture_conflicts(
        repository,
        {
            "league_key": "csl",
            "kickoff": "2026-09-01T19:30:00+08:00",
            "home_team": {"name": "武汉三镇"},
            "away_team": {"name": "上海海港"},
            "source": "thesportsdb",
        },
        {
            "league_key": "csl",
            "kickoff": "2026-09-01T22:30:00+08:00",
            "home_team": {"name": "武汉三镇"},
            "away_team": {"name": "上海海港"},
            "source": "dongqiudi",
        },
    )

    report = provider_reliability([], fixture_conflicts=repository.fixture_conflicts())

    assert report == []
    assert repository.fixture_conflicts()[0]["conflict_type"] == "kickoff"


def test_historical_as_of_snapshot_keeps_future_odds_out_of_quality_checks() -> None:
    from app.historical_validation import build_historical_snapshot, filter_as_of

    kickoff = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    as_of = kickoff - timedelta(hours=24)
    odds_snapshots = [
        {"snapshot_id": "odds-pre", "fixture_id": "sportsdb-9001", "captured_at": (kickoff - timedelta(hours=30)).isoformat(), "quotes": [{"market": "1x2", "selection": "home", "price": 2.0, "captured_at": (kickoff - timedelta(hours=30)).isoformat()}]},
        {"snapshot_id": "odds-future", "fixture_id": "sportsdb-9001", "captured_at": (kickoff + timedelta(hours=1)).isoformat(), "quotes": [{"market": "1x2", "selection": "home", "price": 3.0, "captured_at": (kickoff + timedelta(hours=1)).isoformat()}]},
    ]

    filtered = filter_as_of(odds_snapshots, as_of)
    snapshot = build_historical_snapshot(
        {
            "id": "sportsdb-9001",
            "league_key": "epl",
            "kickoff": kickoff.isoformat(),
            "home_team": {"name": "武汉三镇"},
            "away_team": {"name": "上海海港"},
            "status": "scheduled",
        },
        as_of,
        evidence_snapshots=[],
        odds_snapshots=filtered["accepted"],
        source_versions={"odds": "thesportsdb"},
    )
    result = evaluate_fixture_quality(
        canonical_record(),
        odds=filtered["accepted"],
        now=NOW,
    )

    assert filtered["future"][0]["snapshot_id"] == "odds-future"
    assert rule_status(result, "odds_timestamp_ordering") == "pass"
    assert snapshot["as_of"] == as_of.isoformat()
