# Findings

- Existing `prediction.py` is a pure, odds-independent Poisson forecast and must remain unchanged.
- `PredictionService` already creates an immutable Evidence Snapshot and stores a nested Poisson baseline before saving each model prediction.
- Evidence providers expose recent results with dates and scores, league standings with goals for/against, lineup and squad availability, and player impact metadata.
- P1 `SettlementService` already computes Brier, LogLoss, RPS, ECE, CLV, model reports, and Poisson baseline comparisons.
- The repository has no separate historical feature/ensemble tables or dataset. P3 should derive backtest rows from persisted predictions and fixture settlements and return unavailable states when samples are insufficient.
- Prediction rows are immutable after insertion; new P3 metadata must be written at creation or kept in separate derived snapshots, never patched into frozen fields.
