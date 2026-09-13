"""P17 Platform kit: extension contracts for competitions, providers, models.

The kit makes platform extension mechanical: a new competition is a
registry definition plus a provider plus these checks; a new provider
implements the capability contract; a new model implements the unified
prediction contract. Nothing here duplicates domain services, and every
check enforces the platform-wide provenance and point-in-time invariants.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .competition_registry import (
    CAPABILITIES,
    CAPABILITY_STATUSES,
    COMPETITION_TYPES,
    CompetitionDefinition,
    SEASON_POLICIES,
    season_for,
)
from .historical_validation import parse_timestamp

PLATFORM_VERSION = "p17-platform-v1"

# Ownership and boundaries of the core domain modules (platform navigation).
DOMAIN_MAP: tuple[dict[str, Any], ...] = (
    {"module": "competition_registry", "owner": "competition domain", "contract": "CompetitionDefinition + capability matrix", "since": "P9"},
    {"module": "data_quality_engine", "owner": "data platform", "contract": "canonical fixture/stage + quality rules", "since": "P9"},
    {"module": "provider adapters", "owner": "data platform", "contract": "capability declaration + raw provenance (source/captured_at)", "since": "P0/P9"},
    {"module": "model_platform", "owner": "model domain", "contract": "ModelPrediction unified interface (explicit readiness/failure)", "since": "P10"},
    {"module": "model_registry", "owner": "model domain", "contract": "versioned artifacts + promotion gates", "since": "P10"},
    {"module": "market_intelligence", "owner": "market domain", "contract": "odds timeline/consensus/CLV research signals", "since": "P11"},
    {"module": "settlement/portfolio", "owner": "decision domain", "contract": "P0/P2 prediction/decision separation", "since": "P0/P2"},
    {"module": "backtest_engine", "owner": "evaluation domain", "contract": "train-only weights + manifest reproducibility", "since": "P12"},
    {"module": "explainability", "owner": "explanation domain", "contract": "grounded explanation graph (read-only)", "since": "P13"},
    {"module": "research_engine", "owner": "research domain", "contract": "hypothesis pipeline + mandatory leakage audit", "since": "P14"},
    {"module": "production", "owner": "operations domain", "contract": "environment contract + versioned migrations + verified backups", "since": "P15"},
    {"module": "observability", "owner": "operations domain", "contract": "correlation ids + redacted logs + SLO/alert runbooks", "since": "P16"},
)

PRODUCT_SURFACES: tuple[str, ...] = (
    "Competition Center (/api/competitions)",
    "Match Center (/api/fixtures)",
    "Team Center (/api/teams/{league_key}/{team_id})",
    "Model Lab (/api/models)",
    "Backtest Lab (/api/backtest/runs)",
    "Explainability (/api/fixtures/{id}/explanation)",
    "Market Intelligence (/api/fixtures/{id}/market)",
    "Research Engine (/api/research/runs)",
    "Data Platform (/api/data-sources, /api/data-quality)",
    "Operations (/api/production/readiness, /api/admin/observability)",
)


def validate_competition_definition(definition: Any) -> list[str]:
    """Schema conformance for any new CompetitionDefinition."""

    violations: list[str] = []
    if not isinstance(definition, CompetitionDefinition):
        return ["extension must use CompetitionDefinition, not a bespoke league object"]
    if not definition.key or definition.key != definition.key.strip().casefold():
        violations.append("competition key must be a normalized lowercase token")
    if definition.competition_type not in COMPETITION_TYPES:
        violations.append(f"invalid competition_type: {definition.competition_type}")
    if definition.season_policy not in SEASON_POLICIES:
        violations.append(f"invalid season_policy: {definition.season_policy}")
    if set(definition.capabilities) != set(CAPABILITIES):
        violations.append("every platform capability must be declared explicitly")
    for capability, status in definition.capabilities.items():
        if status not in CAPABILITY_STATUSES:
            violations.append(f"capability {capability} has invalid status {status}")
    for provider, key in definition.provider_keys.items():
        if key is not None and not str(key).strip():
            violations.append(f"provider {provider} key must be a token or None")
    return violations


def validate_provider_adapter(
    provider: Any,
    *,
    name: str,
    declared_capabilities: Mapping[str, str],
    competition_keys: Iterable[str] = (),
) -> list[str]:
    """Capability contract for a new provider adapter (static, no network).

    Declares only what is implemented: a ``supported`` capability must map
    to a callable adapter method, and fixture-producing methods must stamp
    provenance fields on their outputs.
    """

    violations: list[str] = []
    if not name:
        violations.append("provider name is required")
    configured = getattr(provider, "configured", None)
    if configured is None:
        violations.append("provider must expose a `configured` property")
    method_for_capability = {
        "fixture": ("fixtures", "historical_fixtures"),
        "standings": ("standings",),
        "historical": ("historical_fixtures", "historical_results"),
        "odds": ("odds", "historical_odds"),
        "lineup": ("fetch_lineup",),
        "injury": ("fetch",),
        "team": ("team",),
        "stage": ("fixtures", "historical_fixtures"),
        "prediction": (),
        "evaluation": (),
    }
    supported = [capability for capability, status in declared_capabilities.items() if status == "supported"]
    unknown = [capability for capability in declared_capabilities if capability not in CAPABILITIES]
    if unknown:
        violations.append(f"unknown capabilities declared: {unknown}")
    for capability in supported:
        method_names = method_for_capability.get(capability, ())
        if not any(callable(getattr(provider, method_name, None)) for method_name in method_names):
            violations.append(
                f"capability '{capability}' declared supported but none of {method_names} is implemented"
            )
    if "fixture" in supported:
        # Provenance shape: the mapper must emit source + captured_at.
        source = getattr(provider, "SOURCE_NAME", None)
        if not source:
            violations.append("fixture providers must declare SOURCE_NAME for provenance")
    for key in competition_keys:
        if not str(key).strip():
            violations.append("provider competition keys must be non-empty")
    return violations


def validate_model_adapter(model: Any, *, sample_context: Mapping[str, Any]) -> list[str]:
    """Unified model contract: explicit failure, valid probabilities, provenance.

    A model that answers ``ok`` on an empty context is fabricating — the
    contract requires ``insufficient_evidence`` or ``failed`` instead.
    """

    violations: list[str] = []
    if not getattr(model, "model_key", None) or not getattr(model, "model_version", None):
        violations.append("model must declare model_key and model_version")
    if not callable(getattr(model, "predict", None)):
        violations.append("model must implement predict(context)")
        return violations
    empty = model.predict({})
    if empty.ok:
        violations.append("model must not return probabilities without any context (fabrication)")
    if empty.readiness not in {"ready", "insufficient_evidence", "failed"}:
        violations.append(f"unknown readiness state: {empty.readiness}")
    result = model.predict(dict(sample_context))
    if result.ok:
        probabilities = dict(result.probabilities or {})
        if set(probabilities) != {"home", "draw", "away"}:
            violations.append("probabilities must cover home/draw/away")
        elif abs(sum(probabilities.values()) - 1.0) > 1e-3:
            violations.append("probabilities must sum to 1")
        if not result.provenance:
            violations.append("ready predictions must carry provenance")
    elif result.readiness == "ready":
        violations.append("ready state without probabilities")
    return violations


def audit_point_in_time(snapshot_rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Point-in-time invariants for historical snapshot rows."""

    violations: list[str] = []
    for row in snapshot_rows:
        row_id = str(row.get("snapshot_id") or row.get("fixture_id") or "?")
        if not row.get("as_of"):
            violations.append(f"{row_id}: missing as_of cutoff")
        if not row.get("canonical_fixture_id"):
            violations.append(f"{row_id}: missing canonical fixture identity")
        as_of = parse_timestamp(row.get("as_of"))
        created = parse_timestamp(row.get("created_at"))
        if as_of and created and created != as_of:
            violations.append(f"{row_id}: created_at differs from as_of (rebuilds must be idempotent)")
    return violations


def audit_season_binding(snapshot_rows: Iterable[Mapping[str, Any]], *, season_policy: str = "calendar_year") -> dict[str, Any]:
    """Season must be bound explicitly, or the row is global-scope by design."""

    bound = 0
    global_scope = 0
    unknown = 0
    for row in snapshot_rows:
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else row
        fixture = payload.get("fixture") if isinstance(payload, Mapping) else None
        season = (payload.get("season") if isinstance(payload, Mapping) else None) or ((fixture or {}).get("season") if isinstance(fixture, Mapping) else None)
        if season:
            bound += 1
        elif row.get("as_of"):
            global_scope += 1
        else:
            unknown += 1
    return {
        "season_bound": bound,
        "global_scope": global_scope,
        "unknown": unknown,
        "policy": season_policy,
        "note": "historical rows without a season stay explicitly global-scope; none are fabricated",
    }


def season_scope(definition: CompetitionDefinition, on_date: Any) -> dict[str, Any]:
    """First-class season binding for a competition and a point in time."""

    if isinstance(on_date, str):
        parsed = parse_timestamp(on_date)
        day = parsed.date() if parsed else None
    elif hasattr(on_date, "hour"):
        day = on_date.date()
    elif hasattr(on_date, "year"):
        day = on_date
    else:
        day = None
    if day is None:
        return {"season_id": None, "scope": "unknown", "policy": definition.season_policy, "competition_key": definition.key}
    return {
        "season_id": str(season_for(definition.key, day)),
        "scope": "season",
        "policy": definition.season_policy,
        "competition_key": definition.key,
    }
