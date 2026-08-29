# P0 Prediction Integrity Architecture

## Scope

This change applies only to the backend, persistence layer, and regression tests. The existing frontend, DeepSeek/ChatGPT prompt content, model count, calibration, full CLV, Kelly, and unrelated business behavior remain unchanged.

## Forecast and Market Separation

`apps/api/app/prediction.py` produces pure Poisson probabilities without reading market odds into the result. The backward-compatible `probabilities` field remains the pure model forecast and is duplicated as `model_probabilities` for explicit consumers. `market_decision.py` reads those values and independently computes priced market rows with `market_probability`, `model_probability`, `price`, and `expected_edge`.

## Snapshot Contract

Evidence snapshots remain append-only and are identified by `id`, `fixture_id`, `captured_at`, `evidence_version`, `content_hash`, and payload. Generated snapshots use stable canonical JSON and SHA-256. Reusing an ID is idempotent only when content is identical.

Odds captures are stored in a new append-only `odds_snapshots` table. A capture has one group ID and one quote row per market/selection/line, preserving bookmaker, source, price, and captured time. Fixture evidence refreshes and prediction creation both append captures. Predictions retain the group ID they used.

## Freeze and Layers

Prediction persistence is insert-only for forecast, model identity/version, prompt, timestamps, and snapshot references. The repository exposes a constrained lifecycle updater for `status` and `metadata`; attempts to overwrite frozen fields fail. Market assessment returns a derived copy, and bankroll candidate evaluation works on copies so no downstream process mutates a saved prediction.

The runtime data flow is:

```text
Forecast -> Market Assessment -> Risk Gate -> Portfolio Selection -> Execution
                                      |
                                  Settlement
```

Settlement reads the saved pure-model probabilities and writes only settlement/performance and bankroll records. It never updates predictions, evidence snapshots, or odds snapshots. Dual-model prediction creation prepares and persists one shared evidence/odds snapshot bundle before invoking both providers.

## Compatibility and Migration

`PredictionRepository.initialize()` creates the odds table, adds nullable frozen columns to existing prediction/evidence tables, backfills them from JSON payloads, and remains safe to run repeatedly on SQLite and MySQL. No existing rows are deleted or core tables rebuilt.

## Verification

Regression tests cover pure forecast stability under changing odds, immutable evidence and odds history, prediction freeze, non-mutating market/bankroll/settlement flows, shared dual-model snapshots, and pure-model forecast metrics. Existing API tests, web lint/build, migration idempotence, and `git diff --check` are required before handoff.
