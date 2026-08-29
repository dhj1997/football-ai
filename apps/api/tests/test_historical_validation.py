import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from app.database import PredictionRepository
from app.historical_validation import (
    BacktestRunService,
    HistoricalBackfillService,
    RawDataIngestionService,
    RollingBacktestService,
    assess_data_quality,
    build_historical_snapshot,
    build_raw_data_record,
    build_performance_profiles,
    canonical_fixture_id,
    canonical_team_id,
    canonical_league_id,
    classify_odds_timeline,
    map_fixture_sources,
    resolve_source_records,
    rolling_windows,
    select_closing_odds,
)


def _fixture() -> dict:
    return {
        "id": "provider-fixture-1",
        "league_key": "epl",
        "fixture_date": "2025-08-20",
        "kickoff": "2025-08-20T20:00:00+00:00",
        "home_team": {"name": "Barcelona"},
        "away_team": {"name": "Sevilla"},
        "status": "finished",
        "score": {"home": 2, "away": 1},
    }


def _evidence(snapshot_id: str, captured_at: str, marker: str) -> dict:
    return {
        "id": snapshot_id,
        "fixture_id": "provider-fixture-1",
        "captured_at": captured_at,
        "created_at": captured_at,
        "evidence_version": "test-v1",
        "content_hash": "a" * 64,
        "payload": {"context": {"source": marker, "recent_form": {"home": [], "away": []}}},
    }


def _odds(snapshot_id: str, captured_at: str, price: float) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "fixture_id": "provider-fixture-1",
        "captured_at": captured_at,
        "quotes": [{"market": "1x2", "selection": "home", "line": None, "price": price, "source": "test"}],
    }


def _settlement(index: int) -> dict:
    created = datetime(2025, 1, 1, tzinfo=UTC).replace(day=1)
    created = created.replace(month=((index - 1) % 12) + 1, year=2025 + (index - 1) // 12)
    timestamp = created.isoformat()
    return {
        "fixture_id": f"fixture-{index}",
        "prediction_id": f"prediction-{index}",
        "prediction_created_at": timestamp,
        "settled_at": timestamp,
        "fixture_date": timestamp[:10],
        "league_key": "epl",
        "model_key": "deepseek",
        "model_version": "deepseek:test",
        "model_probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "baseline": {"probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2}},
        "actual_outcome": "home" if index % 2 else "away",
    }


def test_canonical_identities_map_provider_aliases() -> None:
    assert canonical_league_id("English Premier League") == "epl"
    assert canonical_team_id("FC Barcelona", "La Liga") == canonical_team_id("Barcelona", "La Liga")
    records = map_fixture_sources(
        [
            {"id": "a-1", "source": "api-football", "league_key": "epl", "home_team": "Barcelona", "away_team": "Sevilla", "kickoff": _fixture()["kickoff"]},
            {"id": "b-9", "source": "espn", "league_key": "EPL", "home_team": "FC Barcelona", "away_team": "Sevilla", "kickoff": _fixture()["kickoff"]},
        ]
    )
    assert len(records) == 1
    assert records[0]["canonical_fixture_id"] == canonical_fixture_id(_fixture())


def test_raw_ingestion_is_append_only_with_provenance(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "raw.db"))
    repository.initialize()
    record = build_raw_data_record(
        "fixture",
        "espn",
        "espn-1",
        {"home": "A"},
        "2025-08-20T10:00:00+00:00",
        ingested_at="2025-08-20T10:01:00+00:00",
    )
    repository.save_raw_data_record(record)
    repository.save_raw_data_record(record)
    assert repository.raw_data_records("fixture") == [record]
    with pytest.raises(ValueError, match="immutable"):
        repository.save_raw_data_record({**record, "payload": {"home": "B"}})
    result = RawDataIngestionService(repository).ingest(
        "fixture",
        "espn",
        [{"source_record_id": "espn-2", "captured_at": "2025-08-20T11:00:00+00:00", "payload": {"home": "C"}}],
        ingested_at="2025-08-20T11:01:00+00:00",
    )
    assert result["count"] == 1


def test_source_conflict_is_explicit_and_deterministic_selection() -> None:
    result = resolve_source_records(
        [
            {"source": "espn", "source_record_id": "2", "captured_at": "2025-08-20T10:00:00+00:00", "payload": {"home": "A"}},
            {"source": "api-football", "source_record_id": "1", "captured_at": "2025-08-20T09:00:00+00:00", "payload": {"home": "B"}},
        ],
        kind="fixture",
    )
    assert result["conflict"] is True
    assert result["selected"]["source"] == "api-football"
    assert result["conflict_details"]["resolved_by"]
    mapped = map_fixture_sources(
        [
            {"id": "a-1", "source": "api-football", "league_key": "epl", "home_team": "Team A", "away_team": "Team B", "kickoff": _fixture()["kickoff"]},
            {"id": "b-1", "source": "espn", "league_key": "epl", "home_team": "Team C", "away_team": "Team B", "kickoff": _fixture()["kickoff"]},
        ]
    )
    assert all(item["conflict"] for item in mapped)


def test_performance_profiles_use_only_settled_rows_at_or_before_as_of() -> None:
    old = _settlement(1)
    future = {**_settlement(2), "prediction_created_at": "2026-01-01T00:00:00+00:00", "settled_at": "2026-01-02T00:00:00+00:00"}
    profiles = build_performance_profiles([old, future], as_of="2025-12-31T23:59:59+00:00")
    assert profiles["deepseek|global"]["sample_size"] == 1


def test_historical_snapshot_filters_future_data_and_is_reproducible() -> None:
    snapshot = build_historical_snapshot(
        _fixture(),
        "2025-08-20T18:00:00+00:00",
        evidence_snapshots=[
            _evidence("old", "2025-08-20T17:00:00+00:00", "old"),
            _evidence("future", "2025-08-20T19:00:00+00:00", "future"),
        ],
        odds_snapshots=[
            _odds("old-odds", "2025-08-20T17:00:00+00:00", 2.1),
            _odds("future-odds", "2025-08-20T19:00:00+00:00", 1.8),
        ],
    )
    rebuilt = build_historical_snapshot(
        _fixture(),
        "2025-08-20T18:00:00+00:00",
        evidence_snapshots=[_evidence("old", "2025-08-20T17:00:00+00:00", "old")],
        odds_snapshots=[_odds("old-odds", "2025-08-20T17:00:00+00:00", 2.1)],
    )
    assert snapshot["evidence_snapshot_id"] == "old"
    assert snapshot["odds_snapshot_id"] == "old-odds"
    assert snapshot["snapshot_id"] == rebuilt["snapshot_id"]
    assert snapshot["created_at"] == rebuilt["created_at"]
    assert snapshot["payload"]["context"]["source"] == "old"


def test_closing_odds_is_last_quote_strictly_before_kickoff() -> None:
    selected = select_closing_odds(
        [
            _odds("before", "2025-08-20T19:59:00+00:00", 2.0),
            _odds("at-kickoff", "2025-08-20T20:00:00+00:00", 1.9),
            _odds("after", "2025-08-20T20:01:00+00:00", 1.8),
        ],
        _fixture()["kickoff"],
        market="1x2",
        selection="home",
    )
    assert selected["snapshot_id"] == "before"
    phases = classify_odds_timeline(
        [_odds("open", "2025-08-20T10:00:00+00:00", 2.2), _odds("pre", "2025-08-20T19:59:00+00:00", 2.0)],
        _fixture()["kickoff"],
    )
    assert phases["opening"]["snapshot_id"] == "open"
    assert phases["closing"]["snapshot_id"] == "pre"
    assert select_closing_odds([], _fixture()["kickoff"]) is None


def test_historical_snapshot_persistence_is_append_only(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "historical.db"))
    repository.initialize()
    snapshot = build_historical_snapshot(_fixture(), "2025-08-20T18:00:00+00:00")
    repository.save_historical_snapshot(snapshot)
    repository.save_historical_snapshot(snapshot)
    assert repository.historical_snapshot(snapshot["snapshot_id"]) == snapshot
    with pytest.raises(ValueError, match="immutable"):
        repository.save_historical_snapshot({**snapshot, "payload": {"changed": True}})


def test_quality_excludes_missing_critical_data_without_fabricating_values() -> None:
    quality = assess_data_quality(
        {"id": "fixture-1", "home_team": {"name": "A"}, "away_team": {}, "kickoff": "bad"},
        require_result=True,
        require_kickoff=True,
    )
    assert quality["status"] == "excluded"
    assert "missing_team" in quality["exclusion_reasons"]
    assert "invalid_kickoff" in quality["exclusion_reasons"]
    assert "result_missing" in quality["exclusion_reasons"]


def test_backfill_passes_only_historical_context_to_formal_runner(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "backfill.db"))
    repository.initialize()
    fixture = {**_fixture(), "provider_id": 1, "status": "scheduled", "score": None}
    repository.replace_fixtures("2025-08-20", "2025-08-20", [fixture], "2025-08-20T20:00:00+00:00")
    repository.save_evidence_snapshot(_evidence("old", "2025-08-20T17:00:00+00:00", "old"))
    repository.save_evidence_snapshot(_evidence("future", "2025-08-20T19:00:00+00:00", "future"))
    received: dict[str, Any] = {}

    async def runner(_fixture, context, historical_snapshot=None, prediction_timestamp=None, snapshot_bundle=None, prepared_context=False):
        received.update({"context": context, "snapshot": historical_snapshot, "timestamp": prediction_timestamp, "bundle": snapshot_bundle, "prepared": prepared_context})
        return {"id": "backfill-prediction"}

    result = asyncio.run(HistoricalBackfillService(repository).backfill("provider-fixture-1", "2025-08-20T18:00:00+00:00", prediction_runner=runner))
    assert result["status"] == "completed"
    assert received["context"]["source"] == "old"
    assert received["timestamp"] == "2025-08-20T18:00:00+00:00"
    assert received["bundle"]["evidence"]["id"] == "old"
    assert received["prepared"] is True


def test_rolling_backtest_boundaries_and_reproducibility() -> None:
    windows = rolling_windows("2025-01-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00", train_days=90, test_days=30, step_days=30)
    assert windows[0]["train_end"] == windows[0]["test_start"]
    assert windows[0]["test_end"] < windows[1]["test_end"]
    rows = [_settlement(index) for index in range(1, 13)]
    first = RollingBacktestService(rows).run(start="2025-01-01T00:00:00+00:00", end="2026-12-31T00:00:00+00:00", train_days=90, test_days=180, step_days=180)
    second = RollingBacktestService(rows).run(start="2025-01-01T00:00:00+00:00", end="2026-12-31T00:00:00+00:00", train_days=90, test_days=180, step_days=180)
    assert first == second
    assert first["leakage_check"]["passed"] is True


def test_backtest_run_id_is_reproducible_and_append_only(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "runs.db"))
    repository.initialize()
    result = {"status": "ok", "dataset_version": "dataset-test", "config": {"train_days": 90}}
    service = BacktestRunService(repository)
    first = service.save_result("rolling-test", result)
    second = service.save_result("rolling-test", result)
    assert first["run_id"] == second["run_id"]
    assert repository.backtest_runs() == [first]
    with pytest.raises(ValueError, match="immutable"):
        repository.save_backtest_run({**first, "status": "changed"})
