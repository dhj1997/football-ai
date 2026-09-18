"""Focused Round 6.5 production-evidence and persistence contracts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import app.database as database_module
from app.database import PredictionRepository
from app.production_evidence import (
    ProductionEvidenceError,
    is_production_evidence,
    validate_production_evidence,
)


CUTOFF = "2026-09-17T10:00:00+00:00"
PERSISTED = "2026-09-17T10:01:00+00:00"
KICKOFF = "2026-09-17T12:00:00+00:00"
FIXTURE_ID = "fixture-round6-5"
FEATURE_ID = "feature:round6-5"
ODDS_ID = "odds:round6-5"
REVISION_ID = "prediction-round6-5:1"

MODEL = {"home": 0.50, "draw": 0.30, "away": 0.20}
MARKET = {"home": 0.40, "draw": 0.35, "away": 0.25}
FINAL = {"home": 0.46, "draw": 0.32, "away": 0.22}


def evidence_parts(*, market_status: str = "MODEL_PLUS_MARKET") -> tuple[dict, dict, list[dict], dict]:
    """Build one complete, cutoff-safe evidence chain for validator tests."""

    feature = {
        "snapshot_id": FEATURE_ID,
        "fixture_id": FIXTURE_ID,
        "prediction_cutoff_at": CUTOFF,
        "computed_at": CUTOFF,
        "feature_version": "round3-feature-engine-v2",
        "features": [
            {
                "feature_name": "team_elo",
                "feature_value": 1500.0,
                "source": "completed_match_results",
                "source_record_id": "result:prior",
                "available_at": "2026-09-17T09:59:00+00:00",
                "prediction_cutoff_at": CUTOFF,
                "status": "available",
            }
        ],
    }
    leakage = {
        "audit_id": "leakage:round6-5",
        "prediction_id": "prediction-round6-5",
        "feature_snapshot_id": FEATURE_ID,
        "status": "PASS",
        "prediction_cutoff_at": CUTOFF,
    }
    source_ids = [ODDS_ID] if market_status == "MODEL_PLUS_MARKET" else []
    audit = {
        "production_evidence_valid": True,
        "evidence_kind": "production_prediction",
        "production_evidence_version": "round6.5-production-evidence-v1",
        "fixture_id": FIXTURE_ID,
        "prediction_revision_id": REVISION_ID,
        "prediction_cutoff_at": CUTOFF,
        "kickoff_at": KICKOFF,
        "persisted_at": PERSISTED,
        "feature_snapshot_id": FEATURE_ID,
        "leakage_audit_id": leakage["audit_id"],
        "source_odds_snapshot_ids": source_ids,
        "model_probability": MODEL,
        "market_probability": MARKET if source_ids else None,
        "final_probability": FINAL if source_ids else MODEL,
        "market_status": market_status,
        "probability_model_version": "poisson-dc-v2.0.0",
        "probability_calculation_version": "round4-probability-engine-v1",
    }
    evidence = {
        "fixture_id": FIXTURE_ID,
        "round5_probability_audit": audit,
        "feature_snapshot": feature,
        "leakage_audit": leakage,
    }
    odds = [
        {
            "id": ODDS_ID,
            "fixture_id": FIXTURE_ID,
            "captured_at": CUTOFF,
            "source_updated_at": CUTOFF,
        }
    ]
    return evidence, feature, odds, leakage


def repository(tmp_path) -> PredictionRepository:
    repo = PredictionRepository(str(tmp_path / "round6-5.db"), competition_id="round6-5")
    repo.initialize()
    return repo


def production_write_parts(repo: PredictionRepository) -> tuple[dict, dict, dict, str, str]:
    """Persist the prerequisites for one MODEL_ONLY atomic production write."""

    now = datetime.now(UTC)
    cutoff = (now - timedelta(minutes=5)).isoformat()
    kickoff = (now + timedelta(hours=1)).isoformat()
    prediction_id = "prediction-production-round6-5"
    evidence_id = "evidence-production-round6-5"
    feature_id = "feature-production-round6-5"
    feature_version = "round3-feature-engine-v2"
    evidence_payload = {"fixture": {"id": FIXTURE_ID}}
    repo.upsert_fixture(
        {
            "id": FIXTURE_ID,
            "provider_id": None,
            "league_key": "round6-5",
            "fixture_date": kickoff[:10],
            "kickoff": kickoff,
            "status": "scheduled",
        }
    )
    repo.save_evidence_snapshot(
        {
            "id": evidence_id,
            "fixture_id": FIXTURE_ID,
            "created_at": cutoff,
            "captured_at": cutoff,
            "evidence_version": "round2-evidence-v1",
            "hash_algorithm": "sha256",
            "source_synced_at": cutoff,
            "content_hash": hashlib.sha256(
                json.dumps(
                    evidence_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "payload": evidence_payload,
        }
    )
    repo.save_feature_snapshot(
        {
            "snapshot_id": feature_id,
            "fixture_id": FIXTURE_ID,
            "prediction_id": prediction_id,
            "evidence_snapshot_id": evidence_id,
            "prediction_cutoff_at": cutoff,
            "computed_at": cutoff,
            "feature_version": feature_version,
            "leakage_detected": False,
            "features": [
                {
                    "feature_name": "team_elo",
                    "feature_value": 1500.0,
                    "source": "completed_match_results",
                    "source_record_id": "result:prior",
                    "computed_at": cutoff,
                    "available_at": cutoff,
                    "prediction_cutoff_at": cutoff,
                    "feature_version": feature_version,
                    "snapshot_id": feature_id,
                    "status": "available",
                }
            ],
        }
    )
    leakage = repo.save_leakage_audit(
        {
            "audit_id": "leakage-production-round6-5",
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_id,
            "status": "PASS",
            "prediction_cutoff_at": cutoff,
            "violations": [],
            "features_checked": 1,
            "features_passed": 1,
            "features_failed": 0,
            "created_at": cutoff,
        }
    )
    prediction = {
        "id": prediction_id,
        "fixture_id": FIXTURE_ID,
        "created_at": cutoff,
        "prediction_cutoff_at": cutoff,
        "phase": "preliminary",
        "model_version": "poisson:round6-5-test",
        "model_key": "poisson",
        "competition_id": "round6-5",
        "prompt_version": "round6-5-test",
        "evidence_snapshot_id": evidence_id,
        "feature_snapshot_id": feature_id,
        "feature_version": feature_version,
        "probabilities": MODEL,
        "expected_goals": {"home": 1.4, "away": 0.9},
    }
    revision = {
        **prediction,
        "prediction_id": prediction_id,
        "probability_home": MODEL["home"],
        "probability_draw": MODEL["draw"],
        "probability_away": MODEL["away"],
        "probability_model_version": "poisson-dc-v2.0.0",
        "probability_calculation_version": "round4-probability-engine-v1",
    }
    raw_audit = {
        "fixture_id": FIXTURE_ID,
        "prediction_cutoff_at": cutoff,
        "feature_snapshot_id": feature_id,
        "source_odds_snapshot_ids": [],
        "model_probability": MODEL,
        "market_probability": None,
        "final_probability": MODEL,
        "market_status": "MODEL_ONLY",
        "probability_model_version": "poisson-dc-v2.0.0",
        "probability_calculation_version": "round4-probability-engine-v1",
    }
    round5_result = {
        "round5_probability_audit": raw_audit,
        "market_prior_detail": {"status": "unavailable"},
        "market_snapshot": {
            "market_snapshot_id": "unbound-round5-result",
            "fixture_id": FIXTURE_ID,
            "market": "1x2",
            "captured_at": cutoff,
            "overround": None,
            "payload": {
                "snapshot_type": "round5_probability_audit",
                "audit": raw_audit,
                "market_prior": {"status": "unavailable"},
            },
        },
    }
    return prediction, revision, round5_result, kickoff, leakage["audit_id"]


def production_row_counts(repo: PredictionRepository) -> tuple[int, int, int]:
    with repo.engine.connect() as connection:
        return (
            int(connection.execute(text("SELECT COUNT(*) FROM predictions")).scalar() or 0),
            int(
                connection.execute(text("SELECT COUNT(*) FROM prediction_revisions")).scalar()
                or 0
            ),
            int(connection.execute(text("SELECT COUNT(*) FROM market_snapshots")).scalar() or 0),
        )


def test_validator_normalizes_complete_model_plus_market_evidence() -> None:
    evidence, feature, odds, leakage = evidence_parts()

    normalized = validate_production_evidence(
        evidence,
        feature_snapshot=feature,
        odds_snapshots=odds,
        leakage_audit=leakage,
    )

    assert normalized["production_evidence_valid"] is True
    assert normalized["evidence_kind"] == "production_prediction"
    assert normalized["prediction_revision_id"] == REVISION_ID
    assert normalized["feature_snapshot_id"] == FEATURE_ID
    assert normalized["source_odds_snapshot_ids"] == [ODDS_ID]
    assert normalized["leakage_audit_id"] == leakage["audit_id"]
    assert normalized["market_probability"] == MARKET
    assert normalized["final_probability"] == FINAL


def test_validator_accepts_model_only_without_market_provenance() -> None:
    evidence, feature, odds, leakage = evidence_parts(market_status="MODEL_ONLY")

    normalized = validate_production_evidence(
        evidence,
        feature_snapshot=feature,
        odds_snapshots=odds,
        leakage_audit=leakage,
    )

    assert normalized["market_status"] == "MODEL_ONLY"
    assert normalized["source_odds_snapshot_ids"] == []
    assert normalized["market_probability"] is None
    assert normalized["model_probability"] == normalized["final_probability"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("production_evidence_valid", False, "explicitly marked valid"),
        ("evidence_kind", "historical_replay", "evidence_kind"),
        ("production_evidence_version", "legacy", "production_evidence_version"),
    ],
)
def test_validator_requires_explicit_production_markers(
    field: str,
    value: object,
    message: str,
) -> None:
    evidence, feature, odds, leakage = evidence_parts()
    evidence["round5_probability_audit"][field] = value

    with pytest.raises(ProductionEvidenceError, match=message):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("persisted_at", None),
        ("persisted_at", "2026-09-17T09:59:59+00:00"),
        ("persisted_at", KICKOFF),
    ],
)
def test_validator_requires_a_real_pre_kickoff_persistence_time(field: str, value: str | None) -> None:
    evidence, feature, odds, leakage = evidence_parts()
    evidence["round5_probability_audit"][field] = value

    with pytest.raises(ProductionEvidenceError, match="persisted_at"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )


def test_validator_rejects_historical_replay_even_with_complete_chain() -> None:
    evidence, feature, odds, leakage = evidence_parts()

    with pytest.raises(ProductionEvidenceError, match="historical replay"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
            replay=True,
        )

    assert is_production_evidence(
        evidence,
        feature_snapshot=feature,
        odds_snapshots=odds,
        leakage_audit=leakage,
        replay=True,
    ) is False


@pytest.mark.parametrize("status", ["FAIL", "WARN", "UNKNOWN", ""])
def test_validator_requires_pass_leakage_audit(status: str) -> None:
    evidence, feature, odds, leakage = evidence_parts()
    leakage["status"] = status

    with pytest.raises(ProductionEvidenceError, match="PASS leakage audit"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )


def test_validator_rejects_feature_or_odds_after_cutoff() -> None:
    evidence, feature, odds, leakage = evidence_parts()
    feature["features"][0]["available_at"] = "2026-09-17T10:00:01+00:00"
    with pytest.raises(ProductionEvidenceError, match="feature available_at"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )

    evidence, feature, odds, leakage = evidence_parts()
    odds[0]["source_updated_at"] = "2026-09-17T10:00:01+00:00"
    with pytest.raises(ProductionEvidenceError, match="odds source_updated_at"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )


def test_validator_keeps_model_only_and_model_plus_market_boundaries() -> None:
    evidence, feature, odds, leakage = evidence_parts(market_status="MODEL_ONLY")
    evidence["round5_probability_audit"]["source_odds_snapshot_ids"] = [ODDS_ID]
    with pytest.raises(ProductionEvidenceError, match="MODEL_ONLY"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )

    evidence, feature, odds, leakage = evidence_parts()
    evidence["round5_probability_audit"]["source_odds_snapshot_ids"] = []
    with pytest.raises(ProductionEvidenceError, match="source odds"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )


def test_validator_rejects_probability_or_identity_mismatch() -> None:
    evidence, feature, odds, leakage = evidence_parts()
    evidence["round5_probability_audit"]["final_probability"] = {
        "home": 0.5,
        "draw": 0.3,
        "away": 0.3,
    }
    with pytest.raises(ProductionEvidenceError, match="sum to one"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )

    evidence, feature, odds, leakage = evidence_parts()
    feature["fixture_id"] = "another-fixture"
    with pytest.raises(ProductionEvidenceError, match="fixture_id"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )

    evidence, feature, odds, leakage = evidence_parts()
    evidence["round5_probability_audit"]["leakage_audit_id"] = "another-audit"
    with pytest.raises(ProductionEvidenceError, match="leakage_audit_id"):
        validate_production_evidence(
            evidence,
            feature_snapshot=feature,
            odds_snapshots=odds,
            leakage_audit=leakage,
        )


def test_initialize_adds_nullable_persisted_at_to_legacy_market_table(tmp_path) -> None:
    repo = PredictionRepository(str(tmp_path / "legacy-schema.db"), competition_id="round6-5")
    with repo.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE market_snapshots ("
                "market_snapshot_id VARCHAR(255) PRIMARY KEY, "
                "fixture_id VARCHAR(255) NOT NULL, "
                "market VARCHAR(64) NOT NULL, "
                "captured_at VARCHAR(64) NOT NULL, "
                "overround DECIMAL(10, 6) NULL, "
                "payload TEXT NOT NULL)"
            )
        )

    repo.initialize()
    columns = {column["name"]: column for column in inspect(repo.engine).get_columns("market_snapshots")}
    assert columns["persisted_at"]["nullable"] is True


def test_legacy_market_snapshot_keeps_null_persisted_at_and_is_not_backfilled(tmp_path) -> None:
    repo = repository(tmp_path)
    payload = {
        "market_snapshot_id": "legacy-market-1",
        "fixture_id": "legacy-fixture",
        "market": "1x2",
        "captured_at": CUTOFF,
        "payload": {"snapshot_type": "round5_probability_audit"},
    }
    with repo.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO market_snapshots "
                "(market_snapshot_id, fixture_id, market, captured_at, overround, payload) "
                "VALUES (:id, :fixture_id, :market, :captured_at, NULL, :payload)"
            ),
            {
                "id": payload["market_snapshot_id"],
                "fixture_id": payload["fixture_id"],
                "market": payload["market"],
                "captured_at": payload["captured_at"],
                "payload": json.dumps(payload),
            },
        )

    with repo.engine.connect() as connection:
        persisted_at = connection.execute(
            text("SELECT persisted_at FROM market_snapshots WHERE market_snapshot_id = :id"),
            {"id": payload["market_snapshot_id"]},
        ).scalar()
    assert persisted_at is None
    rows = repo.market_snapshots("legacy-fixture")
    assert rows[0]["market_snapshot_id"] == payload["market_snapshot_id"]
    assert rows[0].get("persisted_at") is None


def test_generic_market_snapshot_is_idempotent_but_not_production_evidence(tmp_path) -> None:
    repo = repository(tmp_path)
    record = {
        "market_snapshot_id": "round6-5-market-1",
        "fixture_id": FIXTURE_ID,
        "market": "1x2",
        "captured_at": CUTOFF,
        "overround": 0.04,
        "payload": {"snapshot_type": "round5_probability_audit", "audit_id": "audit-1"},
    }

    repo.save_market_snapshot(record)
    repo.save_market_snapshot(deepcopy(record))

    with repo.engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM market_snapshots WHERE market_snapshot_id = :id"),
            {"id": record["market_snapshot_id"]},
        ).scalar()
        persisted_at = connection.execute(
            text("SELECT persisted_at FROM market_snapshots WHERE market_snapshot_id = :id"),
            {"id": record["market_snapshot_id"]},
        ).scalar()
    assert count == 1
    assert persisted_at is None

    changed = deepcopy(record)
    changed["payload"]["audit_id"] = "audit-2"
    with pytest.raises(ValueError, match="immutable"):
        repo.save_market_snapshot(changed)

    forged = deepcopy(record)
    forged["market_snapshot_id"] = "forged-production-timestamp"
    forged["persisted_at"] = PERSISTED
    with pytest.raises(ValueError, match="assigned only by the atomic"):
        repo.save_market_snapshot(forged)


def test_atomic_production_writer_owns_timestamp_revision_link_and_idempotency(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    started_at = datetime.now(UTC)

    first = repo.save_prediction_with_production_evidence(
        prediction,
        revision,
        round5_result,
        kickoff_at=kickoff,
        leakage_audit_id=leakage_audit_id,
    )
    finished_at = datetime.now(UTC)
    second = repo.save_prediction_with_production_evidence(
        prediction,
        revision,
        round5_result,
        kickoff_at=kickoff,
        leakage_audit_id=leakage_audit_id,
    )

    stored = first["market_snapshot"]
    persisted_at = datetime.fromisoformat(stored["persisted_at"])
    audit = stored["payload"]["audit"]
    assert started_at <= persisted_at <= finished_at
    assert persisted_at < datetime.fromisoformat(kickoff)
    assert audit["persisted_at"] == stored["persisted_at"]
    assert audit["prediction_revision_id"] == (
        f"{prediction['id']}:{first['revision']['revision_number']}"
    )
    assert audit["leakage_audit_id"] == leakage_audit_id
    assert audit["production_evidence_valid"] is True
    assert second == first

    with repo.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT persisted_at FROM market_snapshots "
                "WHERE market_snapshot_id = :market_snapshot_id"
            ),
            {"market_snapshot_id": stored["market_snapshot_id"]},
        ).fetchall()
    assert rows == [(stored["persisted_at"],)]
    assert repo.market_snapshots(FIXTURE_ID) == [stored]

    conflicting = deepcopy(round5_result)
    conflicting["round5_probability_audit"]["fusion_version"] = "another-fusion-version"
    with pytest.raises(ValueError, match="immutable"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            conflicting,
            kickoff_at=kickoff,
            leakage_audit_id=leakage_audit_id,
        )
    assert production_row_counts(repo) == (1, 1, 1)
    assert repo.market_snapshots(FIXTURE_ID) == [stored]


def test_atomic_production_writer_rolls_back_every_row_after_final_insert_failure(
    tmp_path,
    monkeypatch,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    insert_market_snapshot = repo._insert_market_snapshot

    def fail_after_insert(connection, item, *, persisted_at):
        insert_market_snapshot(connection, item, persisted_at=persisted_at)
        raise RuntimeError("forced failure after market snapshot insert")

    monkeypatch.setattr(repo, "_insert_market_snapshot", fail_after_insert)

    with pytest.raises(RuntimeError, match="forced failure"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            round5_result,
            kickoff_at=kickoff,
            leakage_audit_id=leakage_audit_id,
        )

    assert production_row_counts(repo) == (0, 0, 0)


@pytest.mark.parametrize("delay", [timedelta(0), timedelta(seconds=1)])
def test_atomic_production_writer_rejects_persistence_at_or_after_kickoff(
    tmp_path,
    monkeypatch,
    delay: timedelta,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    frozen_at = datetime.fromisoformat(kickoff) + delay

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_at if tz is not None else frozen_at.replace(tzinfo=None)

    monkeypatch.setattr(database_module, "datetime", FrozenDateTime)

    with pytest.raises(ValueError, match="between cutoff and kickoff"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            round5_result,
            kickoff_at=kickoff,
            leakage_audit_id=leakage_audit_id,
        )

    assert production_row_counts(repo) == (0, 0, 0)


def test_atomic_production_writer_rejects_stale_caller_kickoff(tmp_path) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    stale_kickoff = (datetime.fromisoformat(kickoff) + timedelta(hours=1)).isoformat()

    with pytest.raises(ValueError, match="persisted fixture"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            round5_result,
            kickoff_at=stale_kickoff,
            leakage_audit_id=leakage_audit_id,
        )

    assert production_row_counts(repo) == (0, 0, 0)


def test_atomic_production_writer_rejects_non_scheduled_persisted_fixture(
    tmp_path,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    fixture = repo.fixture(FIXTURE_ID)
    fixture["status"] = "live"
    repo.upsert_fixture(fixture)

    with pytest.raises(ValueError, match="no longer scheduled"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            round5_result,
            kickoff_at=kickoff,
            leakage_audit_id=leakage_audit_id,
        )

    assert production_row_counts(repo) == (0, 0, 0)


def test_atomic_production_writer_rolls_back_when_transaction_crosses_kickoff(
    tmp_path,
    monkeypatch,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    kickoff_time = datetime.fromisoformat(kickoff)
    clock = iter((kickoff_time - timedelta(microseconds=1), kickoff_time))

    class CrossingDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = next(clock)
            return value if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(database_module, "datetime", CrossingDateTime)

    with pytest.raises(ValueError, match="complete before kickoff"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            round5_result,
            kickoff_at=kickoff,
            leakage_audit_id=leakage_audit_id,
        )

    assert production_row_counts(repo) == (0, 0, 0)


@pytest.mark.parametrize("fixture_change", ["live", "finished", "rescheduled"])
def test_atomic_production_writer_returns_pre_kickoff_evidence_on_late_retry(
    tmp_path,
    monkeypatch,
    fixture_change: str,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    first = repo.save_prediction_with_production_evidence(
        prediction,
        revision,
        round5_result,
        kickoff_at=kickoff,
        leakage_audit_id=leakage_audit_id,
    )
    fixture = repo.fixture(FIXTURE_ID)
    if fixture_change == "rescheduled":
        fixture["kickoff"] = (
            datetime.fromisoformat(kickoff) + timedelta(hours=1)
        ).isoformat()
    else:
        fixture["status"] = fixture_change
    repo.upsert_fixture(fixture)
    after_kickoff = datetime.fromisoformat(kickoff) + timedelta(seconds=1)

    class AfterKickoffDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (
                after_kickoff
                if tz is not None
                else after_kickoff.replace(tzinfo=None)
            )

    monkeypatch.setattr(database_module, "datetime", AfterKickoffDateTime)

    second = repo.save_prediction_with_production_evidence(
        prediction,
        revision,
        round5_result,
        kickoff_at=kickoff,
        leakage_audit_id=leakage_audit_id,
    )

    assert second == first
    assert production_row_counts(repo) == (1, 1, 1)


@pytest.mark.parametrize(
    "field", ["probability_model_version", "probability_calculation_version"]
)
@pytest.mark.parametrize("value", [None, "tampered-version"])
def test_atomic_production_writer_requires_matching_probability_versions(
    tmp_path, field: str, value: str | None,
) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    revision[field] = value

    with pytest.raises(ValueError, match="must match Round 5 audit"):
        repo.save_prediction_with_production_evidence(
            prediction,
            revision,
            round5_result,
            kickoff_at=kickoff,
            leakage_audit_id=leakage_audit_id,
        )

    assert production_row_counts(repo) == (0, 0, 0)


@pytest.mark.parametrize(
    "table",
    ["predictions", "prediction_revisions", "market_snapshots"],
)
def test_atomic_production_writer_retries_unique_races_across_chain(
    tmp_path,
    table: str,
) -> None:
    repo = repository(tmp_path)
    error = IntegrityError(
        f"INSERT INTO {table}",
        {},
        RuntimeError(f"UNIQUE constraint failed: {table}.id"),
    )

    assert repo._is_retryable_revision_error(error) is True


@pytest.mark.parametrize(
    "message",
    [
        "NOT NULL constraint failed: predictions.fixture_id",
        "CHECK constraint failed: prediction_revisions",
        "FOREIGN KEY constraint failed",
    ],
)
def test_non_unique_integrity_errors_are_not_retried(message: str) -> None:
    error = IntegrityError("INSERT INTO predictions", {}, RuntimeError(message))

    assert PredictionRepository._is_retryable_revision_error(error) is False


def test_atomic_production_writer_accepts_cutoff_safe_stored_market_odds(tmp_path) -> None:
    repo = repository(tmp_path)
    prediction, revision, round5_result, kickoff, leakage_audit_id = (
        production_write_parts(repo)
    )
    cutoff = prediction["prediction_cutoff_at"]
    odds_id = "odds-production-round6-5"
    repo.save_odds_snapshot(
        {
            "snapshot_id": odds_id,
            "fixture_id": FIXTURE_ID,
            "captured_at": cutoff,
            "source_updated_at": cutoff,
            "source": "round6-5-test",
            "quotes": [
                {
                    "market": "1x2",
                    "selection": selection,
                    "price": price,
                    "bookmaker": "test-book",
                    "captured_at": cutoff,
                    "source_updated_at": cutoff,
                }
                for selection, price in (("home", 2.5), ("draw", 3.0), ("away", 4.0))
            ],
        }
    )
    round5_result["round5_probability_audit"].update(
        {
            "source_odds_snapshot_ids": [odds_id],
            "market_probability": MARKET,
            "final_probability": FINAL,
            "market_status": "MODEL_PLUS_MARKET",
        }
    )
    round5_result["market_prior_detail"] = {
        "status": "available",
        "source_odds_snapshot_ids": [odds_id],
        "probabilities": MARKET,
    }

    result = repo.save_prediction_with_production_evidence(
        prediction,
        revision,
        round5_result,
        kickoff_at=kickoff,
        leakage_audit_id=leakage_audit_id,
    )

    audit = result["market_snapshot"]["payload"]["audit"]
    stored_odds = repo.odds_snapshot(odds_id)
    assert audit["market_status"] == "MODEL_PLUS_MARKET"
    assert audit["source_odds_snapshot_ids"] == [odds_id]
    assert audit["market_probability"] == MARKET
    assert audit["final_probability"] == FINAL
    assert stored_odds is not None
    assert stored_odds["captured_at"] == cutoff
    assert stored_odds["source_updated_at"] == cutoff
