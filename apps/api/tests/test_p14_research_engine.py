"""P14 automated research: pipeline, statistical discipline, idempotency tests."""

import asyncio

import pytest

from app.database import PredictionRepository
from app.research_engine import (
    ResearchScheduler,
    leakage_audit,
    run_research,
    sample_size_status,
    validate_hypothesis,
)


def settlement_rows(count: int = 300, *, seed: int = 11, predict_after_settle: bool = False) -> list[dict]:
    import random
    from datetime import UTC, datetime, timedelta

    rng = random.Random(seed)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(count):
        actual = rng.choice(["home", "draw", "away"])
        created = start + timedelta(hours=index * 6)
        settled = created + timedelta(minutes=-1) if predict_after_settle else created + timedelta(hours=30)
        rows.append(
            {
                "fixture_id": f"f{index}",
                "prediction_id": f"p{index}",
                "league_key": "epl",
                "prediction_created_at": created.isoformat(),
                "settled_at": settled.isoformat(),
                "model_key": "deepseek",
                "model_version": "deepseek:deepseek-v4-flash",
                "actual_outcome": actual,
                "model_probabilities": {key: 0.55 if key == actual else 0.225 for key in ("home", "draw", "away")},
            }
        )
    return rows


HYPOTHESIS = {"statement": "ensemble 在 epl 测试窗的 Brier 优于 naive baseline", "kind": "confirmatory", "selection_rule": "ensemble_brier 低者胜"}


def test_hypothesis_validation_requires_selection_rule_for_confirmatory() -> None:
    validated = validate_hypothesis(statement="测试一个假设陈述", kind="exploratory")
    assert validated["kind"] == "exploratory"
    assert validated["hypothesis_id"].startswith("hyp:")

    with pytest.raises(ValueError):
        validate_hypothesis(statement="确认性假设需要预注册选择规则", kind="confirmatory")
    with pytest.raises(ValueError):
        validate_hypothesis(statement="短", kind="exploratory")
    with pytest.raises(ValueError):
        validate_hypothesis(statement="测试一个假设陈述", kind="bogus")


def test_sample_size_status_follows_p6_policy() -> None:
    assert sample_size_status(10) == "insufficient_sample"
    assert sample_size_status(30) == "low_confidence"
    assert sample_size_status(99) == "low_confidence"
    assert sample_size_status(100) == "adequate_sample"


def test_leakage_audit_flags_label_after_prediction() -> None:
    clean = leakage_audit(settlement_rows(50))
    assert clean["passed"] is True
    assert clean["status"] == "passed"

    leaky = leakage_audit(settlement_rows(50, predict_after_settle=True))
    assert leaky["passed"] is False
    assert leaky["status"] == "failed"
    assert leaky["violation_count"] == 50

    assert leakage_audit([])["status"] == "not_applicable"


def test_research_run_completes_with_report_and_frozen_versions() -> None:
    run = run_research(settlement_rows(300), hypothesis=HYPOTHESIS, mode="rolling", train_days=45, test_days=15, step_days=15)

    assert run["status"] == "completed"
    assert run["run_id"].startswith("research:")
    assert run["manifest"]["dataset_fingerprint"]
    assert run["manifest"]["feature_version"] and run["manifest"]["calibration_version"]
    assert run["exploratory"] is False
    assert run["selection_rule"] == "ensemble_brier 低者胜"
    report = run["report"]
    for section in ("dataset", "versions", "method", "metrics", "uncertainty", "limitations", "leakage_audit", "conclusion", "unanswerable"):
        assert section in report
    assert report["uncertainty"]["sample_status"] in {"low_confidence", "adequate_sample"}
    assert report["conclusion"]
    assert run["leakage_audit"]["status"] == "passed"
    assert run["leakage_audit"]["violation_count"] == 0


def test_leakage_violations_fail_the_run_without_conclusion() -> None:
    run = run_research(settlement_rows(300, predict_after_settle=True), hypothesis=HYPOTHESIS, mode="rolling", train_days=45, test_days=15, step_days=15)

    assert run["status"] == "failed"
    assert run["report"]["conclusion"] is None
    assert run["stages"]["leakage_audit"]["status"] == "failed"


def test_research_run_is_reproducible_and_immutably_stored(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p14.db"))
    repository.initialize()
    rows = settlement_rows(300)

    first = run_research(rows, hypothesis=HYPOTHESIS, mode="rolling", train_days=45, test_days=15, step_days=15, repository=repository)
    second = run_research(rows, hypothesis=HYPOTHESIS, mode="rolling", train_days=45, test_days=15, step_days=15, repository=repository)

    assert first["run_id"] == second["run_id"]
    assert len(repository.research_runs()) == 1
    stored = repository.research_run(first["run_id"])
    assert stored["report"]["dataset"]["fingerprint"] == first["manifest"]["dataset_fingerprint"]

    # A different hypothesis creates a different run, never mutates the old one.
    other = run_research(rows, hypothesis={**HYPOTHESIS, "statement": "另一个预注册的假设陈述内容"}, mode="rolling", train_days=45, test_days=15, step_days=15, repository=repository)
    assert other["run_id"] != first["run_id"]
    assert repository.research_run(first["run_id"])["status"] == "completed"


def test_insufficient_dataset_fails_without_success_conclusion() -> None:
    run = run_research(settlement_rows(10), hypothesis={**HYPOTHESIS, "statement": "样本不足时的假设陈述"}, mode="rolling", train_days=45, test_days=15, step_days=15)

    assert run["status"] in {"failed", "partial"}
    assert not (run.get("report") or {}).get("conclusion")


def test_scheduler_submit_is_locked_and_idempotent(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p14.db"))
    repository.initialize()
    scheduler = ResearchScheduler(repository)
    calls = {"count": 0}

    def provider() -> list[dict]:
        calls["count"] += 1
        return settlement_rows(300)

    async def scenario() -> list[dict]:
        results = await asyncio.gather(
            *(
                scheduler.submit(
                    job_id="research-job-1",
                    settlement_provider=provider,
                    hypothesis=HYPOTHESIS,
                    mode="rolling",
                    train_days=45,
                    test_days=15,
                    step_days=15,
                )
                for _ in range(3)
            )
        )
        return results

    results = asyncio.run(scenario())

    assert calls["count"] == 1  # lock serializes; idempotency cache avoids recompute
    assert all(result["run"]["run_id"] == results[0]["run"]["run_id"] for result in results)
    assert len(repository.research_runs()) == 1

    retry = asyncio.run(
        scheduler.submit(
            job_id="research-job-1",
            settlement_provider=provider,
            hypothesis=HYPOTHESIS,
            mode="rolling",
            train_days=45,
            test_days=15,
            step_days=15,
        )
    )
    assert retry["reused"] is True
    assert calls["count"] == 1
