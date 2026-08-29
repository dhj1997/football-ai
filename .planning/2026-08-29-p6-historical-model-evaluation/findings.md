# Findings

- P3 already provides normalized probabilities, weighted ensemble, chronological `split_time_ordered`, temperature calibration, and core forecast metrics.
- P4 `RollingBacktestService` already enforces walk-forward windows and separates forecast/betting metrics, but P6 needs a stable experiment/audit facade and model-by-model reports.
- P5 provides CSL/EPL/LAL canonical fixture identity and coverage through `HistoricalLeagueDataService`; the current local dataset may be empty, so evaluation must report insufficient sample without fetching or fabricating data.
- Existing persistence has `predictions`, `historical_snapshots`, and `backtest_runs`; P6 can add only experiment/metric/audit tables with idempotent SQLite/MySQL migrations.
- Existing P2.1 Portfolio/Bankroll services must not be invoked against the real account from evaluation; betting reports are unavailable unless an injected virtual simulation path has a complete frozen chain.
- P6 evaluation consumes persisted fixture settlements and joins immutable predictions/evidence/odds by ID when available; no provider sync is triggered by evaluation.
- Calibration uses a cutoff strictly before the first test prediction timestamp, while the audit permits captures at the prediction boundary itself (`captured_at <= T`).
