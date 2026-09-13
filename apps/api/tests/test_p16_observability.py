"""P16 observability: redaction, correlation, bounded metrics, alerts tests."""

import json
import logging

import pytest

from app.database import PredictionRepository
from app.observability import (
    ALERT_RULES,
    SLO_CATALOG,
    MetricsRegistry,
    emit_observability_log,
    evaluate_alerts,
    new_correlation_id,
    observe_system_state,
    redact,
)


def settlement_rows(count: int = 60, *, leaky: bool = False) -> list[dict]:
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(count):
        created = start + timedelta(hours=index * 6)
        rows.append(
            {
                "fixture_id": f"f{index}",
                "prediction_id": f"p{index}",
                "league_key": "epl",
                "model_key": "deepseek",
                "prediction_created_at": created.isoformat(),
                "settled_at": (created + timedelta(minutes=-1 if leaky else 60)).isoformat(),
            }
        )
    return rows


def test_redact_removes_secrets_and_prompt_payloads() -> None:
    payload = {
        "api_key": "sk-secret",
        "nested": {"x-admin-key": "dev-admin-key", "token": "t", "safe": 1},
        "messages": [{"role": "system", "content": "prompt text"}],
        "list": [{"password": "p"}],
        "plain": "value",
    }
    redacted = redact(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["x-admin-key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == 1
    assert redacted["messages"] == "[REDACTED]"
    assert redacted["list"] == [{"password": "[REDACTED]"}]
    assert redacted["plain"] == "value"


def test_structured_log_contains_code_reason_and_no_secrets(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="football-ai.observability"):
        entry = emit_observability_log(
            "job_failed",
            correlation_id="job:abc",
            component="scheduler",
            level="error",
            code="provider_timeout",
            reason="API_KEY=sk-secret timed out",
            retryable=True,
            config={"api_key": "sk-secret"},
        )

    assert entry["code"] == "provider_timeout"
    assert entry["retryable"] is True
    assert entry["fields"]["config"]["api_key"] == "[REDACTED]"
    line = json.loads(caplog.records[-1].message)
    assert line["correlation_id"] == "job:abc"
    assert "sk-secret" not in caplog.records[-1].message


def test_correlation_ids_are_prefixed_and_unique() -> None:
    first = new_correlation_id("req")
    second = new_correlation_id("job")
    assert first.startswith("req:") and second.startswith("job:")
    assert first != second
    assert new_correlation_id("bad kind!")  # sanitized prefix must not crash


def test_metrics_registry_is_bounded_and_reports_p95() -> None:
    registry = MetricsRegistry(window_size=100)
    for index in range(1000):
        registry.record_request(100.0 + index % 10, 500 if index % 50 == 0 else 200)

    snapshot = registry.snapshot()

    assert snapshot["window_size"] == 100  # bounded, not 1000
    assert snapshot["window_cap"] == 100
    assert snapshot["p95_latency_ms"] is not None
    assert 0 < snapshot["error_rate"] < 0.1


def test_system_state_observes_jobs_providers_models_and_leakage(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p16.db"))
    repository.initialize()

    class Settings:
        environment = "local"
        simulation_competition_id = "dual-model-v1"

    state = observe_system_state(repository, Settings())

    assert state["environment"] == "local"
    assert state["jobs"] == {}
    assert state["models"] == {}
    assert state["leakage"]["live_audit"]["status"] == "not_applicable"
    assert state["data_quality"]["open_fixture_conflicts"] == 0


def test_leakage_violations_trigger_critical_alert() -> None:
    repository_rows = settlement_rows(60, leaky=True)

    class Settings:
        environment = "local"
        simulation_competition_id = "dual-model-v1"

    class Repo:
        def job_runs(self, job_name=None, limit=50):
            return []

        def data_sync_runs(self, limit=300):
            return []

        def fixture_conflicts(self, limit=100):
            return []

        def fixture_settlements(self, **kwargs):
            return repository_rows

        def research_runs(self, limit=20):
            return []

    state = observe_system_state(Repo(), Settings())
    alerts = evaluate_alerts(state)

    assert state["leakage"]["live_audit"]["status"] == "failed"
    assert any(alert["alert_id"] == "alert-leakage" for alert in alerts)
    critical = [alert for alert in alerts if alert["severity"] == "critical"]
    assert critical and all(alert["runbook"].startswith("docs/RUNBOOKS.md") for alert in critical)


def test_provider_staleness_and_job_failures_raise_warnings() -> None:
    state = {
        "leakage": {"live_audit": {"status": "passed"}},
        "data_quality": {"open_fixture_conflicts": 0},
        "providers": [
            {"provider": "thesportsdb", "competition": "epl", "records_seen": 10, "records_rejected": 6, "freshness": "2020-01-01T00:00:00+00:00"}
        ],
        "jobs": {"settlement": {"runs": 4, "failed": 2, "last_status": "failed", "last_error": "boom"}},
    }

    alerts = evaluate_alerts(state)

    alert_ids = {alert["alert_id"] for alert in alerts}
    assert {"alert-provider-stale", "alert-provider-low-coverage", "alert-job-retry"} <= alert_ids
    assert not any(alert["severity"] == "critical" for alert in alerts)


def test_slo_catalog_and_alert_rules_have_runbooks() -> None:
    assert {slo["tier"] for slo in SLO_CATALOG} == {"tier1", "tier2"}
    assert all(slo["runbook"].startswith("docs/RUNBOOKS.md") for slo in SLO_CATALOG)
    assert all(rule["runbook"].startswith("docs/RUNBOOKS.md") and rule["component"] for rule in ALERT_RULES)
    severities = {rule["severity"] for rule in ALERT_RULES}
    assert severities == {"critical", "warning"}
