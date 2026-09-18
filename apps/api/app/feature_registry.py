"""Versioned, explainable Feature Engine v2 definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


FEATURE_GROUPS = frozenset(
    {"elo", "strength", "attack", "defense", "xg", "form", "home_away", "fatigue", "player", "market"}
)
ENTITY_TYPES = frozenset({"team", "player", "match", "competition"})
FEATURE_STATUSES = frozenset({"active", "deprecated"})
REGISTRY_CREATED_AT = "2026-09-16T00:00:00+00:00"


class FeatureRegistryError(ValueError):
    """Raised when a feature definition violates the public registry contract."""


@dataclass(frozen=True)
class FeatureDefinition:
    feature_name: str
    feature_group: str
    entity_type: str
    description: str
    formula: str
    source: str
    calculation_version: str
    value_type: str = "number"
    required: bool = False
    freshness_ttl_hours: float = 720.0
    source_reliability: float = 1.0
    status: str = "active"
    created_at: str = REGISTRY_CREATED_AT
    deprecated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.feature_name or not self.calculation_version:
            raise FeatureRegistryError("feature_name and calculation_version are required")
        if self.feature_group not in FEATURE_GROUPS:
            raise FeatureRegistryError(f"Unsupported feature_group: {self.feature_group}")
        if self.entity_type not in ENTITY_TYPES:
            raise FeatureRegistryError(f"Unsupported entity_type: {self.entity_type}")
        if self.status not in FEATURE_STATUSES:
            raise FeatureRegistryError(f"Unsupported feature status: {self.status}")
        if self.freshness_ttl_hours <= 0:
            raise FeatureRegistryError("freshness_ttl_hours must be positive")
        if not 0 <= self.source_reliability <= 1:
            raise FeatureRegistryError("source_reliability must be between 0 and 1")

    @property
    def id(self) -> str:
        return f"feature:{self.feature_name}:{self.calculation_version}"

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        metadata = values.pop("metadata")
        return {
            "id": self.id,
            **values,
            "payload": {
                "value_type": self.value_type,
                "required": self.required,
                "freshness_ttl_hours": self.freshness_ttl_hours,
                "source_reliability": self.source_reliability,
                **metadata,
            },
        }


def _definition(
    name: str,
    group: str,
    description: str,
    formula: str,
    source: str,
    version: str,
    *,
    value_type: str = "number",
    ttl: float = 720.0,
) -> FeatureDefinition:
    return FeatureDefinition(
        feature_name=name,
        feature_group=group,
        entity_type="team",
        description=description,
        formula=formula,
        source=source,
        calculation_version=version,
        value_type=value_type,
        freshness_ttl_hours=ttl,
    )


def builtin_feature_definitions() -> tuple[FeatureDefinition, ...]:
    """Return the deterministic Round 3 registry seed."""

    definitions = [
        _definition("team_elo", "elo", "Competition-scoped overall team Elo", "Standard Elo; initial=1500, K=20, home advantage=60", "completed_match_results", "elo-feature-v1"),
        _definition("home_elo", "elo", "Team Elo in the home context", "Contextual Elo updated when the team plays at home", "completed_match_results", "elo-feature-v1"),
        _definition("away_elo", "elo", "Team Elo in the away context", "Contextual Elo updated when the team plays away", "completed_match_results", "elo-feature-v1"),
        _definition("attack_strength", "attack", "Opponent-adjusted attack index; larger is stronger", "team primary-for rate / competition primary-for rate * opponent Elo factor", "real_xg_or_goals_or_shots", "strength-feature-v1"),
        _definition("defense_strength", "defense", "Opponent-adjusted defense index; larger is stronger", "competition primary-against rate / max(team primary-against rate, floor) * opponent Elo factor", "real_xga_or_goals_or_shots", "strength-feature-v1"),
        _definition("goals_for_last5", "attack", "Goals scored in the last five eligible matches", "sum(goals_for over last 5)", "completed_match_results", "goal-form-v1"),
        _definition("goals_against_last5", "defense", "Goals conceded in the last five eligible matches", "sum(goals_against over last 5)", "completed_match_results", "goal-form-v1"),
        _definition("goal_difference_last5", "strength", "Goal difference in the last five eligible matches", "goals_for_last5 - goals_against_last5", "completed_match_results", "goal-form-v1"),
        _definition("home_win_rate", "home_away", "Current-season win rate in home matches", "home wins / eligible home matches", "completed_match_results", "home-away-v1"),
        _definition("home_xg", "home_away", "Current-season real xG per home match", "mean(source home xG)", "provider_real_xg", "home-away-v1"),
        _definition("home_xga", "home_away", "Current-season real xGA per home match", "mean(source home xGA)", "provider_real_xg", "home-away-v1"),
        _definition("home_goals_for", "home_away", "Current-season goals scored per home match", "home goals_for / eligible home matches", "completed_match_results", "home-away-v1"),
        _definition("home_goals_against", "home_away", "Current-season goals conceded per home match", "home goals_against / eligible home matches", "completed_match_results", "home-away-v1"),
        _definition("away_win_rate", "home_away", "Current-season win rate in away matches", "away wins / eligible away matches", "completed_match_results", "home-away-v1"),
        _definition("away_xg", "home_away", "Current-season real xG per away match", "mean(source away xG)", "provider_real_xg", "home-away-v1"),
        _definition("away_xga", "home_away", "Current-season real xGA per away match", "mean(source away xGA)", "provider_real_xg", "home-away-v1"),
        _definition("away_goals_for", "home_away", "Current-season goals scored per away match", "away goals_for / eligible away matches", "completed_match_results", "home-away-v1"),
        _definition("away_goals_against", "home_away", "Current-season goals conceded per away match", "away goals_against / eligible away matches", "completed_match_results", "home-away-v1"),
        _definition("days_since_last_match", "fatigue", "Rest days since the last eligible match", "(cutoff - last kickoff) in days", "completed_match_results", "fatigue-v1", ttl=24.0),
        _definition("matches_last_7_days", "fatigue", "Eligible matches in the preceding seven days", "count(kickoff in [cutoff-7d, cutoff))", "completed_match_results", "fatigue-v1", ttl=24.0),
        _definition("matches_last_14_days", "fatigue", "Eligible matches in the preceding fourteen days", "count(kickoff in [cutoff-14d, cutoff))", "completed_match_results", "fatigue-v1", ttl=24.0),
        _definition("matches_last_30_days", "fatigue", "Eligible matches in the preceding thirty days", "count(kickoff in [cutoff-30d, cutoff))", "completed_match_results", "fatigue-v1", ttl=24.0),
        _definition("fatigue_score", "fatigue", "Transparent schedule-fatigue score from 0 to 1", "mean(short-rest, density-7, density-14, density-30 penalties)", "completed_match_results", "fatigue-v1", ttl=24.0),
        _definition("player_impact", "player", "Configured source-backed player availability impact", "sum(active cutoff-safe player impact rules)", "player_impact_rules", "player-impact-rule-v1"),
    ]
    for window in (3, 5, 8):
        definitions.extend(
            (
                _definition(f"rolling_xg_{window}", "xg", f"Mean real xG over the last {window} matches", f"mean(source xG over last {window})", "provider_real_xg", "xg-rolling-v1"),
                _definition(f"rolling_xga_{window}", "xg", f"Mean real xGA over the last {window} matches", f"mean(source xGA over last {window})", "provider_real_xg", "xg-rolling-v1"),
            )
        )
    for window in (3, 5, 8, 10):
        for metric in ("points", "win_rate", "draw_rate", "loss_rate", "goals_for", "goals_against"):
            definitions.append(
                _definition(
                    f"{metric}_last_{window}",
                    "form",
                    f"{metric.replace('_', ' ').title()} over the last {window} matches",
                    f"aggregate {metric} over last {window} eligible matches",
                    "completed_match_results",
                    "form-feature-v1",
                )
            )
        definitions.extend(
            (
                _definition(f"xpoints_delta_last_{window}", "form", f"Actual minus provider xPoints over the last {window} matches", "actual points - sum(provider source xPoints)", "provider_source_xpoints", "performance-expectation-v1"),
                _definition(f"performance_vs_expectation_last_{window}", "form", f"Performance label over the last {window} matches", "delta > 0.5 positive; delta < -0.5 negative; otherwise as expected", "provider_source_xpoints", "performance-expectation-v1", value_type="string"),
            )
        )
    return tuple(definitions)


class FeatureRegistry:
    """Persist and resolve immutable feature definitions through the repository."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def seed(self) -> list[dict[str, Any]]:
        saver = getattr(self.repository, "save_feature_registry", None)
        if not callable(saver):
            raise FeatureRegistryError("repository does not support feature registry persistence")
        return [saver(definition.as_dict()) for definition in builtin_feature_definitions()]

    def list(self, *, status: str | None = "active") -> list[dict[str, Any]]:
        reader = getattr(self.repository, "feature_registry", None)
        if not callable(reader):
            return []
        return reader(status=status)

    def get(self, feature_name: str, calculation_version: str | None = None) -> dict[str, Any] | None:
        reader = getattr(self.repository, "feature_registry", None)
        if not callable(reader):
            return None
        rows = reader(feature_name=feature_name, calculation_version=calculation_version)
        return rows[0] if rows else None
