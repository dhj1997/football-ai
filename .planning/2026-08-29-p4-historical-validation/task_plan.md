# P4 Historical Data & Validation Infrastructure

## Goal

Build traceable, timestamp-consistent historical snapshots, backfill/rolling validation contracts, and explainable data-quality reporting while preserving P0-P3 behavior.

## Phases

### Phase 1: Persistence and identity
- Status: in_progress
- Add idempotent append-only historical snapshot/backtest run persistence and canonical fixture/team/league identity helpers.

### Phase 2: Historical reconstruction and quality
- Status: pending
- Implement as-of evidence/odds reconstruction, closing odds selection, source conflicts, freshness rules, and quality exclusions.

### Phase 3: Backfill and rolling validation
- Status: pending
- Add reusable formal-pipeline backfill and configurable train/test/step rolling backtest with as-of weights/calibration.

### Phase 4: Read-only APIs and tests
- Status: pending
- Expose P4 reports and add focused leakage, immutability, identity, quality, rolling, and reproducibility tests.

### Phase 5: Verification and delivery
- Status: pending
- Run required regression checks, update records, commit, and push directly to `main`.

## Constraints

- Work directly on `main`; no branch, PR, cherry-pick, or real-money action.
- Reuse existing evidence/odds/prediction/settlement tables and services where possible.
- No future data in snapshots, backfill, weights, calibration, or rolling evaluation.
- No new model provider, Kelly sizing, betting strategy, or large frontend change.
- Missing data remains explicit and quality scores never mutate probabilities.
