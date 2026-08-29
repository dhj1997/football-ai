# P3 Prediction Intelligence Upgrade

## Goal

Add timestamp-safe feature snapshots, explainable dynamic ensemble weighting, out-of-sample calibration, and honest backtest/ablation reporting while preserving P0/P1/P2 contracts.

## Phases

### Phase 1: Feature snapshot
- Status: in_progress
- Build deterministic `p3-v1` features from existing evidence with strict as-of filtering.

### Phase 2: Ensemble and calibration
- Status: pending
- Add weighted DeepSeek/GPT/Poisson ensemble, profile hierarchy, shrinkage, drift monitoring, and temperature calibration.

### Phase 3: Backtest and API
- Status: pending
- Add historical evaluator, ablation reporting, and read-only intelligence endpoints without changing frontend behavior.

### Phase 4: Verification and delivery
- Status: pending
- Add focused tests, run required regression checks, commit, and push directly to `main`.

## Constraints

- Work directly on `main`; no branch, PR, cherry-pick, or long-running loop.
- Do not alter P0/P1/P2 core semantics or frozen prediction fields.
- No new model provider, real betting, Kelly, stacking, or speculative external data.
- Use existing evidence and settlement data; report insufficient samples honestly.
- Keep tests focused on changed contracts and required regressions.
