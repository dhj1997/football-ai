"""Current PromptContract retention and simulated-ledger cleanup tests."""

import pytest
from sqlalchemy import text

from app.database import PredictionRepository
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT


CURRENT_VERSION = DEFAULT_PROMPT_CONTRACT.version


def prediction(
    prediction_id: str,
    created_at: str,
    prompt_version: str,
    *,
    fixture_id: str = "fixture-1",
    model_key: str = "deepseek",
    competition_id: str = "retention-test",
) -> dict:
    return {
        "id": prediction_id,
        "fixture_id": fixture_id,
        "created_at": created_at,
        "phase": "preliminary",
        "model_version": f"{model_key}:test",
        "model_key": model_key,
        "competition_id": competition_id,
        "evidence_snapshot_id": f"snapshot-{prediction_id}",
        "probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "ai": {
            "status": "completed",
            "provider": model_key,
            "prompt_version": prompt_version,
        },
    }


def save_prediction(repository: PredictionRepository, item: dict) -> None:
    snapshot_id = item["evidence_snapshot_id"]
    repository.save_evidence_snapshot(
        {
            "id": snapshot_id,
            "fixture_id": item["fixture_id"],
            "created_at": item["created_at"],
            "source_synced_at": item["created_at"],
            "content_hash": snapshot_id.ljust(64, "0")[:64],
            "payload": {"fixture": {"id": item["fixture_id"]}},
        }
    )
    repository.save(item)


def place_bet(repository: PredictionRepository, item: dict, bet_id: str, stake: float) -> dict:
    return repository.place_bet(
        {
            "id": bet_id,
            "prediction_id": item["id"],
            "fixture_id": item["fixture_id"],
            "fixture_date": "2026-08-27",
            "placed_at": item["created_at"],
            "market": "1x2",
            "selection": "home",
            "handicap_line": None,
            "odds": 1.27,
            "stake": stake,
            "league_key": "laliga",
            "kickoff": "2026-08-27T03:00:00+08:00",
            "home_team": "皇家马德里",
            "away_team": "皇家社会",
            "model_version": item["model_version"],
            "is_simulated": True,
            "model_key": item["model_key"],
            "competition_id": item["competition_id"],
        }
    )


def repository(tmp_path) -> PredictionRepository:
    result = PredictionRepository(
        str(tmp_path / "retention.db"),
        competition_id="retention-test",
        model_keys=("deepseek", "chatgpt"),
    )
    result.initialize()
    return result


def test_prune_removes_old_dependencies_and_rebuilds_balance(tmp_path) -> None:
    repo = repository(tmp_path)
    old = prediction("old", "2026-08-27T01:00:00+00:00", "football-forecast-v2")
    current = prediction("current", "2026-08-27T02:00:00+00:00", CURRENT_VERSION)
    save_prediction(repo, old)
    save_prediction(repo, current)
    old_bet = place_bet(repo, old, "bet-old", 100.0)
    repo.settle_bet(old_bet["id"], "2026-08-27T04:00:00+00:00", "full_win", 127.0)
    repo.save_fixture_settlement(
        {
            "id": "settlement-old",
            "prediction_id": old["id"],
            "fixture_id": old["fixture_id"],
            "fixture_date": "2026-08-27",
            "league_key": "laliga",
            "season": "2026-27",
            "model_version": old["model_version"],
            "model_key": old["model_key"],
            "competition_id": old["competition_id"],
            "settled_at": "2026-08-27T04:00:00+00:00",
        }
    )
    place_bet(repo, current, "bet-current", 20.0)

    preview = repo.prediction_retention_preview(CURRENT_VERSION)
    result = repo.prune_prediction_history(CURRENT_VERSION)

    assert preview["delete_counts"] == {
        "predictions": 1,
        "bets": 1,
        "fixture_settlements": 1,
        "bankroll_transactions": 2,
        "evidence_snapshots": 1,
    }
    assert result["delete_counts"] == preview["delete_counts"]
    assert [item["id"] for item in repo.predictions_for_fixture("fixture-1")] == ["current"]
    assert repo.bet_for_prediction("old") is None
    assert repo.settlement_for_prediction("old") is None
    assert repo.evidence_snapshot("snapshot-old") is None
    current_bet = repo.bet_for_prediction("current")
    assert current_bet["balance_before"] == 1000.0
    assert current_bet["balance_after_placement"] == 980.0
    assert repo.current_balance("deepseek", "retention-test") == 980.0
    assert repo.prediction_retention_preview(CURRENT_VERSION)["history_count"] == 0
    assert repo.prune_prediction_history(CURRENT_VERSION)["history_count"] == 0


def test_latest_current_ignores_newer_legacy_and_keeps_only_latest_compatible(tmp_path) -> None:
    repo = repository(tmp_path)
    first_current = prediction("current-1", "2026-08-27T01:00:00+00:00", CURRENT_VERSION)
    latest_current = prediction("current-2", "2026-08-27T02:00:00+00:00", CURRENT_VERSION)
    newest_legacy = prediction("legacy-newest", "2026-08-27T03:00:00+00:00", "football-forecast-v2")
    for item in (first_current, latest_current, newest_legacy):
        save_prediction(repo, item)
    with repo.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM evidence_snapshots WHERE id = :id"),
            {"id": newest_legacy["evidence_snapshot_id"]},
        )

    assert repo.latest_current("fixture-1", CURRENT_VERSION, "deepseek", "retention-test")["id"] == "current-2"
    preview = repo.prediction_retention_preview(CURRENT_VERSION)
    assert preview["history_count"] == 2
    assert preview["delete_counts"]["evidence_snapshots"] == 1

    repo.prune_prediction_history(CURRENT_VERSION)

    assert [item["id"] for item in repo.predictions_for_fixture("fixture-1")] == ["current-2"]


def test_prune_rolls_back_when_ledger_rebuild_fails(tmp_path, monkeypatch) -> None:
    repo = repository(tmp_path)
    old = prediction("old", "2026-08-27T01:00:00+00:00", "football-forecast-v2")
    current = prediction("current", "2026-08-27T02:00:00+00:00", CURRENT_VERSION)
    save_prediction(repo, old)
    save_prediction(repo, current)
    place_bet(repo, old, "bet-old", 20.0)

    def fail_rebuild(*_args, **_kwargs):
        raise RuntimeError("rebuild failed")

    monkeypatch.setattr(repo, "_rebuild_simulation_ledger", fail_rebuild)

    with pytest.raises(RuntimeError, match="rebuild failed"):
        repo.prune_prediction_history(CURRENT_VERSION)

    assert repo.latest("fixture-1", "deepseek", "retention-test")["id"] == "current"
    assert repo.bet_for_prediction("old") is not None
    assert repo.evidence_snapshot("snapshot-old") is not None


def test_new_no_bet_prediction_removes_old_open_bet_and_restores_balance(tmp_path) -> None:
    repo = repository(tmp_path)
    old = prediction("pre-lineup", "2026-08-27T01:00:00+00:00", CURRENT_VERSION)
    current = prediction("confirmed-no-bet", "2026-08-27T02:00:00+00:00", CURRENT_VERSION)
    current["phase"] = "confirmed_lineup"
    current["model_recommendation"] = {
        "status": "no_bet",
        "market": "no_bet",
        "selection": "none",
        "reason": "确认首发后当前市场不值得下注。",
    }
    save_prediction(repo, old)
    place_bet(repo, old, "bet-pre-lineup", 20.0)
    save_prediction(repo, current)

    result = repo.prune_prediction_history(
        CURRENT_VERSION,
        competition_id="retention-test",
        fixture_id="fixture-1",
        model_key="deepseek",
    )

    assert result["delete_counts"]["bets"] == 1
    assert repo.bet_for_prediction("pre-lineup") is None
    assert repo.bets(status="placed", model_key="deepseek", competition_id="retention-test") == []
    assert repo.current_balance("deepseek", "retention-test") == 1000.0


def test_prune_removes_orphan_bet_left_by_a_concurrent_prediction(tmp_path) -> None:
    repo = repository(tmp_path)
    old = prediction("orphaned", "2026-08-27T01:00:00+00:00", CURRENT_VERSION)
    save_prediction(repo, old)
    place_bet(repo, old, "bet-orphaned", 20.0)
    with repo.engine.begin() as connection:
        connection.execute(text("DELETE FROM predictions WHERE id = :id"), {"id": old["id"]})

    result = repo.prune_prediction_history(CURRENT_VERSION)

    assert result["delete_counts"]["bets"] == 1
    assert result["delete_counts"]["bankroll_transactions"] == 1
    assert repo.bets() == []
    assert repo.current_balance("deepseek", "retention-test") == 1000.0


def test_scoped_prune_preserves_other_fixture_bets(tmp_path) -> None:
    repo = repository(tmp_path)
    target_old = prediction("target-old", "2026-08-27T01:00:00+00:00", "football-forecast-v2")
    target_current = prediction("target-current", "2026-08-27T02:00:00+00:00", CURRENT_VERSION)
    other_current = prediction(
        "other-current",
        "2026-08-27T03:00:00+00:00",
        CURRENT_VERSION,
        fixture_id="fixture-2",
        model_key="chatgpt",
    )
    for item in (target_old, target_current, other_current):
        save_prediction(repo, item)
    place_bet(repo, other_current, "bet-other", 20.0)

    repo.prune_prediction_history(
        CURRENT_VERSION,
        competition_id="retention-test",
        fixture_id="fixture-1",
        model_key="deepseek",
    )

    assert repo.bet_for_prediction("other-current") is not None
    assert repo.current_balance("chatgpt", "retention-test") == 980.0
