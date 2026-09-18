# Football AI v2 Round 3 Report

## 1. Completed Work

- Added the strict no-ML, point-in-time Feature Engine v2 and deterministic snapshot hashing.
- Added a 62-definition versioned Feature Registry with immutable definitions and lifecycle deprecation.
- Extended append-only feature values with entity, type, calculation version, provenance, quality, and missing-reason metadata.
- Added cutoff-safe Elo, strength, goals, real-xG, form, xPoints performance, home/away, fatigue, and player-rule features.
- Integrated repository-capable production prediction snapshots with v2 while retaining the Round 2 sanitizer for legacy prediction inputs.
- Added `GET /match/{fixture_id}/features` with latest audit-passed and exact historical revision selection.
- Added persisted coverage calculation and a fail-closed learned/fitted/LLM numeric-input guard.

## 2. Database Changes

Migration `0006-round3-feature-engine` adds:

- `feature_registry`
- `player_impact_rules`
- `feature_values.registry_id`
- `feature_values.entity_type`
- `feature_values.entity_id`
- `feature_values.value_type`
- `feature_values.calculation_version`
- `feature_values.source_record_ids`
- `feature_values.quality_score`
- `feature_values.missing_reason`

Repository initialization also creates indexes for Registry group/status lookup,
feature entity/name lookup, and player-rule cutoff selection. Definitions, rules,
snapshots, and values are immutable or append-only; lifecycle deprecation does
not rewrite historical values.

Rollback is intentionally manual and destructive: after a verified backup,
remove the three Round 3 indexes, remove the eight added `feature_values`
columns, then drop `player_impact_rules` and `feature_registry`. No automated
destructive rollback was added.

## 3. New Feature List

The Registry contains 62 definitions:

- Elo (3): `team_elo`, `home_elo`, `away_elo`
- Strength (2): `attack_strength`, `defense_strength`
- Goal form (3): `goals_for_last5`, `goals_against_last5`, `goal_difference_last5`
- Real xG (6): `rolling_xg_3/5/8`, `rolling_xga_3/5/8`
- Form (32): points, win/draw/loss rates, goals for/against, xPoints delta, and performance label for windows 3/5/8/10
- Home/away (10): win rate, real xG/xGA, and goals for/against for the applicable side
- Fatigue (5): rest days, match counts over 7/14/30 days, and fatigue score
- Player (1): `player_impact`

A two-team fixture snapshot contains 112 expected value rows because team-level
features are emitted separately for the home and away entities, while side-only
definitions are emitted only for their applicable side.

## 4. Calculation Formulas

- Elo: initial 1500, K=20, home advantage=60; updates use only completed results available by cutoff.
- Strength source ladder: real xG, then goals, shots on target, then shots. The selected tier is never blended or converted into estimated xG.
- Attack strength: team primary-for rate divided by competition primary-for rate, multiplied by the clamped mean opponent pre-match Elo factor.
- Defense strength: competition primary-against rate divided by the team primary-against rate floor, multiplied by the same opponent factor.
- Rolling xG/xGA: arithmetic means of provider-supplied genuine xG only.
- Form: deterministic totals and rates over eligible windows 3/5/8/10.
- Performance versus expectation: actual points minus provider xPoints; above 0.5 is positive, below -0.5 is negative, otherwise as expected.
- Home/away: current-season split rates and per-match means, never mixed across venue side.
- Fatigue: mean of versioned short-rest and 7/14/30-day density penalties.
- Player impact: sum of active database rules supported by cutoff-safe absence evidence; no rule is missing, not zero.
- Quality: unweighted mean of source reliability, freshness, completeness, provider availability, and calculation success; missing values score zero.

## 5. Data Sources

- Elo, goals, form, venue splits, and fatigue use completed match results and schedule timestamps whose availability is no later than the prediction cutoff.
- Attack and defense strength use one explicit source tier per calculation: provider real xG when present, otherwise goals, shots on target, or shots. A lower tier is never relabeled as xG.
- Rolling xG/xGA and performance versus expectation use provider-supplied real xG/xPoints only. Missing source fields produce `null` values with an explicit `missing_reason`.
- Player impact uses versioned `player_impact_rules` plus cutoff-safe player absence evidence. Displayed player names continue through the existing Chinese-name normalization path.
- Every emitted row retains source record IDs and availability metadata. LLM output is not a numeric feature source.

## 6. Leakage Verification

All required tests were added and pass:

- `test_feature_available_at_boundary`
- `test_feature_respects_prediction_cutoff`
- `test_elo_no_future_matches`
- `test_form_no_future_matches`
- `test_xg_no_future_matches`
- `test_home_away_feature_boundary`
- `test_feature_reproducibility`

Additional tests cover Registry and value immutability, player-rule cutoff
selection, nested LLM numeric denial, coverage audit selection, migration
idempotency, and exact-revision explanation.

Final verification:

- Full API suite: `557 passed`, `5 warnings`
- `compileall`: passed
- `git diff --check`: passed after implementation (line-ending notices only)

The warnings are one Starlette/httpx deprecation and four pre-existing pytest
marker warnings in `test_prediction_service.py`.

## 7. Coverage Report

See `docs/AI_ROUND3_FEATURE_COVERAGE.md`.

The configured MySQL database currently reports `no_snapshots`: zero total
feature snapshots, zero v2 snapshots, and migration `0006` is not deployed.
No test data was used to claim production coverage.

## 8. Unfinished Items

- Apply migration `0006-round3-feature-engine` to a staging copy, then the configured database under the normal deployment process.
- Accumulate real audit-passed v2 snapshots before publishing competition percentages.
- Add a licensed/source-backed xG and xPoints feed if those feature groups are expected to have non-zero coverage; current providers do not expose them.
- The supported `market` Registry group has no Round 3 feature definition because market-prior modeling belongs to a later round.

No deployment, production migration, probability model, Poisson/Dixon-Coles
engine, UI change, or betting-strategy change was performed.

## 9. Round 4 Recommendation

First deploy and observe Round 3 data collection. Re-run the generated coverage
report and inspect missing reasons by competition before starting Round 4.
Only after coverage and leakage audits are stable should a separate approved
round introduce transparent statistical probability models.
