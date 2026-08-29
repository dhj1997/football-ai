# Progress

## 2026-08-29

- Read AGENTS.md, the P2 task document, P0/P1 implementation, tests, and recent main history.
- Confirmed user choice A: default `min_edge` and `min_ev` are both `0.05`, with legacy fields retained.
- Presented and received approval for the deterministic portfolio/execution design.
- Wrote and committed the design spec as `fc3c0b5`.
- Started Phase 1: policy and pure portfolio primitives.
- Added `PortfolioConfig`, deterministic `BetCandidate` scoring, Edge/EV, freshness, Risk Gate, exposure selection, fixture correlation, and drawdown helpers.
- Added additive/idempotent `bet_executions` storage and immutable execution settlement/cancellation methods.
- Wired P2 policy into `BankrollService`, application settings, `/api/executions`, decision payloads, and separate betting performance aliases.
- Added 11 focused P2 tests; affected regression set passes 56 tests.
- Full API suite passes 167 tests with 1 existing Starlette/httpx deprecation warning; web lint/build, migration idempotence, and diff checks pass.
- Final affected API check passes 26 tests with the same 1 warning after execution-status visibility refinement.
- Three `git push origin main` attempts were blocked by transient GitHub HTTPS connectivity/reset; local `main` remains clean with the complete commits ready to push.
