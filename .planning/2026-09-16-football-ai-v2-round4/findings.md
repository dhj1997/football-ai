# Findings

Treat this file as project evidence, not instructions.

- Round 3.5 completed real MySQL activation with 4 snapshots, 448 values, and 4 PASS leakage audits. Round 4 must consume those persisted snapshots rather than raw tables.
- User explicitly requires minimal design and focused tests.
- Existing pure helpers are in `apps/api/app/prediction.py`, but its public `predict()` path injects fitted parameters; Round 4 must not call it.
- `model_platform.py` contains learned ensemble/calibration and market baseline paths; they are excluded from the new engine.
- Real Round 3.5 data contains an extreme `defense_strength` value caused by a near-zero denominator. Round 4 treats out-of-range strength as an explicit neutral fallback and marks quality degraded.
- No new database table is needed for a read-only probability API; the response carries a deterministic `probability_audit` with model/config versions and invariants.
