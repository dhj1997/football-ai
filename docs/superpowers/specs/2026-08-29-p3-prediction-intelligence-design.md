# P3 Prediction Intelligence Upgrade

## Scope

Improve prediction intelligence without changing P0 prediction integrity, P1 evaluation/settlement metrics, or P2 portfolio/execution behavior. The implementation reuses existing Evidence Snapshots, Poisson baseline, DeepSeek/GPT predictions, and persisted settlement rows. It adds no model provider, real-money execution, Kelly sizing, stacking, or large frontend rewrite.

## Feature Snapshot

`FeatureSnapshot` is a versioned, deterministic derived view of one immutable Evidence Snapshot. Version `p3-v1` records `fixture_id`, `captured_at`, `prediction_timestamp`, team strength, time-decayed recent form, home/away splits, squad availability, schedule context, and a diagnostics-only market context. Every dated input is filtered to `captured_at <= prediction_timestamp`; future results, closing odds, future lineups, and future injury data are rejected. The snapshot is stored under a separate `feature_snapshot` namespace in the prediction payload so existing frozen fields remain unchanged.

## Ensemble and Weights

`EnsembleService` combines DeepSeek, GPT, and the existing Poisson baseline with a normalized weighted average. `ModelPerformanceProfile` derives weights from P1 Brier, LogLoss, ECE, and CLV observations using the hierarchy `league + market -> league -> global -> baseline`. Raw inverse-error weights are shrunk by `n / (n + k)` and time-decayed; model drift lowers a weight instead of deleting the model. The ensemble snapshot records source probabilities, effective weights, profile scope, and versions.

## Calibration

`CalibrationService` uses deterministic multiclass temperature scaling. Data is ordered by prediction timestamp and split into train, calibration, and evaluation periods. A calibration fit is unavailable below the configured sample minimum; calibration samples never appear in the evaluation slice. Version, method, trained time, sample size, and temperature are recorded with the ensemble result.

## Backtest and API

`BacktestService` evaluates existing model versus P3 ensemble with Brier, LogLoss, ECE, RPS, and CLV where available, plus the required feature/ensemble/calibration ablation steps. It returns explicit insufficient-sample states and never adjusts the evaluation window to manufacture an improvement. New read-only API endpoints expose model performance, ensemble output, calibration state, and feature snapshots. Existing prediction rows and P1/P2 contracts remain compatible.

## Verification

Add focused tests for timestamp leakage, feature versioning, weighted ensemble output, fallback and shrinkage, out-of-sample calibration, market separation, freeze preservation, drift down-weighting, and backtest leakage. Run the full API suite, P0/P1/P2/P3 focused suites, frontend lint/build only because frontend files remain untouched, migration idempotence, and `git diff --check`.
