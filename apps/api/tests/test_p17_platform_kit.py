"""P17 platform kit: extension contracts and platform invariants tests."""

import pytest

from app.competition_registry import (
    COMPETITION_REGISTRY,
    CompetitionDefinition,
    CAPABILITIES,
)
from app.data_quality_engine import canonical_fixture_record
from app.historical_validation import build_historical_snapshot
from app.model_platform import PoissonModel
from app.platform_kit import (
    audit_point_in_time,
    audit_season_binding,
    season_scope,
    validate_competition_definition,
    validate_model_adapter,
    validate_provider_adapter,
)


def test_existing_six_competition_definitions_pass_the_kit() -> None:
    for definition in COMPETITION_REGISTRY.definitions():
        assert validate_competition_definition(definition) == []


def test_new_competition_extends_via_definition_without_duplicating_services() -> None:
    world_cup = CompetitionDefinition(
        key="world_cup",
        name="世界杯",
        mark="WC",
        competition_type="continental",
        season_policy="fall_spring",
        capabilities={capability: "unknown" for capability in CAPABILITIES} | {"fixture": "supported"},
        capability_notes={},
        provider_keys={"thesportsdb": "world_cup"},
    )

    assert validate_competition_definition(world_cup) == []
    # The canonical layer works for the new competition with zero new services.
    record = canonical_fixture_record(
        {
            "id": "sportsdb-wc-1",
            "source": "thesportsdb",
            "league_key": "world_cup",
            "kickoff": "2026-06-11T19:00:00+00:00",
            "home_team": {"name": "中国队"},
            "away_team": {"name": "巴西队"},
            "status": "scheduled",
            "captured_at": "2026-06-01T00:00:00+00:00",
        },
        world_cup,
        stage_name="小组赛",
    )
    assert record is not None
    assert record["competition_key"] == "world_cup"
    assert record["stage"]["stage_type"] == "group"

    broken = CompetitionDefinition(
        key="Bad Key",
        name="x",
        mark="X",
        competition_type="bogus",
        season_policy="unknown",
        capabilities={},
        capability_notes={},
        provider_keys={"": " "},
    )
    violations = validate_competition_definition(broken)
    assert violations


def test_provider_capability_contract_rejects_unimplemented_claims() -> None:
    class GoodProvider:
        configured = True
        SOURCE_NAME = "freescore"

        async def fixtures(self, start_date, end_date):
            return []

        async def standings(self):
            return []

    violations = validate_provider_adapter(
        GoodProvider(),
        name="freescore",
        declared_capabilities={"fixture": "supported", "standings": "supported", "odds": "unavailable"},
    )
    assert violations == []

    class OverclaimingProvider:
        configured = True
        SOURCE_NAME = "overclaim"

    violations = validate_provider_adapter(
        OverclaimingProvider(),
        name="overclaim",
        declared_capabilities={"fixture": "supported", "odds": "supported"},
    )
    assert any("fixture" in item for item in violations)
    assert any("odds" in item for item in violations)

    class NoProvenanceProvider:
        configured = True

        async def fixtures(self, start_date, end_date):
            return []

    assert validate_provider_adapter(
        NoProvenanceProvider(),
        name="noprovenance",
        declared_capabilities={"fixture": "supported"},
    )


def test_model_contract_requires_explicit_failure_and_provenance() -> None:
    assert validate_model_adapter(PoissonModel(), sample_context={"expected_goals": {"home": 1.4, "away": 1.1}}) == []

    class FabricatingModel:
        model_key = "fake"
        model_version = "fake-v1"

        def predict(self, context):
            from app.model_platform import ModelPrediction

            return ModelPrediction("fake", "fake-v1", {"home": 0.4, "draw": 0.3, "away": 0.3})

    violations = validate_model_adapter(FabricatingModel(), sample_context={"expected_goals": {"home": 1.4, "away": 1.1}})
    assert any("fabrication" in item for item in violations)
    assert any("provenance" in item for item in violations)


def test_point_in_time_audit_enforces_snapshot_invariants() -> None:
    from datetime import UTC, datetime, timedelta

    kickoff = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    as_of = kickoff - timedelta(hours=24)
    snapshot = build_historical_snapshot(
        {
            "id": "sportsdb-9001",
            "league_key": "epl",
            "kickoff": kickoff.isoformat(),
            "home_team": {"name": "武汉三镇"},
            "away_team": {"name": "上海海港"},
            "status": "scheduled",
        },
        as_of,
        evidence_snapshots=[],
        odds_snapshots=[],
    )

    assert audit_point_in_time([snapshot]) == []

    bad = [{"snapshot_id": "s1", "canonical_fixture_id": "fixture:x", "as_of": None, "created_at": None}]
    violations = audit_point_in_time(bad)
    assert any("as_of" in item for item in violations)

    inconsistent = [dict(snapshot, created_at="2020-01-01T00:00:00+00:00")]
    assert any("idempotent" in item for item in audit_point_in_time(inconsistent))


def test_season_binding_audit_and_season_scope() -> None:
    definition = COMPETITION_REGISTRY.get("epl")
    scope = season_scope(definition, "2026-03-01T00:00:00+00:00")
    assert scope == {"season_id": "2025", "scope": "season", "policy": "fall_spring", "competition_key": "epl"}

    unknown = season_scope(definition, "not-a-date")
    assert unknown["scope"] == "unknown" and unknown["season_id"] is None

    rows = [
        {"as_of": "2026-01-01T00:00:00+00:00", "payload": {"season": "2025"}},
        {"as_of": "2026-01-01T00:00:00+00:00", "payload": {"fixture": {}}},
    ]
    audit = audit_season_binding(rows)
    assert audit["season_bound"] == 1
    assert audit["global_scope"] == 1
    assert audit["unknown"] == 0
    assert "none are fabricated" in audit["note"]


def test_platform_invariants_are_importable_without_side_effects() -> None:
    # Importing the kit must not touch the database or network.
    from app.platform_kit import DOMAIN_MAP, PLATFORM_VERSION

    assert PLATFORM_VERSION == "p17-platform-v1"
    modules = {item["module"] for item in DOMAIN_MAP}
    assert "competition_registry" in modules and "observability" in modules
