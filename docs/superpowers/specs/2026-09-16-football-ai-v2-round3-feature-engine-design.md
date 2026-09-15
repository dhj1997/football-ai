# Football AI v2 Round 3 Feature Engine Design

**Date:** 2026-09-16
**Status:** Approved for implementation planning
**Scope:** Point-in-Time Feature Engine v2 under the strict no-ML architecture

## 1. Objective

Round 3 extends the Round 2 point-in-time snapshot and revision chain into a reliable, explainable, auditable, and reproducible feature engine. It must provide versioned feature inputs for later Elo, Poisson, Dixon-Coles, market-prior, deterministic-fusion, and backtest rounds without implementing those probability engines in this round.

The implementation is incremental. It keeps the existing FastAPI application, `PredictionRepository`, `feature_snapshots`, `feature_values`, `prediction_revisions`, and `leakage_audits` as the system of record. It must not create a parallel feature store or prediction pipeline.

## 2. Hard Boundaries

Round 3 must not introduce or execute any trainable model, learned parameter, fitted weight, or fitted calibrator. XGBoost, LightGBM, random forests, SVMs, neural networks, Transformers, LSTMs, GNNs, Platt scaling, and isotonic calibration are prohibited.

LLMs may structure source-backed evidence and explain already-calculated features, but they may not produce or modify probabilities, expected goals, fusion weights, predictions, or stakes. The v2 production path must fail closed when a learned engine, learned weight, fitted calibrator, or LLM numeric output is presented. Historical artifacts and revisions remain readable for audit only.

This round does not implement Poisson, Dixon-Coles, probability fusion, betting changes, or UI changes.

## 3. Architecture

The approved approach is a lightweight calculation layer over the existing Round 2 persistence and audit boundary:

```text
feature_registry
        |
fixture + cutoff-safe evidence
        |
BaseFeatureCalculator implementations
        |
quality scoring and registry validation
        |
feature_snapshots -> feature_values -> leakage_audits
        |
prediction_revisions
```

`feature_engine.py` owns the result contract, orchestration, registry validation, quality calculation, and deterministic snapshot assembly. `feature_registry.py` owns the versioned definitions and seed data. Existing `recent_form.py`, `elo.py`, and `player_impact.py` remain the domain owners and are extended rather than copied. A focused calculator module may adapt these existing services to the common contract.

The existing `build_feature_snapshot` function remains as a compatibility entry point and delegates to Feature Engine v2. Current prediction reads and revision storage remain unchanged except for consuming the enriched snapshot.

## 4. Data Model

### 4.1 Feature Registry

Add `feature_registry` with at least:

```text
id
feature_name
feature_group
entity_type
description
formula
source
calculation_version
status
created_at
deprecated_at
payload
```

Supported groups are `elo`, `strength`, `attack`, `defense`, `xg`, `form`, `home_away`, `fatigue`, `player`, and `market`. Supported entity types are `team`, `player`, `match`, and `competition`.

The unique identity is `feature_name + calculation_version`. Definitions are immutable after publication. A formula or source-policy change creates a new registry row and calculation version. Deprecation changes lifecycle status without rewriting historical feature values.

Registry metadata also states whether a feature is required for admission, its expected value type, freshness TTL, and deterministic source policy. These fields live in the JSON payload to avoid unnecessary schema expansion.

### 4.2 Feature Values

Extend the existing append-only `feature_values` table while preserving its `snapshot_id` and ordinal relationship. Add:

```text
registry_id
entity_type
entity_id
value_type
calculation_version
source_record_ids
quality_score
missing_reason
```

Every registered feature produces a row, including unavailable features. An unavailable value stores JSON `null`, `quality_score = 0`, and a specific `missing_reason`. This makes coverage measurable and prevents absent rows from inflating coverage.

Existing identity and immutability checks are extended to include the new version and provenance fields. Re-saving the same deterministic snapshot is idempotent; changing any hash-defining field under an existing snapshot ID is rejected.

### 4.3 Player Impact Rules

Add `player_impact_rules` with at least:

```text
id
player_id
role
impact_type
impact_value
confidence
source
available_at
rule_version
status
created_at
deprecated_at
payload
```

Player-specific impact values are configuration data, not Python constants. A modification publishes a new rule version. The calculator selects only active rules whose `available_at` is no later than the prediction cutoff. A missing rule is reported as missing rather than interpreted as zero impact.

All player names exposed through APIs, pages, or logs must pass through `to_chinese_player_name`. Persistence and joins use canonical player IDs.

## 5. Calculator Contract

Every calculator implements the equivalent of:

```python
calculate(entity_id, prediction_cutoff_at) -> FeatureResult
```

`FeatureResult` contains:

```text
feature_name
value
value_type
entity_type
entity_id
available_at
source
source_record_ids
quality_score
calculation_version
missing_reason
status
```

Calculators receive cutoff-aware repository readers or frozen input collections. They do not call unrestricted readers and filter afterward. Results are deterministically ordered before snapshot hashing.

## 6. Feature Definitions

### 6.1 Elo

Use the existing transparent Elo constants as version `elo-feature-v1`: initial rating `1500`, K-factor `20`, and home advantage `60`.

```text
expected_home = 1 / (1 + 10 ** ((away_rating - home_rating - 60) / 400))
delta = 20 * (actual_home - expected_home)
```

`team_elo` updates the overall state from all eligible matches. `home_elo` and `away_elo` update contextual home and away states. State is partitioned by competition, processed by result availability time and stable fixture ID, and consumes only completed results available by cutoff. Each result records the final contributing fixture IDs and latest `available_at`.

### 6.2 Attack and Defense Strength

The primary observation source follows a fixed non-blending ladder:

```text
real xG -> goals -> shots_on_target -> shots
```

The chosen tier is returned in provenance. No lower tier is transformed into estimated xG.

```text
attack_strength
  = team_primary_for_per_match / competition_primary_for_per_match
    * opponent_strength_factor

defense_strength
  = competition_primary_against_per_match / max(team_primary_against_per_match, floor)
    * opponent_strength_factor

opponent_strength_factor
  = clamp(mean_opponent_pre_match_elo / 1500, 0.75, 1.25)
```

The division floor, competition scope, and source ladder are part of `strength-feature-v1`. Larger values mean stronger performance. Insufficient competition baseline data produces a missing value instead of a default strength.

### 6.3 Goal Expectation Inputs

`rolling_xg_3`, `rolling_xg_5`, and `rolling_xg_8` are arithmetic means of source-provided historical xG. `rolling_xga_3`, `rolling_xga_5`, and `rolling_xga_8` are the corresponding opponent xG means.

Only real provider xG is accepted. When it is unavailable, each registered value is written with `missing_reason = source_xg_unavailable`. Goals, shots, LLM output, and later model estimates must not populate these fields.

`goals_for_last5` and `goals_against_last5` are totals over the five most recent eligible results. `goal_difference_last5` is their difference.

### 6.4 Form

For windows 3, 5, 8, and 10, calculate:

```text
points
win_rate
draw_rate
loss_rate
goals_for
goals_against
```

Rates use the actual eligible sample count. A non-empty undersized window is calculated with `status = insufficient_sample` and a reduced completeness component in its quality score. An empty window is missing.

Performance versus expectation uses only provider-supplied historical xPoints. For each window:

```text
delta = actual_points - sum(source_xpoints)
delta > 0.5  -> positive_overperformance
delta < -0.5 -> negative_overperformance
otherwise    -> as_expected
```

If any required source xPoints observation is unavailable, the aggregate is missing with `missing_reason = source_xpoints_unavailable`. Round 3 does not calculate xPoints from odds, xG, or a probability model.

### 6.5 Home and Away

Use current-season results available by cutoff. Home features use only matches where the target team was home; away features use only matches where it was away.

```text
home_win_rate, home_xg, home_xga, home_goals_for, home_goals_against
away_win_rate, away_xg, away_xga, away_goals_for, away_goals_against
```

Win rates are ratios. Goal and genuine xG values are per-match means for the relevant split. Missing xG does not prevent goal or win-rate features from being produced.

### 6.6 Fatigue

Only earlier completed fixtures are counted. The current fixture is excluded.

```text
days_since_last_match
matches_last_7_days
matches_last_14_days
matches_last_30_days

short_rest_penalty = clamp((5 - rest_days) / 5, 0, 1)
density_7_penalty  = clamp((matches_7 - 1) / 3, 0, 1)
density_14_penalty = clamp((matches_14 - 3) / 4, 0, 1)
density_30_penalty = clamp((matches_30 - 6) / 6, 0, 1)

fatigue_score = mean(
  short_rest_penalty,
  density_7_penalty,
  density_14_penalty,
  density_30_penalty
)
```

The score ranges from 0 to 1, where larger values mean greater schedule fatigue. This rule is published as `fatigue-v1`; future threshold changes require a new version.

### 6.7 Player Impact

The player calculator applies only database-backed, cutoff-eligible rules supported by availability or lineup evidence. For the same player and impact type, the selected rule version is deterministic. Applicable impacts are summed by team and role, with each rule ID retained in provenance. No rule or no evidence produces a missing value rather than an implicit zero.

## 7. Feature Quality

Each available feature has five components in `[0, 1]`:

```text
source reliability
freshness
input completeness
provider availability
calculation success
```

`quality_score` is their unweighted arithmetic mean, rounded to four decimals. Freshness declines linearly from 1 to 0 over the registry TTL. Calculation success is 1 or 0. Source reliability levels, TTLs, and completeness expectations are versioned registry configuration and are never fitted from results. Missing values have quality 0.

## 8. Leakage and Failure Behavior

- A non-empty input with `available_at > prediction_cutoff_at` creates a failed leakage audit and is denied admission to the prediction pipeline.
- A non-empty input whose availability cannot be proven also fails closed.
- An unregistered feature or calculation-version mismatch fails snapshot admission.
- A genuinely absent source value is persisted as missing and is not itself a leakage violation.
- A calculator exception becomes `calculation_failed` with quality 0. It blocks snapshot admission only when the registry marks that feature as required.
- The failed snapshot and audit remain durable; no prediction revision is written after a failed gate.
- Legacy learned and LLM numeric paths are denied in v2 production and emit audit evidence without deleting historical records.

## 9. Explanation API

Add the required read-only route:

```text
GET /match/{id}/features
```

Keep `/api/features/{fixture_id}` as a backward-compatible route over the same service. With no revision selector, the new route returns the latest audit-passed snapshot for the match. Optional `prediction_id` and `revision` parameters resolve the exact feature snapshot referenced by a historical prediction revision.

The response groups features under `elo`, `strength`, `attack`, `defense`, `xg`, `form`, `home_away`, `fatigue`, `player`, and `market`. Each feature exposes its value, status, description, formula/calculation version, source records, `available_at`, quality score, and missing reason. The endpoint never recomputes historical values from mutable current data.

## 10. Coverage Report

Generate `docs/AI_ROUND3_FEATURE_COVERAGE.md` from persisted Feature Engine v2 values. For each competition and feature group:

```text
denominator = registered expected values across each fixture's latest valid snapshot
numerator   = non-missing, audit-passed values in those snapshots
coverage    = numerator / denominator
```

When no eligible snapshots exist, report `no_snapshots` rather than a percentage. Include fixture count, snapshot count, feature version, calculation versions, and generation cutoff so the report cannot be mistaken for timeless production coverage.

## 11. Migration

Add the idempotent additive migration `0006-round3-feature-engine` to the existing `production.py` migration system and mirror its schema in `PredictionRepository.initialize()`. The migration creates `feature_registry` and `player_impact_rules`, then adds the new feature-value columns using the repository's cross-database compatibility helpers.

Existing rows remain readable. New writes populate all v2 fields. The rollback documentation identifies only Round 3 tables, indexes, and added columns; automated destructive rollback is not introduced.

## 12. Tests and Verification

Required leakage and determinism tests:

```text
test_feature_available_at_boundary
test_feature_respects_prediction_cutoff
test_elo_no_future_matches
test_form_no_future_matches
test_xg_no_future_matches
test_home_away_feature_boundary
test_feature_reproducibility
```

Focused tests also cover registry immutability/versioning, append-only feature values, missing real xG and xPoints, fatigue boundaries, quality scoring, player-rule cutoff selection and Chinese player-name output, exact revision explanation, coverage calculation, migration idempotency, and no-ML/LLM-numeric deny gates.

Because the feature snapshot is a shared prediction contract, final verification includes the relevant focused suite followed by the complete API suite required by the execution prompt:

```text
git diff --check
compileall
pytest
```

## 13. Deliverables and Acceptance

Round 3 is complete only when:

1. Registry, enriched append-only values, calculators, core feature groups, player rules, quality, explanation API, coverage report, and leakage tests are implemented.
2. Every non-missing value has a registered definition, version, source record, and cutoff-safe availability time.
3. Rebuilding identical inputs at the same cutoff and version produces the same snapshot identity and values.
4. The v2 production boundary rejects learned and LLM numeric paths while preserving read-only historical audit.
5. `docs/AI_ROUND3_FEATURE_COVERAGE.md` and `docs/AI_ROUND3_REPORT.md` truthfully report coverage, formulas, validation results, and remaining gaps.
6. Existing tests remain green, with any unrelated environmental limitation reported explicitly.
7. No Round 4 probability model, UI change, or betting-strategy change is included.
