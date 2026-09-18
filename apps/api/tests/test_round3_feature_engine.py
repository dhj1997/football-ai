"""Round 3 Feature Engine v2 contracts."""

from copy import deepcopy

import pytest
from sqlalchemy import inspect

from app.database import PredictionRepository
from app.feature_coverage import build_feature_coverage, render_feature_coverage_markdown
from app.feature_engine import FeatureEngine
from app.feature_registry import FeatureRegistry, builtin_feature_definitions
from app.leakage_audit import LeakageAuditService
from app.no_ml_guard import NoMLNumericPathError, assert_v2_numeric_path_allowed
from app.prediction_intelligence import build_feature_snapshot


def repository(tmp_path) -> PredictionRepository:
    result = PredictionRepository(str(tmp_path / "round3.db"), competition_id="round3")
    result.initialize()
    return result


def fixture(
    fixture_id: str,
    kickoff: str,
    *,
    home: str = "home",
    away: str = "away",
    score: tuple[int, int] = (2, 1),
    available_at: str | None = None,
    xg: tuple[float, float] | None = None,
    xg_available_at: str | None = None,
) -> dict:
    row = {
        "id": fixture_id,
        "canonical_fixture_id": fixture_id,
        "canonical_league": "EPL",
        "season_id": "2026",
        "kickoff": kickoff,
        "status": "finished",
        "score": {"home": score[0], "away": score[1]},
        "home_team": {"canonical_team_id": home},
        "away_team": {"canonical_team_id": away},
        "match_stats": {
            "home_shots": 12,
            "away_shots": 8,
            "home_shots_on_target": 5,
            "away_shots_on_target": 3,
        },
    }
    if available_at:
        row["result_captured_at"] = available_at
    if xg:
        row["xg"] = {"home": xg[0], "away": xg[1], "available_at": xg_available_at}
    return row


def engine_with(repo: PredictionRepository, fixtures: list[dict]) -> FeatureEngine:
    repo.list_fixtures = lambda *args, **kwargs: deepcopy(fixtures)  # type: ignore[method-assign]
    return FeatureEngine(repo)


def target_fixture() -> dict:
    return {
        "id": "target",
        "canonical_fixture_id": "target",
        "canonical_league": "EPL",
        "season_id": "2026",
        "kickoff": "2026-09-20T15:00:00+00:00",
        "status": "scheduled",
        "score": None,
        "home_team": {"canonical_team_id": "home"},
        "away_team": {"canonical_team_id": "away"},
    }


def feature_row(snapshot: dict, name: str, side: str = "home") -> dict:
    return next(
        row
        for row in snapshot["features"]
        if row["feature_name"] == name and row["side"] == side
    )


def test_round3_schema_and_builtin_registry_are_idempotent(tmp_path) -> None:
    repo = repository(tmp_path)

    repo.initialize()

    schema = inspect(repo.engine)
    assert {"feature_registry", "player_impact_rules"}.issubset(schema.get_table_names())
    columns = {column["name"] for column in schema.get_columns("feature_values")}
    assert {
        "registry_id",
        "entity_type",
        "entity_id",
        "value_type",
        "calculation_version",
        "source_record_ids",
        "quality_score",
        "missing_reason",
    }.issubset(columns)
    rows = FeatureRegistry(repo).list()
    assert len(rows) == len(builtin_feature_definitions())
    assert {"team_elo", "rolling_xg_5", "fatigue_score", "player_impact"}.issubset(
        {row["feature_name"] for row in rows}
    )


def test_feature_registry_definition_is_immutable_but_lifecycle_can_change(tmp_path) -> None:
    repo = repository(tmp_path)
    item = FeatureRegistry(repo).get("team_elo", "elo-feature-v1")
    assert item is not None

    changed = deepcopy(item)
    changed["formula"] = "hidden learned weights"
    with pytest.raises(ValueError, match="immutable"):
        repo.save_feature_registry(changed)

    retired = deepcopy(item)
    retired["status"] = "deprecated"
    retired["deprecated_at"] = "2026-09-16T01:00:00+00:00"
    repo.save_feature_registry(retired)
    assert FeatureRegistry(repo).get("team_elo", "elo-feature-v1")["status"] == "deprecated"
    repo.initialize()
    assert FeatureRegistry(repo).get("team_elo", "elo-feature-v1")["status"] == "deprecated"


def test_player_impact_rules_are_append_only_and_cutoff_filtered(tmp_path) -> None:
    repo = repository(tmp_path)
    rule = {
        "id": "rule-player-9-attack-v1",
        "player_id": "player-9",
        "role": "attack",
        "impact_type": "main_striker_missing",
        "impact_value": -0.1,
        "confidence": 0.9,
        "source": "confirmed-lineup",
        "available_at": "2026-09-16T04:00:00+00:00",
        "rule_version": "player-impact-rule-v1",
        "status": "active",
        "created_at": "2026-09-16T04:00:00+00:00",
        "deprecated_at": None,
    }
    repo.save_player_impact_rule(rule)
    repo.save_player_impact_rule(deepcopy(rule))

    assert repo.player_impact_rules(
        player_ids=["player-9"], available_at_lte="2026-09-16T03:59:59+00:00"
    ) == []
    assert repo.player_impact_rules(
        player_ids=["player-9"], available_at_lte="2026-09-16T04:00:00+00:00"
    ) == [rule]
    changed = deepcopy(rule)
    changed["impact_value"] = -0.2
    with pytest.raises(ValueError, match="immutable"):
        repo.save_player_impact_rule(changed)
    retired = deepcopy(rule)
    retired["status"] = "deprecated"
    retired["deprecated_at"] = "2026-09-16T05:00:00+00:00"
    repo.save_player_impact_rule(retired)
    assert repo.player_impact_rules(player_ids=["player-9"]) == []


def test_enriched_feature_value_round_trips_and_remains_immutable(tmp_path) -> None:
    repo = repository(tmp_path)
    cutoff = "2026-09-16T05:00:00+00:00"
    definition = FeatureRegistry(repo).get("team_elo", "elo-feature-v1")
    snapshot = {
        "snapshot_id": "feature:round3-storage",
        "fixture_id": "fixture-round3",
        "prediction_cutoff_at": cutoff,
        "computed_at": cutoff,
        "feature_version": "round3-feature-engine-v2",
        "leakage_detected": False,
        "features": [
            {
                "feature_name": "team_elo",
                "feature_value": 1532.25,
                "source": "completed_match_results",
                "source_record_id": "fixture-history-1",
                "source_record_ids": ["fixture-history-1"],
                "registry_id": definition["id"],
                "entity_type": "team",
                "entity_id": "team-home",
                "value_type": "number",
                "calculation_version": "elo-feature-v1",
                "quality_score": 0.93,
                "missing_reason": None,
                "computed_at": cutoff,
                "available_at": cutoff,
                "prediction_cutoff_at": cutoff,
                "feature_version": "round3-feature-engine-v2",
                "snapshot_id": "feature:round3-storage",
                "status": "available",
            }
        ],
    }

    first = repo.save_feature_snapshot(snapshot)
    persisted = repo.feature_values(first["snapshot_id"])[0]

    assert persisted["registry_id"] == definition["id"]
    assert persisted["source_record_ids"] == ["fixture-history-1"]
    assert persisted["entity_type"] == "team"
    assert persisted["entity_id"] == "team-home"
    assert persisted["quality_score"] == 0.93
    changed = deepcopy(snapshot)
    changed["features"][0]["quality_score"] = 0.5
    with pytest.raises(ValueError, match="immutable"):
        repo.save_feature_snapshot(changed)


def test_feature_available_at_boundary(tmp_path) -> None:
    repo = repository(tmp_path)
    cutoff = "2026-09-16T12:00:00+00:00"
    history = [
        fixture(
            "boundary",
            "2026-09-16T08:00:00+00:00",
            available_at=cutoff,
            xg=(1.7, 0.8),
            xg_available_at=cutoff,
        )
    ]

    snapshot = engine_with(repo, history).calculate_snapshot(target_fixture(), {}, cutoff)

    row = feature_row(snapshot, "rolling_xg_3")
    assert row["status"] == "insufficient_sample"
    assert row["feature_value"] == 1.7
    assert row["available_at"] == cutoff
    assert snapshot["leakage_detected"] is False


def test_feature_respects_prediction_cutoff(tmp_path) -> None:
    repo = repository(tmp_path)
    cutoff = "2026-09-16T12:00:00+00:00"
    history = [
        fixture("past", "2026-09-10T12:00:00+00:00", available_at="2026-09-10T15:00:00+00:00"),
        fixture("future-result", "2026-09-16T10:00:00+00:00", available_at="2026-09-16T13:00:00+00:00"),
    ]

    snapshot = engine_with(repo, history).calculate_snapshot(target_fixture(), {}, cutoff)

    row = feature_row(snapshot, "points_last_3")
    assert row["feature_value"] == 3
    assert row["source_record_ids"] == ["past"]


def test_elo_no_future_matches(tmp_path) -> None:
    repo = repository(tmp_path)
    history = [
        fixture("elo-past", "2026-09-10T12:00:00+00:00", available_at="2026-09-10T15:00:00+00:00"),
        fixture("elo-future", "2026-09-16T10:00:00+00:00", available_at="2026-09-16T13:00:00+00:00", score=(0, 4)),
    ]

    snapshot = engine_with(repo, history).calculate_snapshot(
        target_fixture(), {}, "2026-09-16T12:00:00+00:00"
    )

    row = feature_row(snapshot, "team_elo")
    assert row["source_record_ids"] == ["elo-past"]
    assert row["feature_value"] > 1500


def test_form_no_future_matches(tmp_path) -> None:
    repo = repository(tmp_path)
    history = [
        fixture("form-past", "2026-09-10T12:00:00+00:00", available_at="2026-09-10T15:00:00+00:00"),
        fixture("form-future", "2026-09-17T10:00:00+00:00", available_at="2026-09-17T13:00:00+00:00", score=(0, 3)),
    ]

    snapshot = engine_with(repo, history).calculate_snapshot(
        target_fixture(), {}, "2026-09-16T12:00:00+00:00"
    )

    assert feature_row(snapshot, "win_rate_last_3")["feature_value"] == 1.0
    assert feature_row(snapshot, "loss_rate_last_3")["feature_value"] == 0.0


def test_xg_no_future_matches(tmp_path) -> None:
    repo = repository(tmp_path)
    cutoff = "2026-09-16T12:00:00+00:00"
    history = [
        fixture(
            "xg-future",
            "2026-09-10T12:00:00+00:00",
            available_at="2026-09-10T15:00:00+00:00",
            xg=(2.1, 0.5),
            xg_available_at="2026-09-16T13:00:00+00:00",
        )
    ]

    snapshot = engine_with(repo, history).calculate_snapshot(target_fixture(), {}, cutoff)

    row = feature_row(snapshot, "rolling_xg_3")
    assert row["feature_value"] is None
    assert row["status"] == "future"
    assert row["missing_reason"] == "xg_available_after_cutoff"
    assert snapshot["leakage_detected"] is True


def test_home_away_feature_boundary(tmp_path) -> None:
    repo = repository(tmp_path)
    cutoff = "2026-09-16T12:00:00+00:00"
    history = [
        fixture("home-boundary", "2026-09-16T08:00:00+00:00", available_at=cutoff, score=(3, 1)),
        fixture("home-future", "2026-09-16T09:00:00+00:00", available_at="2026-09-16T12:00:01+00:00", score=(0, 4)),
    ]

    snapshot = engine_with(repo, history).calculate_snapshot(target_fixture(), {}, cutoff)

    assert feature_row(snapshot, "home_win_rate")["feature_value"] == 1.0
    assert feature_row(snapshot, "home_goals_for")["feature_value"] == 3.0


def test_feature_reproducibility(tmp_path) -> None:
    repo = repository(tmp_path)
    history = [
        fixture(
            "stable",
            "2026-09-10T12:00:00+00:00",
            available_at="2026-09-10T15:00:00+00:00",
            xg=(1.4, 0.9),
            xg_available_at="2026-09-10T15:00:00+00:00",
        )
    ]
    engine = engine_with(repo, history)

    first = engine.calculate_snapshot(target_fixture(), {}, "2026-09-16T12:00:00+00:00")
    second = engine.calculate_snapshot(target_fixture(), {}, "2026-09-16T12:00:00+00:00")

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["features"] == second["features"]


def test_player_impact_requires_cutoff_safe_database_rule(tmp_path) -> None:
    repo = repository(tmp_path)
    repo.save_player_impact_rule(
        {
            "id": "rule-striker-v1",
            "player_id": "player-9",
            "role": "attack",
            "impact_type": "main_striker_missing",
            "impact_value": -0.12,
            "confidence": 0.9,
            "source": "confirmed-injury",
            "available_at": "2026-09-16T10:00:00+00:00",
            "rule_version": "player-impact-rule-v1",
            "status": "active",
            "created_at": "2026-09-16T10:00:00+00:00",
            "deprecated_at": None,
        }
    )
    evidence = {
        "availability": {
            "players": [{"team": "home", "canonical_player_id": "player-9", "name": "供应商英文名"}],
            "updated_at": "2026-09-16T10:00:00+00:00",
        }
    }

    snapshot = engine_with(repo, []).calculate_snapshot(
        target_fixture(), evidence, "2026-09-16T12:00:00+00:00"
    )

    row = feature_row(snapshot, "player_impact")
    assert row["feature_value"] == -0.12
    assert row["source_record_ids"] == ["rule-striker-v1"]
    assert "供应商英文名" not in str(snapshot)


def test_no_ml_guard_rejects_learned_and_nested_llm_numeric_paths() -> None:
    with pytest.raises(NoMLNumericPathError, match="learned"):
        assert_v2_numeric_path_allowed({"engine": "learned-ensemble", "weights": {"a": 1.0}})
    with pytest.raises(NoMLNumericPathError, match="LLM numeric"):
        assert_v2_numeric_path_allowed(
            {"assessment": {"probabilities": {"home": 0.5}}},
            source="deepseek",
        )


def test_prediction_snapshot_entry_uses_v2_with_real_repository(tmp_path) -> None:
    repo = repository(tmp_path)
    repo.list_fixtures = lambda *args, **kwargs: []  # type: ignore[method-assign]

    snapshot = build_feature_snapshot(
        target_fixture(),
        {},
        "2026-09-16T12:00:00+00:00",
        repository=repo,
    )

    assert snapshot["feature_version"] == "round3-feature-engine-v2"
    assert len(snapshot["features"]) == 112


def test_coverage_counts_only_latest_audit_passed_v2_snapshot(tmp_path) -> None:
    repo = repository(tmp_path)
    repo.list_fixtures = lambda *args, **kwargs: []  # type: ignore[method-assign]
    snapshot = FeatureEngine(repo).calculate_snapshot(
        target_fixture(), {}, "2026-09-16T12:00:00+00:00"
    )
    persisted = repo.save_feature_snapshot(snapshot)

    assert build_feature_coverage(repo, generated_at="2026-09-16T13:00:00+00:00")["status"] == "no_snapshots"
    audit = LeakageAuditService(repo).audit_feature_snapshot(
        persisted,
        prediction_id="prediction-coverage",
    )
    assert audit["status"] == "PASS"

    report = build_feature_coverage(repo, generated_at="2026-09-16T13:00:00+00:00")
    markdown = render_feature_coverage_markdown(report)
    assert report["status"] == "ok"
    assert report["snapshot_count"] == 1
    assert "EPL" in report["competitions"]
    assert "| EPL | form |" in markdown
