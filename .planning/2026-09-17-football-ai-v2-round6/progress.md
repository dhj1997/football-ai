# Round 6 Progress

## 2026-09-17

- Read the complete Round 6 execution prompt and adopted it as the approved
  evaluation-only design baseline.
- Confirmed the worktree contains extensive uncommitted Round 1-5 work; all
  Round 6 changes must preserve it.
- Reviewed the strict no-ML architecture and required Round 2-5 reports.
- Confirmed legacy `backtest_engine.py` and `model_evaluation.py` contain
  learned weights, fitted calibration, bootstrap, and betting concerns, so
  Round 6 must not execute those computation paths.
- Started read-only audits of existing historical persistence, evaluation
  contracts, and the configured MySQL data.
- Completed the repository-specific design at
  `docs/superpowers/specs/2026-09-17-football-ai-v2-round6-temporal-evaluation-design.md`.
- Selected persisted Round 5 audits only, canonical read-only leakage rechecks,
  existing scheduler cutoff bands, and optional immutable `backtest_runs`
  persistence with no migration.
- Started the pure metric and temporal evaluation implementation.
- Implemented the pure probability metric service, persisted-audit temporal
  service, independent coverage/calibration/segments, admin GET, and explicit
  immutable-run POST without a migration.
- Round 6 focused tests passed: 27. Round 2/5 regressions passed: 43. Existing
  API regression passed: 27.
- Read-only real MySQL service validation over the bounded 2026-09-17 window
  returned 16 discovered fixtures, zero persisted probability audits, zero
  evaluable observations, and truthful `insufficient_data`.
- Added `docs/AI_ROUND6_REPORT.md`; final compileall, diff check, and focused
  review remain.
- Resumed after review, confirmed no P0, and split non-overlapping API,
  repository, and documentation hardening tasks for parallel completion.
- A root-level focused pytest attempt failed at collection because `app` was
  outside the import path; subsequent API tests must run from `apps/api`.
- Fixed the Round 6 audit fixture identity, zero-limit behavior, bounded
  leakage reads, unknown source replay assertions, complete fingerprint test,
  and sticky WARN/unknown handling.
- Focused tests now reach 28 passing with one expected API assertion mismatch:
  strict Pydantic validation returns HTTP 422 instead of the former 400.
- Completed strict API, per-run provenance, immutable collision, and concurrent
  reuse hardening; Round 6 plus its new API contract tests pass `34 passed`.
- Revalidated the configured real MySQL path twice with no initialization or
  persistence: 16 discovered, 9 missing audit, 7 missing result, 0 evaluated,
  stable fingerprint, `insufficient_data`, and unchanged row counts in
  `backtest_runs`, `market_snapshots`, and `leakage_audits`.
- Repository hardening passed Round 2 plus temporal tests (`41 passed`) and
  targeted SQLite/MySQL unique-conflict simulations; unrelated integrity
  failures remain fail-closed.
- Necessary Round 5, full API, fixture repository, and immutable backtest
  regressions passed (`62 passed`); bundled-runtime `compileall -q app tests`
  passed and tracked `git diff --check` reported no whitespace error.
- Final report now records `34/41/62`, successful compile/diff checks, and a
  complete 22-item delivery summary. Independent final review found no P0/P1;
  all five phases are complete without commit, push, deploy, or migration.
