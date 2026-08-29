# P2 Portfolio / Betting Engine

## Goal

Implement deterministic Edge/EV signals, configurable portfolio risk limits, fixed-fraction stake allocation, paper execution freezing, drawdown protection, and separate betting performance metrics without changing frozen predictions or the frontend.

## Phases

### Phase 1: Policy and pure portfolio primitives
- Status: complete
- Add P2 settings and a small pure `portfolio.py` for candidate construction, scoring, risk checks, exposure and drawdown.

### Phase 2: Persistence and execution lifecycle
- Status: complete
- Add idempotent `bet_executions` persistence, freeze immutable execution fields, and settle only result/PnL metadata.

### Phase 3: Bankroll/API integration
- Status: complete
- Route existing league-day selection through Portfolio, apply configured limits and fixed stake, expose candidate/risk/execution/betting metrics while preserving legacy fields.

### Phase 4: Focused verification
- Status: complete
- Add targeted P2 tests, run affected P0/P1 regressions, migration idempotence, lint/build, and diff checks; commit and push directly to `main`.

## Constraints

- Work directly on `main`; no branch or PR.
- P0/P1 contracts and Prediction Freeze remain intact.
- Paper execution only; no bookmaker integration.
- No Kelly or covariance matrix in this version.
- Do not modify frontend.
- Use risk-proportionate tests only.
