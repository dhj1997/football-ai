# Progress

## 2026-08-29

- Read the P3 task document, AGENTS.md, current main history, prediction/evidence/P1/P2 code, and existing tests.
- Confirmed P3 scope and approved design: feature snapshot, weighted ensemble, dynamic profiles, temperature calibration, honest backtest/ablation, and read-only API.
- Wrote the approved P3 design and initialized the implementation plan.
- Added `prediction_intelligence.py` with timestamp-safe `FeatureSnapshot` (`p3-v1`), time-decayed form, strength, home/away, squad, schedule, and diagnostics-only market context.
- Added weighted DeepSeek/GPT/Poisson ensemble, performance-profile hierarchy, sample shrinkage, time decay, drift down-weighting, temperature calibration, and leakage-safe backtest/ablation utilities.
- Integrated feature snapshots into PredictionService and P3 ensemble metadata into DualPredictionService without changing frozen probability fields.
- Added read-only model-performance, features, ensemble, calibration, and backtest API endpoints.
- P3 focused tests: 6 passed; existing prediction/P0/P1/P2 focused tests: 39 passed.
- Dual model and prediction service regression tests: 5 passed.
- Added future-standings leakage coverage and persisted ensemble metadata through the existing lifecycle metadata field.
- Full pytest: 178 passed, 1 warning.
- Web lint and production build passed; database initialization regression passed.
- No database schema migration or historical data rewrite was introduced.
- Current database backtest: 8 fixtures, 2 evaluation samples; calibration unavailable below the 30-sample threshold.
