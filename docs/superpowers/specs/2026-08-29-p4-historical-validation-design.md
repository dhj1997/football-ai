# P4 Historical Data & Validation Infrastructure

## Scope

Add traceable historical snapshots, timestamp-safe reconstruction, reusable backfill/rolling validation, and data-quality reporting without changing P0-P3 prediction, settlement, portfolio, or execution semantics.

## Persistence

Reuse immutable `evidence_snapshots`, `odds_snapshots`, predictions, and settlements. Add only append-only `historical_snapshots` and `backtest_runs` records with idempotent schema creation. Historical records store source/version/config payloads and are never overwritten; corrections use a new version.

## As-of Reconstruction

`HistoricalValidationService` accepts a fixture and `as_of`, filters every dated source record to `captured_at <= as_of`, selects closing odds as the latest valid quote strictly before kickoff, and reports missing/conflicting sources instead of silently replacing them. Canonical fixture/team/league identities are deterministic and retain source mappings.

## Backfill and Rolling Validation

`HistoricalBackfillService` delegates prediction creation to an injected formal-pipeline runner while supplying the reconstructed snapshot and timestamp. `RollingBacktestService` uses configurable `train_days`, `test_days`, and `step_days`; each window builds profiles and calibration only from prior settled rows, then returns separate forecast and betting metrics plus exclusions and leakage state.

## Data Quality and API

Quality checks cover missing identity/kickoff/result, duplicates, odds gaps, timestamp inconsistencies, and source conflicts. A 0-1 score is diagnostic/filtering metadata only and never changes probabilities. Read-only endpoints expose runs, snapshots, and quality reports.

## Verification

Focused tests cover as-of leakage, snapshot immutability, identity mapping/conflict, closing odds, backfill boundaries, rolling reproducibility, as-of weights/calibration, and quality exclusions. Existing P0-P3 suites remain unchanged.
