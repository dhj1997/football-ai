"""P9 competition registry and capability gate tests."""

from datetime import date

import pytest

from app.competition_registry import (
    COMPETITION_REGISTRY,
    CAPABILITIES,
    CapabilityGateError,
    CompetitionRegistry,
    CompetitionDefinition,
    normalize_competition_key,
    season_for,
)
from app.database import PredictionRepository


def test_registry_contains_six_competitions_with_domain_types() -> None:
    definitions = COMPETITION_REGISTRY.definitions()

    assert [item.key for item in definitions] == ["csl", "epl", "laliga", "cfa_cup", "ucl", "acl"]
    assert [item.competition_type for item in definitions] == [
        "league",
        "league",
        "league",
        "knockout",
        "continental",
        "continental",
    ]


def test_every_definition_declares_all_capabilities_with_valid_status() -> None:
    for definition in COMPETITION_REGISTRY.definitions():
        assert set(definition.capabilities) == set(CAPABILITIES)
        assert all(status in {"supported", "partial", "unavailable", "unknown"} for status in definition.capabilities.values())


def test_capability_matrix_reflects_real_support() -> None:
    assert COMPETITION_REGISTRY.capability_status("csl", "standings") == "supported"
    assert COMPETITION_REGISTRY.capability_status("csl", "historical") == "supported"
    assert COMPETITION_REGISTRY.capability_status("csl", "prediction") == "supported"
    # Cup and continental competitions are fixture-only today.
    assert COMPETITION_REGISTRY.capability_status("cfa_cup", "standings") == "unavailable"
    assert COMPETITION_REGISTRY.capability_status("ucl", "historical") == "unavailable"
    assert COMPETITION_REGISTRY.capability_status("acl", "prediction") == "unavailable"
    assert COMPETITION_REGISTRY.capability_status("ucl", "fixture") == "supported"


def test_unknown_capability_is_never_treated_as_supported() -> None:
    definition = COMPETITION_REGISTRY.get("csl")
    assert definition.capability_status("nonexistent") == "unknown"
    with pytest.raises(CapabilityGateError):
        COMPETITION_REGISTRY.require("csl", "nonexistent")


def test_require_gates_unsupported_capability() -> None:
    assert COMPETITION_REGISTRY.require("csl", "standings").key == "csl"
    with pytest.raises(CapabilityGateError):
        COMPETITION_REGISTRY.require("cfa_cup", "standings")
    with pytest.raises(CapabilityGateError):
        COMPETITION_REGISTRY.require("ucl", "historical")
    with pytest.raises(CapabilityGateError):
        COMPETITION_REGISTRY.require("bogus", "fixture")


def test_competitions_with_capability_lists_only_supported_standings() -> None:
    assert [item.key for item in COMPETITION_REGISTRY.competitions_with_capability("standings")] == ["csl", "epl", "laliga"]


def test_normalize_competition_key_unifies_all_vocabularies() -> None:
    assert normalize_competition_key("CSL") == "csl"
    assert normalize_competition_key("LAL") == "laliga"
    assert normalize_competition_key("laliga") == "laliga"
    assert normalize_competition_key("中超") == "csl"
    assert normalize_competition_key("英超") == "epl"
    assert normalize_competition_key("西甲") == "laliga"
    assert normalize_competition_key("中国足协杯") == "cfa_cup"
    assert normalize_competition_key("欧冠") == "ucl"
    assert normalize_competition_key("亚冠") == "acl"
    assert normalize_competition_key("亚冠二级联赛") == "acl"
    assert normalize_competition_key("") is None
    assert normalize_competition_key("bogus") is None


def test_season_policy_matches_provider_convention() -> None:
    assert season_for("csl", date(2026, 3, 1)) == 2026
    assert season_for("cfa_cup", date(2026, 11, 5)) == 2026
    assert season_for("epl", date(2026, 3, 1)) == 2025
    assert season_for("epl", date(2026, 8, 1)) == 2026
    assert season_for("ucl", date(2026, 3, 1)) == 2025


def test_registry_persistence_roundtrip(tmp_path) -> None:
    repository = PredictionRepository(str(tmp_path / "p9.db"))
    repository.initialize()

    repository.save_competition_registry(COMPETITION_REGISTRY.as_dict())
    rows = repository.competition_registry()

    assert [row["key"] for row in rows] == ["acl", "cfa_cup", "csl", "epl", "laliga", "ucl"]
    assert rows[2]["capabilities"]["standings"] == "supported"


def test_custom_registry_isolates_definitions() -> None:
    definition = CompetitionDefinition(
        key="test",
        name="测试",
        mark="T",
        competition_type="league",
        season_policy="calendar_year",
        capabilities={capability: "unknown" for capability in CAPABILITIES},
        capability_notes={},
        provider_keys={},
    )
    registry = CompetitionRegistry((definition,))

    assert registry.get("test").key == "test"
    with pytest.raises(CapabilityGateError):
        registry.require("test", "fixture")
