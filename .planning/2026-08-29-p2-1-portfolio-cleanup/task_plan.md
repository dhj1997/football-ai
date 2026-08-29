# P2.1 Portfolio Engine Cleanup

## Goal

Remove the old BankrollService betting policy from production, centralize cash/equity/exposure semantics, and enforce one deterministic cross-model candidate per fixture.

## Phases

### Phase 1: Design and policy audit
- Status: complete
- Confirm canonical account semantics and the Portfolio-only production boundary.

### Phase 2: Canonical Portfolio primitives
- Status: complete
- Add shared active statuses, cash/equity/open-exposure/exposure snapshot functions, and deterministic global candidate selection.

### Phase 3: Bankroll integration cleanup
- Status: complete
- Remove legacy production branches and make BankrollService use the canonical Portfolio policy without changing P0/P1/P2 prediction or settlement contracts.

### Phase 4: Boundary and integration verification
- Status: complete
- Add focused boundary and DeepSeek/GPT/Poisson integration tests, run regressions and checks, commit, and push directly to `main`.

## Constraints

- Work directly on `main`; no branch or PR.
- Do not change P0/P1/P2 prediction, settlement, CLV, calibration, or freeze core logic.
- No Kelly, real-money execution, or new model.
- Do not modify frontend files.
- Use one account money definition and one active status set everywhere.
