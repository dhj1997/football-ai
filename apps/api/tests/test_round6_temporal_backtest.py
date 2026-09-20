"""Focused Round 6 temporal eligibility, provenance, and API contracts."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("USE_DEMO_DATA", "false")
os.environ.setdefault("API_DEEPSEEK_KEY", "")
os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

import app.main as main_module
from app.market_prior import MarketPriorConfig
from app.temporal_backtest import (
    SOURCE_KIND,
    TemporalBacktestService,
    build_round6_backtest_run,
)


MODEL = {"home": 0.5, "draw": 0.3, "away": 0.2}
MARKET = {"home": 0.4, "draw": 0.3, "away": 0.3}
FINAL = {"home": 0.46, "draw": 0.3, "away": 0.24}
ADMIN = {"x-admin-key": "dev-admin-key"}


class Round6Repository:
    def __init__(self) -> None:
        self.fixtures: list[dict[str, Any]] = []
        self.markets: list[dict[str, Any]] = []
        self.features: dict[str, dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []
        self.odds: dict[str, dict[str, Any]] = {}
        self.revisions: dict[tuple[str, int], dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.saved_runs: list[str] = []
        self.leakage_requests: list[list[str] | None] = []

    def list_fixtures(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return deepcopy(self.fixtures)

    def market_snapshots(self, fixture_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.markets
        if fixture_id:
            rows = [row for row in rows if row["fixture_id"] == fixture_id]
        return deepcopy(rows)

    def feature_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return deepcopy(self.features.get(snapshot_id))

    def leakage_audits(self, **kwargs: Any) -> list[dict[str, Any]]:
        feature_snapshot_ids = kwargs.get("feature_snapshot_ids")
        requested = (
            sorted(str(value) for value in feature_snapshot_ids)
            if feature_snapshot_ids is not None
            else None
        )
        self.leakage_requests.append(requested)
        rows = self.audits
        if requested is not None:
            allowed = set(requested)
            rows = [
                row
                for row in rows
                if str(row.get("feature_snapshot_id") or row.get("snapshot_id") or "")
                in allowed
            ]
        return deepcopy(rows)

    def odds_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return deepcopy(self.odds.get(snapshot_id))

    def prediction_revision(
        self,
        prediction_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any] | None:
        if revision_number is None:
            candidates = [
                row
                for (candidate_id, _number), row in self.revisions.items()
                if candidate_id == prediction_id
            ]
            if not candidates:
                return None
            return deepcopy(max(candidates, key=lambda row: row["revision_number"]))
        return deepcopy(self.revisions.get((prediction_id, revision_number)))

    def backtest_run(self, run_id: str) -> dict[str, Any] | None:
        return deepcopy(self.runs.get(run_id))

    def save_backtest_run(self, run: dict[str, Any]) -> None:
        previous = self.runs.get(run["run_id"])
        if previous is not None and previous != run:
            raise ValueError("Backtest run is immutable")
        self.runs[run["run_id"]] = deepcopy(run)
        self.saved_runs.append(run["run_id"])


def fixture(
    fixture_id: str,
    kickoff: str,
    *,
    status: str = "finished",
    score: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "id": fixture_id,
        "league_key": "epl",
        "season": "2026",
        "fixture_date": kickoff[:10],
        "kickoff": kickoff,
        "status": status,
        "score": score if score is not None else {"home": 2, "away": 1},
    }


def feature_snapshot(
    fixture_id: str,
    cutoff: str,
    *,
    available_at: str | None = None,
) -> dict[str, Any]:
    snapshot_id = f"feature:{fixture_id}:{cutoff}"
    return {
        "snapshot_id": snapshot_id,
        "fixture_id": fixture_id,
        "prediction_cutoff_at": cutoff,
        "computed_at": cutoff,
        "feature_version": "round3-feature-engine-v2",
        "leakage_detected": False,
        "leakage_check": {"passed": True, "violations": []},
        "features": [
            {
                "feature_name": "team_elo",
                "feature_value": 1500.0,
                "source": "completed_match_results",
                "source_record_id": "result:prior",
                "computed_at": cutoff,
                "available_at": available_at or cutoff,
                "prediction_cutoff_at": cutoff,
                "feature_version": "round3-feature-engine-v2",
                "snapshot_id": snapshot_id,
                "status": "available",
            }
        ],
    }


def add_round5_audit(
    repository: Round6Repository,
    fixture_id: str,
    cutoff: str,
    *,
    model: dict[str, float] | None = None,
    market: dict[str, float] | None = None,
    final: dict[str, float] | None = None,
    market_status: str = "MODEL_PLUS_MARKET",
    snapshot_suffix: str = "one",
) -> str:
    snapshot = feature_snapshot(fixture_id, cutoff)
    feature_id = snapshot["snapshot_id"]
    repository.features[feature_id] = snapshot
    prediction_id = f"prediction:{fixture_id}:{snapshot_suffix}"
    revision_number = 1
    revision_id = f"{prediction_id}:{revision_number}"
    kickoff = next(
        item["kickoff"] for item in repository.fixtures if item["id"] == fixture_id
    )
    persisted_at = (datetime.fromisoformat(cutoff) + timedelta(minutes=1)).isoformat()
    leakage_audit_id = f"audit:{fixture_id}:{snapshot_suffix}"
    repository.audits.append(
        {
            "audit_id": leakage_audit_id,
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_id,
            "status": "PASS",
            "prediction_cutoff_at": cutoff,
        }
    )
    repository.revisions[(prediction_id, revision_number)] = {
        "prediction_id": prediction_id,
        "revision_number": revision_number,
        "fixture_id": fixture_id,
        "prediction_cutoff_at": cutoff,
        "feature_snapshot_id": feature_id,
        "model_key": "poisson",
        "model_version": "poisson-dc-v2.0.0",
        "probability_home": (model or MODEL)["home"],
        "probability_draw": (model or MODEL)["draw"],
        "probability_away": (model or MODEL)["away"],
        "probability_model_version": "poisson-dc-v2.0.0",
        "probability_calculation_version": "round4-probability-engine-v1",
    }
    policy = MarketPriorConfig()
    source_ids: list[str] = []
    if market_status == "MODEL_PLUS_MARKET":
        odds_id = f"odds:{fixture_id}:{snapshot_suffix}"
        source_ids = [odds_id]
        repository.odds[odds_id] = {
            "id": odds_id,
            "fixture_id": fixture_id,
            "captured_at": cutoff,
            "source_updated_at": cutoff,
            "quotes": [],
        }
    market_snapshot_id = f"round5:{fixture_id}:{snapshot_suffix}"
    audit = {
        "audit_version": "round5-probability-audit-v1",
        "production_evidence_version": "round6.5-production-evidence-v1",
        "production_evidence_valid": True,
        "evidence_kind": "production_prediction",
        "fixture_id": fixture_id,
        "market_snapshot_id": market_snapshot_id,
        "prediction_id": prediction_id,
        "prediction_revision_number": revision_number,
        "prediction_revision_id": revision_id,
        "model_key": "poisson",
        "serving_model_version": "poisson-dc-v2.0.0",
        "prediction_cutoff_at": cutoff,
        "kickoff_at": kickoff,
        "persisted_at": persisted_at,
        "leakage_audit_id": leakage_audit_id,
        "feature_snapshot_id": feature_id,
        "probability_model_version": "poisson-dc-v2.0.0",
        "probability_calculation_version": "round4-probability-engine-v1",
        "market_prior_id": (
            f"market-prior:{fixture_id}:{snapshot_suffix}"
            if market_status == "MODEL_PLUS_MARKET"
            else None
        ),
        "source_odds_snapshot_ids": source_ids,
        "market_model_version": policy.market_model_version,
        "market_calculation_version": policy.calculation_version,
        "fusion_version": policy.fusion_version,
        "fusion_config_hash": policy.config_hash,
        "fusion_weights": {
            "model": policy.model_weight,
            "market": policy.market_weight,
        },
        "model_probability": deepcopy(model or MODEL),
        "market_probability": deepcopy(
            market if market is not None else (MARKET if source_ids else None)
        ),
        "final_probability": deepcopy(final or (FINAL if source_ids else model or MODEL)),
        "market_status": market_status,
        "market_fusion_applied": bool(source_ids),
        "market_fusion_count": 1 if source_ids else 0,
        "no_ml": True,
        "no_llm_numeric_probability": True,
        "reproducible": True,
    }
    repository.markets.append(
        {
            "market_snapshot_id": market_snapshot_id,
            "fixture_id": fixture_id,
            "prediction_revision_id": revision_id,
            "persisted_at": persisted_at,
            "market": "1x2",
            "captured_at": cutoff,
            "payload": {
                "snapshot_type": "round5_probability_audit",
                "audit": audit,
                "market_prior": {},
            },
        }
    )
    return feature_id


def test_temporal_report_is_chronological_and_keeps_three_layers_separate() -> None:
    repository = Round6Repository()
    repository.fixtures = [
        fixture("late", "2026-09-17T12:00:00+00:00"),
        fixture("early", "2026-09-17T10:00:00+00:00", score={"home": 1, "away": 1}),
    ]
    add_round5_audit(repository, "late", "2026-09-17T10:00:00+00:00")
    add_round5_audit(repository, "early", "2026-09-17T09:30:00+00:00")

    report = TemporalBacktestService(repository).run()

    assert [row["fixture_id"] for row in report["observations"]] == ["early", "late"]
    assert [row["cutoff_segment"] for row in report["observations"]] == ["30m", "6h"]
    assert report["observations"][0]["actual_outcome"] == "draw"
    assert report["observations"][0]["source_kind"] == SOURCE_KIND
    assert report["observations"][0]["replayed_prediction"] is False
    assert report["observations"][0]["replay_status"] == "not_replayed"
    assert report["observations"][0]["round6_replay_performed"] is False
    assert report["observations"][0]["historical_production_prediction"] is True
    assert report["observations"][0]["provenance"]["prediction_revision_id"]
    assert report["observations"][0]["provenance"]["persisted_at"]
    assert report["observations"][0]["model_probability"] == MODEL
    assert report["observations"][0]["market_probability"] == MARKET
    assert report["observations"][0]["final_probability"] == FINAL
    assert report["model"]["sample_count"] == 2
    assert report["market"]["sample_count"] == 2
    assert report["final"]["sample_count"] == 2
    assert report["status"] == "insufficient_data"
    assert report["provenance"]["round6_replay_count"] == 0
    assert report["provenance"]["source_replay_status"] == "not_replayed"
    assert repository.leakage_requests == [
        sorted(
            [
                "feature:early:2026-09-17T09:30:00+00:00",
                "feature:late:2026-09-17T10:00:00+00:00",
            ]
        )
    ]


def test_model_only_keeps_model_and_final_coverage_without_imputing_market() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("model-only", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(
        repository,
        "model-only",
        "2026-09-17T11:00:00+00:00",
        market_status="MODEL_ONLY",
    )

    report = TemporalBacktestService(repository).run()

    assert report["observations"][0]["market_status"] == "MODEL_ONLY"
    assert report["observations"][0]["provenance"]["market_prior_id"] is None
    assert report["coverage"]["model"]["rate"] == 1.0
    assert report["coverage"]["market"]["rate"] == 0.0
    assert report["coverage"]["final"]["rate"] == 1.0
    assert report["exclusion_reasons"]["missing_market_probability"] == 1
    assert report["segments"]["availability"]["model_only"]["sample_count"] == 1


def test_any_historical_leakage_fail_is_sticky() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("sticky", "2026-09-17T12:00:00+00:00")]
    feature_id = add_round5_audit(repository, "sticky", "2026-09-17T11:00:00+00:00")
    repository.audits.extend(
        [
            {"audit_id": "audit:fail", "feature_snapshot_id": feature_id, "status": "FAIL"},
            {"audit_id": "audit:later-pass", "feature_snapshot_id": feature_id, "status": "PASS"},
        ]
    )

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["leakage_failed"] == 1


def test_leakage_pass_must_match_the_prediction_cutoff() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("audit-cutoff", "2026-09-17T12:00:00+00:00")]
    feature_id = add_round5_audit(
        repository,
        "audit-cutoff",
        "2026-09-17T11:00:00+00:00",
    )
    repository.audits[0]["prediction_cutoff_at"] = "2026-09-17T10:00:00+00:00"

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["leakage_unknown"] == 1


def test_leakage_warn_cannot_be_overridden_by_a_pass() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("warn", "2026-09-17T12:00:00+00:00")]
    feature_id = add_round5_audit(repository, "warn", "2026-09-17T11:00:00+00:00")
    repository.audits.append(
        {
            "audit_id": "audit:warn",
            "feature_snapshot_id": feature_id,
            "status": "WARN",
            "prediction_cutoff_at": "2026-09-17T11:00:00+00:00",
        }
    )

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["leakage_unknown"] == 1


def test_canonical_leakage_recheck_rejects_future_feature() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("future", "2026-09-17T12:00:00+00:00")]
    feature_id = add_round5_audit(repository, "future", "2026-09-17T11:00:00+00:00")
    repository.features[feature_id]["features"][0]["available_at"] = (
        "2026-09-17T11:00:01+00:00"
    )

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["leakage_failed"] == 1


def test_post_kickoff_and_unfinished_fixtures_are_excluded_with_reasons() -> None:
    repository = Round6Repository()
    repository.fixtures = [
        fixture("post", "2026-09-17T12:00:00+00:00"),
        fixture("scheduled", "2026-09-17T13:00:00+00:00", status="scheduled", score=None),
    ]
    add_round5_audit(repository, "post", "2026-09-17T12:00:00+00:00")

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"] == {
        "missing_result": 1,
        "post_kickoff_prediction": 1,
    }


def test_exact_odds_provenance_must_be_at_or_before_cutoff() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("future-odds", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "future-odds", "2026-09-17T11:00:00+00:00")
    repository.odds["odds:future-odds:one"]["captured_at"] = (
        "2026-09-17T11:00:01+00:00"
    )

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["odds_after_prediction_cutoff"] == 1


def test_invalid_layer_is_not_imputed_and_frozen_fusion_is_not_recomputed() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("bad-final", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(
        repository,
        "bad-final",
        "2026-09-17T11:00:00+00:00",
        final={"home": 0.2, "draw": 0.4, "away": 0.4},
    )

    report = TemporalBacktestService(repository).run()

    row = report["observations"][0]
    assert row["model_probability"] == MODEL
    assert row["market_probability"] == MARKET
    assert row["final_probability"] is None
    assert report["coverage"]["final"]["rate"] == 0.0
    assert report["exclusion_reasons"]["invalid_frozen_fusion"] == 1


def test_duplicate_fixture_cutoff_is_ambiguous_instead_of_silently_selected() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("duplicate", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "duplicate", "2026-09-17T11:00:00+00:00", snapshot_suffix="a")
    add_round5_audit(repository, "duplicate", "2026-09-17T11:00:00+00:00", snapshot_suffix="b")

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["ambiguous_probability_revision"] == 1


def test_round5_audit_requires_matching_inner_and_outer_snapshot_identity() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("identity", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "identity", "2026-09-17T11:00:00+00:00")
    repository.markets[0]["payload"]["audit"]["market_snapshot_id"] = "round5:other"

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"]["insufficient_provenance"] == 1


def test_legacy_round5_audit_without_production_evidence_is_excluded() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("legacy", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "legacy", "2026-09-17T11:00:00+00:00")
    record = repository.markets[0]
    audit = record["payload"]["audit"]
    for field in (
        "production_evidence_version",
        "production_evidence_valid",
        "evidence_kind",
        "prediction_id",
        "prediction_revision_number",
        "prediction_revision_id",
        "kickoff_at",
        "persisted_at",
        "leakage_audit_id",
    ):
        audit.pop(field, None)
    record.pop("prediction_revision_id", None)
    record.pop("persisted_at", None)

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"] == {"missing_production_evidence": 1}


def test_replayed_or_post_kickoff_production_evidence_is_excluded() -> None:
    repository = Round6Repository()
    repository.fixtures = [
        fixture("replay", "2026-09-17T12:00:00+00:00"),
        fixture("late-write", "2026-09-17T12:00:00+00:00"),
    ]
    add_round5_audit(repository, "replay", "2026-09-17T11:00:00+00:00")
    add_round5_audit(repository, "late-write", "2026-09-17T11:00:00+00:00")
    replay = repository.markets[0]
    replay["payload"]["audit"]["replayed_prediction"] = True
    late_write = repository.markets[1]
    late_write["persisted_at"] = "2026-09-17T12:00:00+00:00"
    late_write["payload"]["audit"]["persisted_at"] = late_write["persisted_at"]

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"] == {"invalid_production_evidence": 2}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("production_evidence_valid", False),
        ("evidence_kind", "historical_replay"),
    ],
)
def test_forged_production_marker_is_excluded(field: str, value: object) -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("forged", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "forged", "2026-09-17T11:00:00+00:00")
    repository.markets[0]["payload"]["audit"][field] = value

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"] == {"invalid_production_evidence": 1}


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("invalid_id", "invalid_prediction_revision"),
        ("missing", "missing_prediction_revision"),
        ("fixture", "prediction_revision_mismatch"),
        ("cutoff", "prediction_revision_mismatch"),
        ("feature", "prediction_revision_mismatch"),
        ("model", "prediction_revision_mismatch"),
        ("probability_home", "prediction_revision_mismatch"),
        ("probability_draw", "prediction_revision_mismatch"),
        ("probability_away", "prediction_revision_mismatch"),
        ("probability_model_version", "prediction_revision_mismatch"),
        ("probability_calculation_version", "prediction_revision_mismatch"),
        ("leakage", "prediction_revision_mismatch"),
    ],
)
def test_production_evidence_requires_matching_persisted_revision(
    case: str,
    reason: str,
) -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("revision", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "revision", "2026-09-17T11:00:00+00:00")
    revision_key = next(iter(repository.revisions))
    if case == "invalid_id":
        record = repository.markets[0]
        record["prediction_revision_id"] = "invalid-revision-id"
        record["payload"]["audit"]["prediction_revision_id"] = (
            "invalid-revision-id"
        )
    elif case == "missing":
        repository.revisions.clear()
    elif case == "leakage":
        repository.audits[0]["prediction_id"] = "other-prediction"
    else:
        replacement = {
            "fixture": {"fixture_id": "other"},
            "cutoff": {"prediction_cutoff_at": "2026-09-17T10:00:00+00:00"},
            "feature": {"feature_snapshot_id": "feature:other"},
            "model": {"model_key": "other-model"},
            "probability_home": {"probability_home": 0.51},
            "probability_draw": {"probability_draw": 0.31},
            "probability_away": {"probability_away": 0.21},
            "probability_model_version": {
                "probability_model_version": "tampered-model-version"
            },
            "probability_calculation_version": {
                "probability_calculation_version": "tampered-calculation-version"
            },
        }[case]
        repository.revisions[revision_key].update(replacement)

    report = TemporalBacktestService(repository).run()

    assert report["observation_count"] == 0
    assert report["exclusion_reasons"] == {reason: 1}


def test_report_and_content_addressed_run_are_reproducible() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("stable", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "stable", "2026-09-17T11:00:00+00:00")
    service = TemporalBacktestService(repository)

    first = service.run(limit=30)
    second = service.run(limit=30)
    first_run = build_round6_backtest_run(first)
    second_run = build_round6_backtest_run(second)

    assert first == second
    assert first_run == second_run
    assert first_run["run_id"].startswith("round6:")


def test_limit_bounds_fixture_and_provenance_reads_before_evaluation() -> None:
    repository = Round6Repository()
    repository.fixtures = [
        fixture("old", "2026-09-15T12:00:00+00:00"),
        fixture("middle", "2026-09-16T12:00:00+00:00"),
        fixture("new", "2026-09-17T12:00:00+00:00"),
    ]
    for fixture_id, cutoff in (
        ("old", "2026-09-15T11:00:00+00:00"),
        ("middle", "2026-09-16T11:00:00+00:00"),
        ("new", "2026-09-17T11:00:00+00:00"),
    ):
        add_round5_audit(repository, fixture_id, cutoff)

    report = TemporalBacktestService(repository).run(limit=2)

    assert report["fixtures"] == {
        "discovered": 2,
        "eligible": 2,
        "evaluated": 2,
        "excluded": 0,
    }
    assert [row["fixture_id"] for row in report["observations"]] == ["middle", "new"]
    assert repository.leakage_requests == [
        [
            "feature:middle:2026-09-16T11:00:00+00:00",
            "feature:new:2026-09-17T11:00:00+00:00",
        ]
    ]
    assert TemporalBacktestService(repository).run(limit=0)["fixtures"]["discovered"] == 0


def test_fingerprint_covers_deterministic_report_configuration() -> None:
    repository = Round6Repository()
    repository.fixtures = [fixture("fingerprint", "2026-09-17T12:00:00+00:00")]
    add_round5_audit(repository, "fingerprint", "2026-09-17T11:00:00+00:00")

    default_report = TemporalBacktestService(repository, min_samples=30).run()
    displayable_report = TemporalBacktestService(repository, min_samples=1).run()

    assert default_report["observations"] == displayable_report["observations"]
    assert default_report["status"] == "insufficient_data"
    assert displayable_report["status"] == "ok"
    assert (
        default_report["provenance"]["dataset_fingerprint"]
        != displayable_report["provenance"]["dataset_fingerprint"]
    )


def test_round6_admin_get_is_read_only_and_post_is_append_only(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Round6Repository()
    kickoff = datetime.fromisoformat("2026-09-17T12:00:00+00:00")
    for index in range(30):
        fixture_id = f"api-{index}"
        fixture_kickoff = kickoff + timedelta(days=index)
        repository.fixtures.append(fixture(fixture_id, fixture_kickoff.isoformat()))
        add_round5_audit(
            repository,
            fixture_id,
            (fixture_kickoff - timedelta(hours=1)).isoformat(),
        )
    monkeypatch.setattr(main_module, "repository", repository)
    client = TestClient(main_module.app)

    assert client.get("/api/admin/backtest/probability").status_code == 401
    response = client.get(
        "/api/admin/backtest/probability",
        headers=ADMIN,
        params={"limit": 30},
    )
    assert response.status_code == 200
    assert response.json()["observation_count"] == 30
    assert repository.saved_runs == []

    rejected = client.post(
        "/api/admin/backtest/probability",
        headers=ADMIN,
        json={"model_weight": 0.7},
    )
    assert rejected.status_code == 422
    assert repository.saved_runs == []

    first = client.post(
        "/api/admin/backtest/probability",
        headers=ADMIN,
        json={"limit": 30},
    )
    second = client.post(
        "/api/admin/backtest/probability",
        headers=ADMIN,
        json={"limit": 30},
    )
    assert first.status_code == 200
    assert first.json()["reused"] is False
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == first.json()["run_id"]
    assert repository.saved_runs == [first.json()["run_id"]]
