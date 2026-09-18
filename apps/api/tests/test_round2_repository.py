"""Round 2 immutable feature, revision, retention and reproduction persistence."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.database import PredictionRepository
from app.leakage_audit import LeakageAuditService
from app.prediction_intelligence import build_feature_snapshot
from app.prompt_contract import DEFAULT_PROMPT_CONTRACT


FEATURE_VERSION = "round2-feature-v1"
MODEL_VERSION = "poisson:round2-test"


def repository(tmp_path) -> PredictionRepository:
    result = PredictionRepository(str(tmp_path / "round2.db"), competition_id="round2")
    result.initialize()
    return result


def save_evidence(
    repository: PredictionRepository,
    prediction_id: str,
    captured_at: str,
) -> str:
    snapshot_id = f"evidence-{prediction_id}"
    repository.save_evidence_snapshot(
        {
            "id": snapshot_id,
            "fixture_id": "fixture-round2",
            "created_at": captured_at,
            "captured_at": captured_at,
            "source_synced_at": captured_at,
            "content_hash": prediction_id.ljust(64, "0")[:64],
            "payload": {"fixture": {"id": "fixture-round2"}},
        }
    )
    return snapshot_id


def save_features(
    repository: PredictionRepository,
    prediction_id: str,
    evidence_snapshot_id: str,
    cutoff: str,
) -> str:
    snapshot_id = f"features-{prediction_id}"
    repository.save_feature_snapshot(
        {
            "snapshot_id": snapshot_id,
            "fixture_id": "fixture-round2",
            "prediction_id": prediction_id,
            "evidence_snapshot_id": evidence_snapshot_id,
            "prediction_cutoff_at": cutoff,
            "computed_at": cutoff,
            "feature_version": FEATURE_VERSION,
            "leakage_detected": False,
            "features": [
                {
                    "feature_name": "home_last_5_points",
                    "feature_value": 11,
                    "source": "fixture_results",
                    "source_record_id": "fixture-history-5",
                    "computed_at": cutoff,
                    "available_at": cutoff,
                    "prediction_cutoff_at": cutoff,
                    "feature_version": FEATURE_VERSION,
                    "snapshot_id": snapshot_id,
                }
            ],
        }
    )
    return snapshot_id


def prediction(
    prediction_id: str,
    created_at: str,
    evidence_snapshot_id: str,
    feature_snapshot_id: str,
    *,
    prompt_version: str | None = None,
    home_probability: float = 0.55,
) -> dict:
    return {
        "id": prediction_id,
        "fixture_id": "fixture-round2",
        "created_at": created_at,
        "prediction_cutoff_at": created_at,
        "phase": "preliminary",
        "model_version": MODEL_VERSION,
        "model_key": "poisson",
        "competition_id": "round2",
        "prompt_version": prompt_version or DEFAULT_PROMPT_CONTRACT.version,
        "evidence_snapshot_id": evidence_snapshot_id,
        "feature_snapshot_id": feature_snapshot_id,
        "feature_version": FEATURE_VERSION,
        "probabilities": {
            "home": home_probability,
            "draw": 0.25,
            "away": round(0.75 - home_probability, 2),
        },
        "expected_goals": {"home": 1.6, "away": 0.9},
        "uncertainty": 0.12,
        "data_quality": 0.91,
        "model_agreement": 0.88,
        "ai": {
            "status": "completed",
            "provider": "poisson",
            "prompt_version": prompt_version or DEFAULT_PROMPT_CONTRACT.version,
        },
    }


def save_complete_prediction(
    repository: PredictionRepository,
    prediction_id: str,
    created_at: str,
    **overrides,
) -> tuple[dict, dict]:
    evidence_snapshot_id = save_evidence(repository, prediction_id, created_at)
    feature_snapshot_id = save_features(
        repository,
        prediction_id,
        evidence_snapshot_id,
        created_at,
    )
    item = prediction(
        prediction_id,
        created_at,
        evidence_snapshot_id,
        feature_snapshot_id,
        **overrides,
    )
    audit = LeakageAuditService(repository).audit_feature_snapshot(
        repository.feature_snapshot(feature_snapshot_id),
        prediction_id=prediction_id,
    )
    assert audit["status"] == "PASS"
    revision = repository.save_prediction_with_revision(item)
    return item, revision


def test_round2_schema_initialize_is_idempotent(tmp_path) -> None:
    repo = repository(tmp_path)
    evidence_snapshot_id = save_evidence(
        repo,
        "prediction-schema",
        "2026-09-15T03:00:00+00:00",
    )
    snapshot_id = save_features(
        repo,
        "prediction-schema",
        evidence_snapshot_id,
        "2026-09-15T03:00:00+00:00",
    )

    repo.initialize()

    schema = inspect(repo.engine)
    assert {
        "feature_snapshots",
        "feature_values",
        "prediction_revisions",
        "leakage_audits",
    }.issubset(schema.get_table_names())
    available_at = next(
        column
        for column in schema.get_columns("feature_values")
        if column["name"] == "available_at"
    )
    assert available_at["nullable"] is True
    assert repo.feature_snapshot(snapshot_id) is not None


def test_feature_snapshot_replay_allows_unknown_availability(tmp_path) -> None:
    repo = repository(tmp_path)
    snapshot = {
        "id": "features-unverifiable",
        "fixture_id": "fixture-round2",
        "prediction_id": "prediction-unverifiable",
        "prediction_cutoff_at": "2026-09-15T03:00:00+00:00",
        "computed_at": "2026-09-15T03:00:01+00:00",
        "feature_version": FEATURE_VERSION,
        "features": [
            {
                "feature_name": "injuries.status",
                "feature_value": None,
                "source": "injury_provider",
                "source_record_id": "injuries:fixture-round2",
                "available_at": None,
                "status": "unverifiable",
            }
        ],
    }

    first = repo.save_feature_snapshot(snapshot)
    replay = deepcopy(snapshot)
    replay["computed_at"] = "2026-09-15T03:00:05+00:00"
    replay["features"][0]["computed_at"] = "2026-09-15T03:00:05+00:00"
    persisted = repo.save_feature_snapshot(replay)

    assert first["snapshot_id"] == "features-unverifiable"
    assert persisted["computed_at"] == first["computed_at"]
    assert persisted["features"][0]["available_at"] is None
    changed = deepcopy(replay)
    changed["features"][0]["feature_value"] = "fabricated"
    with pytest.raises(ValueError, match="immutable"):
        repo.save_feature_snapshot(changed)


def test_feature_available_at_boundary(tmp_path) -> None:
    repo = repository(tmp_path)
    cutoff = "2026-09-15T04:00:00+00:00"
    snapshot = build_feature_snapshot(
        {
            "id": "fixture-boundary",
            "canonical_fixture_id": "fixture-boundary",
        },
        {
            "source": "test-odds",
            "odds": {
                "home": 2.0,
                "draw": 3.2,
                "away": 3.8,
                "updated_at": cutoff,
                "source": "test-odds",
                "source_record_ids": ["odds-at-cutoff"],
            },
        },
        cutoff,
    )
    snapshot["prediction_id"] = "prediction-boundary"

    persisted = repo.save_feature_snapshot(snapshot)
    audit = LeakageAuditService(repo).audit_feature_snapshot(
        persisted,
        prediction_id="prediction-boundary",
    )
    odds = next(
        feature
        for feature in persisted["features"]
        if feature["feature_name"] == "odds"
    )

    assert odds["available_at"] == cutoff
    assert odds["prediction_cutoff_at"] == cutoff
    assert odds["status"] == "available"
    assert {
        "feature_name",
        "feature_value",
        "source",
        "source_record_id",
        "computed_at",
        "available_at",
        "prediction_cutoff_at",
        "feature_version",
        "snapshot_id",
    }.issubset(odds)
    assert persisted["leakage_detected"] is False
    assert audit["status"] == "PASS"
    assert audit["violations"] == []


def test_prediction_revision_is_append_only(tmp_path) -> None:
    repo = repository(tmp_path)
    first_prediction, first = save_complete_prediction(
        repo, "prediction-1", "2026-09-15T02:00:00+00:00", home_probability=0.55
    )
    _, second = save_complete_prediction(
        repo, "prediction-2", "2026-09-15T03:00:00+00:00", home_probability=0.61
    )

    assert (first["revision_number"], second["revision_number"]) == (1, 2)
    assert [row["probability_home"] for row in repo.prediction_revisions(fixture_id="fixture-round2")] == [0.55, 0.61]
    assert repo.save_prediction_with_revision(first_prediction) == first

    changed = deepcopy(first)
    changed["probability_home"] = 0.99
    changed["probabilities"]["home"] = 0.99
    with pytest.raises(ValueError, match="immutable"):
        repo.save_prediction_revision(changed)
    assert repo.prediction_revision("prediction-1", 1)["probability_home"] == 0.55


def test_concurrent_revision_allocation_keeps_unique_order(tmp_path) -> None:
    repo = repository(tmp_path)
    predictions = []
    for index in range(8):
        prediction_id = f"prediction-concurrent-{index}"
        cutoff = f"2026-09-15T04:{index:02d}:00+00:00"
        evidence_snapshot_id = save_evidence(repo, prediction_id, cutoff)
        feature_snapshot_id = save_features(
            repo,
            prediction_id,
            evidence_snapshot_id,
            cutoff,
        )
        item = prediction(
            prediction_id,
            cutoff,
            evidence_snapshot_id,
            feature_snapshot_id,
        )
        audit = LeakageAuditService(repo).audit_feature_snapshot(
            repo.feature_snapshot(feature_snapshot_id),
            prediction_id=prediction_id,
        )
        assert audit["status"] == "PASS"
        predictions.append(item)

    def write_revision(item: dict) -> dict:
        return repo.save_prediction_with_revision(item)

    with ThreadPoolExecutor(max_workers=8) as pool:
        revisions = list(pool.map(write_revision, predictions))

    assert sorted(item["revision_number"] for item in revisions) == list(range(1, 9))
    assert len(repo.prediction_revisions(fixture_id="fixture-round2")) == 8


def test_explicit_revision_conflict_is_not_retried(tmp_path, monkeypatch) -> None:
    repo = repository(tmp_path)
    prepared = []
    for index in (1, 2):
        prediction_id = f"prediction-explicit-{index}"
        cutoff = f"2026-09-15T04:0{index}:00+00:00"
        evidence_snapshot_id = save_evidence(repo, prediction_id, cutoff)
        feature_snapshot_id = save_features(
            repo,
            prediction_id,
            evidence_snapshot_id,
            cutoff,
        )
        item = prediction(
            prediction_id,
            cutoff,
            evidence_snapshot_id,
            feature_snapshot_id,
        )
        audit = LeakageAuditService(repo).audit_feature_snapshot(
            repo.feature_snapshot(feature_snapshot_id),
            prediction_id=prediction_id,
        )
        assert audit["status"] == "PASS"
        prepared.append(item)

    repo.save_prediction_with_revision(prepared[0], {"revision_number": 1})
    monkeypatch.setattr(
        "app.database.time.sleep",
        lambda _seconds: pytest.fail("explicit revision conflicts must not be retried"),
    )

    with pytest.raises(IntegrityError):
        repo.save_prediction_with_revision(
            prepared[1],
            {"revision_number": 1},
        )
    assert repo.prediction(prepared[1]["id"]) is None


def test_prediction_and_revision_are_saved_atomically(tmp_path) -> None:
    repo = repository(tmp_path)
    item = prediction(
        "prediction-incomplete",
        "2026-09-15T03:00:00+00:00",
        "missing-evidence",
        "",
    )

    with pytest.raises(ValueError, match="feature_snapshot_id"):
        repo.save_prediction_with_revision(item)

    assert repo.prediction(item["id"]) is None
    assert repo.prediction_revision(item["id"]) is None


def test_standard_save_routes_through_audited_revision_chain(tmp_path) -> None:
    repo = repository(tmp_path)
    prediction_id = "prediction-save-route"
    cutoff = "2026-09-15T03:00:00+00:00"
    evidence_snapshot_id = save_evidence(repo, prediction_id, cutoff)
    feature_snapshot_id = save_features(
        repo,
        prediction_id,
        evidence_snapshot_id,
        cutoff,
    )
    item = prediction(
        prediction_id,
        cutoff,
        evidence_snapshot_id,
        feature_snapshot_id,
    )
    audit = LeakageAuditService(repo).audit_feature_snapshot(
        repo.feature_snapshot(feature_snapshot_id),
        prediction_id=prediction_id,
    )
    assert audit["status"] == "PASS"

    repo.save(item)

    assert repo.prediction(prediction_id) == item
    assert repo.prediction_revision(prediction_id)["feature_snapshot_id"] == feature_snapshot_id


def test_standard_prediction_without_pass_audit_is_rejected_atomically(tmp_path) -> None:
    repo = repository(tmp_path)
    prediction_id = "prediction-without-audit"
    cutoff = "2026-09-15T03:00:00+00:00"
    evidence_snapshot_id = save_evidence(repo, prediction_id, cutoff)
    feature_snapshot_id = save_features(
        repo,
        prediction_id,
        evidence_snapshot_id,
        cutoff,
    )
    item = prediction(
        prediction_id,
        cutoff,
        evidence_snapshot_id,
        feature_snapshot_id,
    )

    with pytest.raises(ValueError, match="PASS leakage audit"):
        repo.save_prediction_with_revision(item)

    assert repo.prediction(prediction_id) is None
    assert repo.prediction_revision(prediction_id) is None


def test_orphan_prediction_revision_is_rejected(tmp_path) -> None:
    repo = repository(tmp_path)
    prediction_id = "prediction-orphan"
    cutoff = "2026-09-15T03:00:00+00:00"
    evidence_snapshot_id = save_evidence(repo, prediction_id, cutoff)
    feature_snapshot_id = save_features(
        repo,
        prediction_id,
        evidence_snapshot_id,
        cutoff,
    )
    item = prediction(
        prediction_id,
        cutoff,
        evidence_snapshot_id,
        feature_snapshot_id,
    )
    audit = LeakageAuditService(repo).audit_feature_snapshot(
        repo.feature_snapshot(feature_snapshot_id),
        prediction_id=prediction_id,
    )
    assert audit["status"] == "PASS"

    with pytest.raises(ValueError, match="prediction prediction-orphan was not found"):
        repo.save_prediction_revision({**item, "prediction_id": prediction_id})

    assert repo.prediction_revision(prediction_id) is None


def test_revision_identity_mismatch_rolls_back_prediction(tmp_path) -> None:
    repo = repository(tmp_path)
    snapshot_owner = "prediction-snapshot-owner"
    prediction_id = "prediction-wrong-owner"
    cutoff = "2026-09-15T03:00:00+00:00"
    evidence_snapshot_id = save_evidence(repo, snapshot_owner, cutoff)
    feature_snapshot_id = save_features(
        repo,
        snapshot_owner,
        evidence_snapshot_id,
        cutoff,
    )
    item = prediction(
        prediction_id,
        cutoff,
        evidence_snapshot_id,
        feature_snapshot_id,
    )
    item["fixture_id"] = "fixture-other"
    repo.save_leakage_audit(
        {
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "status": "PASS",
            "prediction_cutoff_at": cutoff,
            "violations": [],
            "features_checked": 1,
            "features_passed": 1,
            "features_failed": 0,
            "audited_at": cutoff,
        }
    )

    with pytest.raises(ValueError, match="feature_snapshot.fixture_id"):
        repo.save_prediction_with_revision(item)

    assert repo.prediction(prediction_id) is None
    assert repo.prediction_revision(prediction_id) is None


def test_legacy_prediction_without_feature_snapshot_key_remains_supported(tmp_path) -> None:
    repo = repository(tmp_path)
    legacy = prediction(
        "prediction-legacy-bare",
        "2026-09-15T03:00:00+00:00",
        "",
        "",
    )
    legacy.pop("feature_snapshot_id")

    repo.save(legacy)

    assert repo.prediction(legacy["id"]) == legacy
    assert repo.prediction_revision(legacy["id"]) is None


def test_prediction_revision_survives_retention(tmp_path) -> None:
    repo = repository(tmp_path)
    old, old_revision = save_complete_prediction(
        repo,
        "prediction-old",
        "2026-09-15T02:00:00+00:00",
        prompt_version="legacy-prompt",
    )
    save_complete_prediction(repo, "prediction-current", "2026-09-15T03:00:00+00:00")
    audit = repo.save_leakage_audit(
        {
            "audit_id": "audit-old",
            "prediction_id": old["id"],
            "feature_snapshot_id": old["feature_snapshot_id"],
            "status": "PASS",
            "prediction_cutoff_at": old["prediction_cutoff_at"],
            "violations": [],
            "features_checked": 1,
            "features_passed": 1,
            "features_failed": 0,
            "audited_at": old["created_at"],
        }
    )

    result = repo.prune_prediction_history(DEFAULT_PROMPT_CONTRACT.version)

    assert all(count == 0 for count in result["delete_counts"].values())
    assert result["protected_counts"]["predictions"] == 1
    assert result["protected_counts"]["prediction_revisions"] == 1
    assert result["protected_counts"]["feature_snapshots"] == 1
    assert result["retention_status"] == "audit_chain_protected"
    assert repo.prediction(old["id"]) == old
    assert repo.prediction_revision(old["id"], old_revision["revision_number"]) == old_revision
    assert repo.feature_snapshot(old["feature_snapshot_id"]) is not None
    assert repo.feature_snapshots(prediction_id=old["id"])[0]["snapshot_id"] == old["feature_snapshot_id"]
    assert repo.evidence_snapshot(old["evidence_snapshot_id"]) is not None
    assert repo.leakage_audit(audit["audit_id"]) == audit


def test_forged_pass_audit_cannot_admit_future_feature(tmp_path) -> None:
    repo = repository(tmp_path)
    prediction_id = "prediction-forged-pass"
    cutoff = "2026-09-15T03:00:00+00:00"
    evidence_snapshot_id = save_evidence(repo, prediction_id, cutoff)
    feature_snapshot_id = "features-forged-pass"
    repo.save_feature_snapshot(
        {
            "snapshot_id": feature_snapshot_id,
            "fixture_id": "fixture-round2",
            "evidence_snapshot_id": evidence_snapshot_id,
            "prediction_cutoff_at": cutoff,
            "computed_at": cutoff,
            "feature_version": FEATURE_VERSION,
            "leakage_detected": False,
            "features": [
                {
                    "feature_name": "future.result",
                    "feature_value": 3,
                    "source": "fixture_results",
                    "source_record_id": "future-match-1",
                    "computed_at": cutoff,
                    "available_at": "2026-09-15T04:00:00+00:00",
                    "prediction_cutoff_at": cutoff,
                    "feature_version": FEATURE_VERSION,
                    "snapshot_id": feature_snapshot_id,
                }
            ],
        }
    )
    item = prediction(
        prediction_id,
        cutoff,
        evidence_snapshot_id,
        feature_snapshot_id,
    )
    # Simulate an untrusted caller claiming that the future feature passed.
    repo.save_leakage_audit(
        {
            "audit_id": "audit-forged-pass",
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "status": "PASS",
            "prediction_cutoff_at": cutoff,
            "violations": [],
            "features_checked": 1,
            "features_passed": 1,
            "features_failed": 0,
            "audited_at": cutoff,
        }
    )

    with pytest.raises(ValueError, match="leakage re-audit"):
        repo.save_prediction_with_revision(item)

    assert repo.prediction(prediction_id) is None
    assert repo.prediction_revision(prediction_id) is None


def test_prediction_is_reproducible(tmp_path) -> None:
    repo = repository(tmp_path)
    repo.save_model_registry(
        {
            "model_key": "poisson",
            "model_version": MODEL_VERSION,
            "status": "champion",
            "competition_scope": "round2",
            "feature_version": FEATURE_VERSION,
            "dataset_fingerprint": "dataset-round2",
            "training_cutoff": "2026-09-14T00:00:00+00:00",
            "calibration_version": None,
            "artifact_hash": "a" * 64,
            "created_at": "2026-09-14T00:00:00+00:00",
        }
    )
    item, revision = save_complete_prediction(
        repo, "prediction-reproducible", "2026-09-15T03:00:00+00:00"
    )

    result = repo.reproduce_prediction(item["id"], revision["revision_number"])

    assert result["status"] == "PASS"
    assert result["reproducible"] is True
    assert result["missing_references"] == []
    assert result["artifact_status"] == "registered"
    assert result["identity"] == {
        "match_id": "fixture-round2",
        "prediction_id": "prediction-reproducible",
        "prediction_revision": 1,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_snapshot_id": item["feature_snapshot_id"],
        "evidence_snapshot_id": item["evidence_snapshot_id"],
    }
    assert result["feature_snapshot"]["features"][0]["available_at"] == item["prediction_cutoff_at"]
    assert result["model_artifact"]["artifact_hash"] == "a" * 64


def test_live_prediction_does_not_modify_pre_match(tmp_path) -> None:
    repo = repository(tmp_path)
    item, revision = save_complete_prediction(
        repo,
        "prediction-pre-match",
        "2026-09-15T03:00:00+00:00",
    )
    original = deepcopy(repo.prediction(item["id"]))
    live_prediction = deepcopy(item)
    live_prediction.update(
        {
            "id": "prediction-live",
            "phase": "live",
            "created_at": "2026-09-15T05:30:00+00:00",
            "prediction_cutoff_at": "2026-09-15T05:30:00+00:00",
            "probabilities": {"home": 0.7, "draw": 0.2, "away": 0.1},
        }
    )

    with pytest.raises(ValueError):
        repo.save_prediction_with_revision(live_prediction)

    with pytest.raises(ValueError, match="immutable"):
        repo.update_prediction(
            item["id"],
            {
                "phase": "live",
                "prediction_cutoff_at": "2026-09-15T05:30:00+00:00",
                "probabilities": {"home": 0.7, "draw": 0.2, "away": 0.1},
            },
        )

    assert repo.prediction("prediction-live") is None
    assert repo.prediction(item["id"]) == original
    assert repo.prediction_revision(item["id"], revision["revision_number"]) == revision
    assert repo.prediction_revisions(fixture_id=item["fixture_id"]) == [revision]
    assert repo.latest_current(
        item["fixture_id"],
        DEFAULT_PROMPT_CONTRACT.version,
        model_key="poisson",
        competition_id="round2",
    ) == original


def test_leakage_audit(tmp_path) -> None:
    repo = repository(tmp_path)
    item, _ = save_complete_prediction(
        repo,
        "prediction-audited",
        "2026-09-15T03:00:00+00:00",
    )

    result = LeakageAuditService(repo).audit_prediction(item["id"])

    assert result["status"] == "PASS"
    assert result["prediction_cutoff_at"] == item["prediction_cutoff_at"]
    assert result["violations"] == []
    assert result["features_checked"] == 1
    assert result["features_passed"] == 1
    assert result["features_failed"] == 0
    persisted = repo.leakage_audits(item["id"])
    assert len(persisted) == 2
    assert persisted[-1]["audit_id"] == result["audit_id"]
    assert persisted[-1]["status"] == "PASS"
    assert persisted[-1]["features_checked"] == 1


@pytest.mark.parametrize(
    ("invalid_kind", "invalid_captured_at", "expected_reason"),
    [
        ("evidence", "2026-09-15T04:00:00+00:00", "evidence_captured_after_prediction_cutoff"),
        ("odds", "2026-09-15T04:00:00+00:00", "odds_captured_after_prediction_cutoff"),
        ("evidence", None, "evidence_captured_at_missing"),
        ("odds", None, "odds_captured_at_missing"),
    ],
)
def test_leakage_audit_checks_referenced_snapshot_capture_boundary(
    invalid_kind: str,
    invalid_captured_at: str | None,
    expected_reason: str,
) -> None:
    cutoff = "2026-09-15T03:00:00+00:00"
    feature_snapshot = {
        "snapshot_id": "features-reference-audit",
        "fixture_id": "fixture-reference-audit",
        "prediction_cutoff_at": cutoff,
        "computed_at": cutoff,
        "feature_version": FEATURE_VERSION,
        "evidence_snapshot_id": "evidence-reference-audit",
        "odds_snapshot_id": "odds-reference-audit",
        "leakage_detected": False,
        "features": [
            {
                "feature_name": "reference.value",
                "feature_value": 1,
                "source": "test",
                "source_record_id": "reference-record",
                "computed_at": cutoff,
                "available_at": cutoff,
                "prediction_cutoff_at": cutoff,
                "feature_version": FEATURE_VERSION,
                "snapshot_id": "features-reference-audit",
                "status": "available",
            }
        ],
    }
    prediction = {
        "id": "prediction-reference-audit",
        "fixture_id": "fixture-reference-audit",
        "match_id": "fixture-reference-audit",
        "prediction_cutoff_at": cutoff,
        "feature_version": FEATURE_VERSION,
        "feature_snapshot_id": "features-reference-audit",
        "evidence_snapshot_id": "evidence-reference-audit",
        "odds_snapshot_id": "odds-reference-audit",
        "model_version": MODEL_VERSION,
        "model_key": "poisson",
        "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
    }
    revision = {
        "prediction_id": prediction["id"],
        "fixture_id": prediction["fixture_id"],
        "match_id": prediction["match_id"],
        "prediction_cutoff_at": cutoff,
        "feature_version": FEATURE_VERSION,
        "feature_snapshot_id": "features-reference-audit",
        "evidence_snapshot_id": "evidence-reference-audit",
        "model_version": MODEL_VERSION,
        "model_key": "poisson",
        "revision_number": 1,
        "probability_home": 0.5,
        "probability_draw": 0.25,
        "probability_away": 0.25,
    }

    class ReferenceRepository:
        def __init__(self) -> None:
            self.audit_rows: list[dict] = []
            self.evidence = {
                "id": "evidence-reference-audit",
                "fixture_id": "fixture-reference-audit",
                "created_at": cutoff,
                "captured_at": invalid_captured_at if invalid_kind == "evidence" else cutoff,
            }
            self.odds = {
                "id": "odds-reference-audit",
                "fixture_id": "fixture-reference-audit",
                "created_at": cutoff,
                "captured_at": invalid_captured_at if invalid_kind == "odds" else cutoff,
            }

        def prediction(self, _: str) -> dict:
            return prediction

        def feature_snapshot(self, _: str) -> dict:
            return feature_snapshot

        def prediction_revision(self, _: str) -> dict:
            return revision

        def evidence_snapshot(self, _: str) -> dict:
            return self.evidence

        def odds_snapshot(self, _: str) -> dict:
            return self.odds

        def save_leakage_audit(self, audit: dict) -> dict:
            self.audit_rows.append(audit)
            return audit

    repository = ReferenceRepository()
    result = LeakageAuditService(repository).audit_prediction(prediction["id"])

    assert result["status"] == "FAIL"
    assert any(
        violation["reason"] == expected_reason
        for violation in result["violations"]
    )


@pytest.mark.parametrize("mismatch_owner", ["prediction", "revision"])
def test_leakage_audit_rejects_prediction_fixture_link_mismatch(
    mismatch_owner: str,
) -> None:
    cutoff = "2026-09-15T03:00:00+00:00"
    snapshot = {
        "snapshot_id": "features-link-mismatch",
        "fixture_id": "fixture-a",
        "prediction_cutoff_at": cutoff,
        "feature_version": FEATURE_VERSION,
        "features": [
            {
                "feature_name": "link.value",
                "feature_value": 1,
                "source": "test",
                "source_record_id": "link-record",
                "computed_at": cutoff,
                "available_at": cutoff,
                "prediction_cutoff_at": cutoff,
                "feature_version": FEATURE_VERSION,
                "snapshot_id": "features-link-mismatch",
                "status": "available",
            }
        ],
    }

    class LinkRepository:
        def prediction(self, _: str) -> dict:
            return {
                "id": "prediction-link-mismatch",
                "fixture_id": "fixture-b" if mismatch_owner == "prediction" else "fixture-a",
                "prediction_cutoff_at": cutoff,
                "feature_version": FEATURE_VERSION,
                "feature_snapshot_id": "features-link-mismatch",
            }

        def feature_snapshot(self, _: str) -> dict:
            return snapshot

        def prediction_revision(self, _: str) -> dict:
            return {
                "prediction_id": "prediction-link-mismatch",
                "match_id": "fixture-b" if mismatch_owner == "revision" else "fixture-a",
                "prediction_cutoff_at": cutoff,
                "feature_version": FEATURE_VERSION,
                "feature_snapshot_id": "features-link-mismatch",
            }

        def save_leakage_audit(self, audit: dict) -> dict:
            return audit

    result = LeakageAuditService(LinkRepository()).audit_prediction("prediction-link-mismatch")

    assert result["status"] == "FAIL"
    assert any(
        violation["reason"] == f"{mismatch_owner}_fixture_id_mismatch"
        for violation in result["violations"]
    )


def test_leakage_audit_rejects_odds_snapshot_link_mismatch() -> None:
    cutoff = "2026-09-15T03:00:00+00:00"
    snapshot = {
        "snapshot_id": "features-odds-link",
        "fixture_id": "fixture-odds-link",
        "prediction_cutoff_at": cutoff,
        "feature_version": FEATURE_VERSION,
        "odds_snapshot_id": "odds-snapshot-a",
        "features": [
            {
                "feature_name": "odds.value",
                "feature_value": 2.1,
                "source": "test",
                "source_record_id": "odds-record",
                "computed_at": cutoff,
                "available_at": cutoff,
                "prediction_cutoff_at": cutoff,
                "feature_version": FEATURE_VERSION,
                "snapshot_id": "features-odds-link",
                "status": "available",
            }
        ],
    }

    class LinkRepository:
        def odds_snapshot(self, _: str) -> dict:
            return {
                "id": "odds-snapshot-a",
                "fixture_id": "fixture-odds-link",
                "captured_at": cutoff,
            }

    result = LeakageAuditService(LinkRepository()).audit_feature_snapshot(
        snapshot,
        persist=False,
        expected_prediction={
            "fixture_id": "fixture-odds-link",
            "prediction_cutoff_at": cutoff,
            "feature_version": FEATURE_VERSION,
            "feature_snapshot_id": "features-odds-link",
            "odds_snapshot_id": "odds-snapshot-b",
        },
    )

    assert result["status"] == "FAIL"
    assert any(
        violation["reason"] == "prediction_odds_snapshot_id_mismatch"
        for violation in result["violations"]
    )


def test_prediction_reproduction_does_not_require_registered_artifact(tmp_path) -> None:
    repo = repository(tmp_path)
    item, revision = save_complete_prediction(
        repo,
        "prediction-without-registry",
        "2026-09-15T03:00:00+00:00",
    )

    result = repo.reproduce_prediction(item["id"], revision["revision_number"])

    assert result["status"] == "PASS"
    assert result["reproducible"] is True
    assert result["model_artifact"] is None
    assert result["artifact_status"] == "not_registered"


def test_prediction_reproduction_locates_composite_poisson_artifact(tmp_path) -> None:
    repo = repository(tmp_path)
    fitted_version = "dc-fit-round2"
    composite_version = f"poisson-pure-v0.2+{fitted_version}"
    repo.save_model_registry(
        {
            "model_key": "dixon_coles",
            "model_version": fitted_version,
            "status": "champion",
            "competition_scope": "round2",
            "feature_version": None,
            "dataset_fingerprint": "dataset-round2",
            "training_cutoff": "2026-09-14T00:00:00+00:00",
            "calibration_version": None,
            "artifact_hash": "b" * 64,
            "created_at": "2026-09-14T00:00:00+00:00",
        }
    )
    evidence_snapshot_id = save_evidence(
        repo,
        "prediction-composite",
        "2026-09-15T03:00:00+00:00",
    )
    feature_snapshot_id = save_features(
        repo,
        "prediction-composite",
        evidence_snapshot_id,
        "2026-09-15T03:00:00+00:00",
    )
    item = prediction(
        "prediction-composite",
        "2026-09-15T03:00:00+00:00",
        evidence_snapshot_id,
        feature_snapshot_id,
    )
    item["model_version"] = composite_version
    audit = LeakageAuditService(repo).audit_feature_snapshot(
        repo.feature_snapshot(feature_snapshot_id),
        prediction_id=item["id"],
    )
    assert audit["status"] == "PASS"
    revision = repo.save_prediction_with_revision(item)

    result = repo.reproduce_prediction(item["id"], revision["revision_number"])

    assert result["status"] == "PASS"
    assert result["model_artifact"]["model_key"] == "dixon_coles"
    assert result["model_artifact"]["model_version"] == fitted_version
    assert result["model_artifact"]["artifact_hash"] == "b" * 64
