# Task Plan: Strategy Ledger and Job Status Repair

## Goal

Implement, test, push, deploy, and production-verify the approved reporting
repair while preserving immutable bets, executions, and bankroll transactions.

## Current Phase

Complete

## Phases

### Phase 1: Baseline and regression contracts
- [x] Reconfirm worktree and existing contracts
- [x] Add focused failing regression tests
- **Status:** complete

### Phase 2: Minimal implementation
- [x] Read latest provider job per job name
- [x] Separate financial ledger metrics from prediction evaluation rows
- [x] Apply financial filters and configured drawdown baseline
- **Status:** complete

### Phase 3: Focused verification and review
- [x] Run directly affected test suites
- [x] Compile changed Python sources
- [x] Review diff and whitespace
- **Status:** complete

### Phase 4: GitHub delivery and production deployment
- [x] Commit implementation and push tracked HEAD
- [x] Run MySQL backup and restore verification
- [x] Deploy, build, restart, and verify services/routes
- **Status:** complete

### Phase 5: Historical reconciliation and final audit
- [x] Validate and upsert the two authoritative finished fixtures
- [x] Run existing settlement service idempotently
- [x] Verify the current 50 settled financial bets and unchanged immutable ledger
- [x] Repeat reconciliation and verify no duplicate writes
- **Status:** complete

## Decisions Made

| Decision | Rationale |
|---|---|
| Forecast metrics remain settlement-row based | Prevents fabricated prediction outcomes |
| Financial metrics use every settled paper bet | Makes ROI and bankroll reporting match the immutable ledger |
| Unknown seasons are excluded from season-filtered financial reports | No inferred provenance |
| Use repository initial balance for drawdown | Matches configured production account semantics |
| Reconcile through existing fixture mapper and settlement service | Reuses validated idempotency and avoids direct synthetic SQL |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Parallel pytest processes contended for shared `.pytest_tmp` SQLite file on Windows | 1 | Run the portfolio suite alone with an isolated base temp directory |
| Default `bash` resolved to WSL and lacked `cygpath`/Windows Workbench path | 1 | Re-run the unchanged deploy script with Git for Windows Bash |

## Constraints

- Preserve unrelated `.planning` and `.tmp` changes.
- Keep tests proportional to the two reporting defects.
- Use MySQL in production; SQLite only in isolated tests.
- Do not change model decisions, bets, executions, or bankroll transactions.
