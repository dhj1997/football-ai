import asyncio
from datetime import UTC, datetime, timedelta

from app.database import PredictionRepository
from app.historical_backfill import HistoricalEvaluationRepository, HistoricalPredictionBackfillService


def _fixture(index: int, kickoff: datetime, *, league: str = "EPL", status: str = "finished") -> dict:
    return {
        "id": f"history-{index}",
        "provider_id": 1000 + index,
        "canonical_fixture_id": f"canonical-history-{index}",
        "canonical_league": league,
        "league_key": league.casefold(),
        "season": "2025",
        "fixture_date": kickoff.date().isoformat(),
        "kickoff": kickoff.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "status": status,
        "home_team": {"canonical_team_id": "team:home", "provider_id": 10, "name": "Home FC"},
        "away_team": {"canonical_team_id": "team:away", "provider_id": 20, "name": "Away FC"},
        "score": {"home": 1, "away": 0} if status == "finished" else None,
        "is_demo": False,
    }


def _seed(repository: PredictionRepository) -> None:
    start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    for index in range(4):
        repository.upsert_fixture(_fixture(index, start + timedelta(days=index * 2)))


def test_backfill_is_as_of_bounded_and_idempotent_without_production_writes(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "historical-backfill.db"))
    repository.initialize()
    _seed(repository)
    service = HistoricalPredictionBackfillService(repository)

    first = asyncio.run(service.run())
    second = asyncio.run(service.run())

    assert first["total_fixtures"] == 4
    assert first["eligible_fixtures"] == 3
    assert first["excluded_fixtures"] == 1
    assert first["excluded_by_reason"] == {"recent_form_unavailable": 1}
    assert first["generated_predictions"] == 3
    assert second["generated_predictions"] == 3
    assert all(item["reused"] for item in second["items"] if item["status"] == "completed")
    stored = repository.historical_predictions(limit=100)
    assert len(stored) == 3
    assert len(repository.historical_snapshots(limit=100)) == 3
    view = HistoricalEvaluationRepository(repository)
    view_snapshot = view.historical_snapshots(fixture_id="history-1")[0]
    assert "captured_at" not in view_snapshot["payload"]["fixture"]
    view_evidence = view.evidence_snapshots("history-1")[0]
    assert "captured_at" not in view_evidence["payload"]["fixture"]
    assert repository.predictions_for_fixture("history-1") == []
    assert repository.fixture_settlements() == []
    assert repository.bets() == []
    assert repository.bet_executions() == []
    for prediction in stored:
        cutoff = datetime.fromisoformat(prediction["prediction_timestamp"])
        assert prediction["feature_snapshot_id"]
        assert prediction["evidence_snapshot_id"]
        assert cutoff < datetime.fromisoformat(prediction["actual_completed_at"])
        evidence = repository.evidence_snapshot(prediction["evidence_snapshot_id"])
        recent = (evidence["payload"]["context"]["recent_form"] if evidence else {})
        for side in ("home", "away"):
            for match in (recent.get(side) or []):
                assert datetime.fromisoformat(match["date"]) <= cutoff


def test_backfill_rejects_unsupported_and_unfinished_fixtures(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "historical-rejects.db"))
    repository.initialize()
    kickoff = datetime(2025, 1, 1, 12, tzinfo=UTC)
    repository.upsert_fixture(_fixture(1, kickoff, league="Bundesliga"))
    repository.upsert_fixture(_fixture(2, kickoff + timedelta(days=2), status="scheduled"))

    result = asyncio.run(HistoricalPredictionBackfillService(repository).run())

    assert result["total_fixtures"] == 1
    assert result["excluded_by_reason"] == {"not_finished": 1}
    assert result["generated_predictions"] == 0


def test_backfill_evaluation_rows_are_isolated_and_p6_compatible(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "historical-evaluation.db"))
    repository.initialize()
    _seed(repository)
    service = HistoricalPredictionBackfillService(repository)
    asyncio.run(service.run())

    rows = service.evaluation_rows()

    assert len(rows) == 3
    assert {row["model_key"] for row in rows} == {"poisson"}
    assert all(row["prediction_timestamp"] for row in rows)
    assert all(row["canonical_fixture_id"].startswith("canonical-history-") for row in rows)
    assert all(row["canonical_league"] == "EPL" and row["league_key"] == "epl" for row in rows)
    assert all(row["competition_id"] == "p7.2-historical" for row in rows)
