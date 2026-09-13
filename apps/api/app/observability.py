"""P16 Observability: correlation, structured logs, SLOs, alerts.

Every request/job/run carries a correlation id; logs are structured JSON
with secrets redacted before emission. Metrics use bounded in-memory
buffers so observability overhead cannot grow with traffic. Alerts carry
an actionable component and a runbook reference, and they never modify
business decisions or models.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from .data_quality_engine import provider_reliability
from .historical_validation import parse_timestamp
from .research_engine import leakage_audit

OBSERVABILITY_VERSION = "p16-observability-v1"
_REDACTED_KEYS = frozenset(
    {"api_key", "apikey", "token", "access_token", "password", "authorization", "x-admin-key", "secret", "prompt", "messages", "system_message"}
)
# Secrets embedded inside free text ("api_key=sk-...", "Authorization: Bearer x")
# must never reach the logs either.
_SECRET_IN_TEXT = re.compile(
    r"(api[_-]?key|apikey|token|password|authorization|secret|x-admin-key)\s*[=:]\s*(\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)


def _scrub_text(text: str) -> str:
    return _SECRET_IN_TEXT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def redact(value: Any) -> Any:
    """Recursively remove secrets and prompt payloads from loggable data."""

    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, Mapping):
        return {
            key: ("[REDACTED]" if str(key).casefold() in _REDACTED_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


_logger = logging.getLogger("football-ai.observability")


def new_correlation_id(kind: str = "req") -> str:
    """Correlation id for requests, jobs and runs."""

    safe_kind = "".join(character for character in str(kind).casefold() if character.isalnum() or character in {"-", "_"})[:24] or "id"
    return f"{safe_kind}:{uuid.uuid4().hex[:16]}"


def emit_observability_log(
    event: str,
    *,
    correlation_id: str | None = None,
    component: str = "app",
    level: str = "info",
    code: str | None = None,
    reason: str | None = None,
    retryable: bool | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Emit one structured log line; secrets are redacted, never logged."""

    entry = {
        "ts": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "event": event,
        "correlation_id": correlation_id,
        "component": component,
        "level": level,
        "code": code,
        "reason": redact(reason),
        "retryable": retryable,
        "fields": redact(fields),
    }
    _logger.log(
        {"debug": 10, "info": 20, "warning": 30, "error": 40}.get(level, 20),
        json.dumps(entry, ensure_ascii=False, default=str),
    )
    return entry


class MetricsRegistry:
    """Bounded in-process request metrics (ring buffer, O(1) memory)."""

    def __init__(self, *, window_size: int = 500) -> None:
        self._latencies: deque[float] = deque(maxlen=max(10, int(window_size)))
        self._errors: deque[int] = deque(maxlen=max(10, int(window_size)))
        self._started_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    def record_request(self, duration_ms: float, status_code: int) -> None:
        self._latencies.append(float(duration_ms))
        self._errors.append(1 if status_code >= 500 else 0)

    def snapshot(self) -> dict[str, Any]:
        latencies = sorted(self._latencies)
        count = len(latencies)
        p95 = latencies[min(count - 1, int(count * 0.95))] if count else None
        errors = sum(self._errors)
        return {
            "window_size": count,
            "window_cap": self._latencies.maxlen,
            "p95_latency_ms": round(p95, 2) if p95 is not None else None,
            "error_rate": round(errors / count, 6) if count else None,
            "since": self._started_at,
        }


# SLOs are ranked by business importance; each has an owner component and
# a runbook so alerts are actionable.
SLO_CATALOG: tuple[dict[str, Any], ...] = (
    {"slo_id": "slo-api-availability", "tier": "tier1", "objective": "API availability", "target": ">= 99.5% monthly", "owner_component": "api", "runbook": "docs/RUNBOOKS.md#api-availability"},
    {"slo_id": "slo-api-p95-latency", "tier": "tier1", "objective": "API p95 latency", "target": "<= 1500 ms", "owner_component": "api", "runbook": "docs/RUNBOOKS.md#api-p95-latency"},
    {"slo_id": "slo-provider-freshness", "tier": "tier1", "objective": "Provider fixture freshness", "target": "<= 24 h for scheduled competitions", "owner_component": "sync", "runbook": "docs/RUNBOOKS.md#provider-freshness"},
    {"slo_id": "slo-job-completion", "tier": "tier2", "objective": "Scheduled job completion", "target": ">= 98% daily", "owner_component": "scheduler", "runbook": "docs/RUNBOOKS.md#scheduled-job-completion"},
    {"slo_id": "slo-prediction-success", "tier": "tier2", "objective": "Prediction success rate", "target": ">= 95% per model", "owner_component": "prediction", "runbook": "docs/RUNBOOKS.md#prediction-success-rate"},
    {"slo_id": "slo-leakage-response", "tier": "tier1", "objective": "Leakage incident response", "target": "freeze + audit within 24 h", "owner_component": "research", "runbook": "docs/RUNBOOKS.md#leakage-incident-response"},
)

ALERT_RULES: tuple[dict[str, Any], ...] = (
    {"alert_id": "alert-leakage", "severity": "critical", "condition": "leakage audit reports violations", "component": "research", "runbook": "docs/RUNBOOKS.md#leakage-incident-response"},
    {"alert_id": "alert-data-pollution", "severity": "critical", "condition": "open fixture conflicts exceed 20", "component": "data-quality", "runbook": "docs/RUNBOOKS.md#fixture-conflicts"},
    {"alert_id": "alert-db-loss", "severity": "critical", "condition": "database query fails in smoke checks", "component": "database", "runbook": "docs/RUNBOOKS.md#database-unavailable"},
    {"alert_id": "alert-provenance-missing", "severity": "critical", "condition": "prediction without evidence snapshot id", "component": "prediction", "runbook": "docs/RUNBOOKS.md#provenance-missing"},
    {"alert_id": "alert-provider-stale", "severity": "warning", "condition": "provider freshness older than 24 h", "component": "sync", "runbook": "docs/RUNBOOKS.md#provider-freshness"},
    {"alert_id": "alert-provider-low-coverage", "severity": "warning", "condition": "provider records_rejected above 50%", "component": "sync", "runbook": "docs/RUNBOOKS.md#provider-coverage"},
    {"alert_id": "alert-job-retry", "severity": "warning", "condition": "scheduled job failed in the last runs", "component": "scheduler", "runbook": "docs/RUNBOOKS.md#scheduled-job-completion"},
)

STALE_PROVIDER_HOURS = 24.0


def _job_observability(job_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for run in job_rows:
        name = str(run.get("job_name") or "unknown")
        item = jobs.setdefault(name, {"runs": 0, "failed": 0, "last_status": None, "last_error": None, "last_finished_at": None, "avg_duration_ms": None})
        item["runs"] += 1
        status = str(run.get("status") or "")
        if status in {"failed", "error"} or run.get("error_summary"):
            item["failed"] += 1
        if item["last_status"] is None:
            item["last_status"] = status or None
            item["last_error"] = run.get("error_summary")
        started = parse_timestamp(run.get("started_at"))
        finished = parse_timestamp(run.get("finished_at"))
        if started and finished:
            duration = (finished - started).total_seconds() * 1000
            item["avg_duration_ms"] = round(duration, 1) if item["avg_duration_ms"] is None else round((item["avg_duration_ms"] + duration) / 2, 1)
            if item["last_finished_at"] is None or finished.isoformat() > item["last_finished_at"]:
                item["last_finished_at"] = finished.isoformat()
    return jobs


def _model_observability(settlement_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for row in settlement_rows:
        key = str(row.get("model_key") or "unknown")
        item = models.setdefault(key, {"settled_predictions": 0, "last_settled_at": None})
        item["settled_predictions"] += 1
        settled_at = str(row.get("settled_at") or "")
        if settled_at and (item["last_settled_at"] is None or settled_at > item["last_settled_at"]):
            item["last_settled_at"] = settled_at
    return models


def observe_system_state(
    repository: Any,
    settings: Any,
    *,
    request_metrics: MetricsRegistry | None = None,
) -> dict[str, Any]:
    """Aggregate live observability state from persisted telemetry only.

    All reads are bounded; nothing here mutates business data.
    """

    job_rows = repository.job_runs(limit=100) if callable(getattr(repository, "job_runs", None)) else []
    sync_runs = repository.data_sync_runs(limit=300) if callable(getattr(repository, "data_sync_runs", None)) else []
    conflicts = repository.fixture_conflicts(limit=100) if callable(getattr(repository, "fixture_conflicts", None)) else []
    settlement_rows = (
        repository.fixture_settlements(competition_id=getattr(settings, "simulation_competition_id", None))
        if callable(getattr(repository, "fixture_settlements", None))
        else []
    )
    research_runs = repository.research_runs(limit=20) if callable(getattr(repository, "research_runs", None)) else []

    last_leakage = None
    for run in research_runs:
        audit = (run.get("leakage_audit") or {})
        if audit.get("status"):
            last_leakage = {"run_id": run.get("run_id"), **audit}
            break

    state = {
        "observability_version": OBSERVABILITY_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "environment": getattr(settings, "environment", "local"),
        "api": request_metrics.snapshot() if request_metrics else None,
        "jobs": _job_observability(job_rows),
        "providers": provider_reliability(sync_runs, fixture_conflicts=conflicts),
        "models": _model_observability(settlement_rows),
        "data_quality": {
            "open_fixture_conflicts": sum(1 for row in conflicts if not row.get("resolved")),
            "total_fixture_conflicts": len(conflicts),
        },
        "leakage": {
            "live_audit": leakage_audit(settlement_rows),
            "last_research_audit": last_leakage,
        },
    }
    return state


def evaluate_alerts(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Evaluate alert rules against the observed state (read-only)."""

    triggered: list[dict[str, Any]] = []
    live_audit = ((state.get("leakage") or {}).get("live_audit")) or {}
    if live_audit.get("status") == "failed":
        rule = next(rule for rule in ALERT_RULES if rule["alert_id"] == "alert-leakage")
        triggered.append({**rule, "evidence": {"violations": live_audit.get("violation_count")}})

    open_conflicts = ((state.get("data_quality") or {}).get("open_fixture_conflicts") or 0)
    if open_conflicts > 20:
        rule = next(rule for rule in ALERT_RULES if rule["alert_id"] == "alert-data-pollution")
        triggered.append({**rule, "evidence": {"open_fixture_conflicts": open_conflicts}})

    for provider in state.get("providers") or []:
        finished = parse_timestamp(provider.get("freshness"))
        age_hours = ((datetime.now(UTC) - finished).total_seconds() / 3600) if finished else None
        if age_hours is None or age_hours > STALE_PROVIDER_HOURS:
            rule = next(rule for rule in ALERT_RULES if rule["alert_id"] == "alert-provider-stale")
            triggered.append(
                {
                    **rule,
                    "evidence": {
                        "provider": provider.get("provider"),
                        "competition": provider.get("competition"),
                        "freshness": provider.get("freshness"),
                        "age_hours": round(age_hours, 1) if age_hours is not None else None,
                    },
                }
            )
        if provider.get("records_seen") and provider.get("records_rejected", 0) / provider["records_seen"] > 0.5:
            rule = next(rule for rule in ALERT_RULES if rule["alert_id"] == "alert-provider-low-coverage")
            triggered.append({**rule, "evidence": {key: provider.get(key) for key in ("provider", "competition", "records_seen", "records_rejected")}})

    for name, job in (state.get("jobs") or {}).items():
        if job.get("failed"):
            rule = next(rule for rule in ALERT_RULES if rule["alert_id"] == "alert-job-retry")
            triggered.append({**rule, "evidence": {"job": name, "failed_runs": job.get("failed"), "last_error": job.get("last_error")}})
    return triggered
