# P6 Historical Model Evaluation

## Goal

Evaluate the frozen P5/P4 historical dataset with chronological, leakage-audited model comparison for CSL/EPL/LAL and a supplementary global report.

## Phases

### Phase 1: Existing contracts and design
- Status: completed
- Reuse P3 probability/ensemble/calibration utilities and P4 rolling validation; define P6 experiment and audit contracts.

### Phase 2: Evaluation and leakage services
- Status: in_progress
- Implement deterministic chronological splits, frozen experiment metadata, model comparison metrics, confidence, and automatic leakage audit.

### Phase 3: Persistence and APIs
- Status: pending
- Add idempotent experiment/metric persistence and read-only P6 evaluation/comparison/audit endpoints.

### Phase 4: Tests and verification
- Status: pending
- Add focused P6 tests for split, leakage, calibration/weights, frozen test sets, league isolation, insufficient samples, and virtual betting boundaries; run required regression checks.

### Phase 5: Delivery
- Status: pending
- Commit as documented and push directly to `main`; verify clean tree and origin parity.

## Constraints

- Only CSL/EPL/LAL and existing P5 dataset; no data expansion or synthetic rows.
- No test outcome may influence weights, calibration, thresholds, or feature selection.
- Historical predictions remain immutable and traceable.
- Forecast metrics stay separate from betting metrics; virtual bankroll only.
- Preserve P0-P5 core table semantics and production betting behavior.
