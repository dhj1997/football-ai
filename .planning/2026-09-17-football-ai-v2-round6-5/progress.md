# Round 6.5 Progress

## 2026-09-17

- Read the complete Round 6.5 execution prompt.
- Confirmed this is evidence infrastructure, not model development or
  backtest optimization.
- Preserved the dirty Round 1-6 worktree and created a scoped execution plan.
- Started the actual persistence/schema audit; implementation has not started.
- Completed the repository and contract audit and recorded the minimal design
  in the Round 6.5 design document.
- Added the fail-closed production evidence validator, nullable physical
  persistence timestamp, migration registration, and atomic repository writer.
- Added the strict Round 6 production-evidence consumer and focused tests.
- Fixed SQLite initialization so the nullable market snapshot column is
  checked only after the table exists.
- First combined Round 6.5/Round 6 run reached 44 passed and one test-fixture
  failure; corrected the fixture to satisfy the existing evidence hash contract.
- Production-path, writer, and Round 6 focused verification reached 61 passed.
- Read-only real MySQL inspection found no deployed `persisted_at` column,
  zero market snapshots/revisions, and made no writes.
- The first shared regression run reached 59 passed with two stale migration
  expectation failures; updated those assertions for migration `0007`.
- Re-ran the migration cases successfully (`2 passed`) and the complete scoped
  shared regression set successfully (`61 passed`).
- Final cross-module review found and fixed duplicate dual-model evidence
  ownership and the Round 6 MODEL_ONLY `market_prior_id=None` compatibility
  boundary without relaxing any audit gate.
- Resumed the scoped Round 6.5 plan, restored its active-plan pointer, and
  incorporated final review findings.
- Added exact matching between the evidence-declared `leakage_audit_id` and
  the loaded append-only audit row, plus a focused mismatch regression.
- Clarified that the serving revision carries the Round 5 model probability,
  while Round 5 evidence is authoritative for model/market/final layers.
- Added a real dual-model SQLite integration assertion for two provider
  revisions and exactly one shared Round 5 production evidence row; completed
  its input fixture with cutoff-safe finished-match history.
- Final prediction/dual-model/P0/Round 6.5/Round 6 set passed `102` tests;
  the Round 2/Round 4/Round 5/P15 regression set passed `61` tests.
- Final `compileall` and `git diff --check` passed; the latter reported only
  existing Windows LF/CRLF conversion warnings.
- Hardened the repository probability guard against inherited prediction
  mappings by validating the fully merged revision candidate before opening
  the transaction.
- Refreshed the real MySQL inspection read-only on 2026-09-18: no deployed
  `persisted_at`, zero market snapshots/revisions, four feature/leakage rows,
  and 71,249 odds snapshots; no production writes were made.
- Made the production evidence version an explicit fail-closed validator
  input instead of merely normalizing every accepted record to the latest
  version.
- Bound one production market snapshot ID to each revision identity so
  conflicting retries fail the immutable-content check and cannot create
  multiple production rows for a single revision.
- Added Round 6 cross-checks between the persisted serving revision and the
  audited model probability plus probability model/calculation versions.
- Added a final transaction-boundary kickoff check and a focused rollback test
  for a write that starts before kickoff but completes at kickoff.
- Final related production-chain regression passed `109` tests; the shared
  Round 2/Round 4/Round 5/P15 regression remained `61 passed`.
- Preserved exactly-once retry semantics across kickoff: an identical late
  retry returns already committed pre-kickoff evidence with its original
  timestamp, while new or conflicting evidence remains blocked.
- Bound the transaction to the persisted fixture kickoff and expanded the
  bounded unique-conflict retry classifier across prediction, revision, and
  market evidence inserts.
- The first regression after the authoritative-kickoff guard failed only
  because the dual-model integration fixture was not persisted; aligned that
  test with the real production path by storing the target fixture first.
- Final production-chain regression passed `114` tests. The Windows runtime
  printed one non-fatal `0x800703e5` platform-probe stack, then pytest finished
  the full set successfully; the existing pytest-cache warning remained.
- Strengthened the authoritative fixture guard with a MySQL row lock and a
  persisted `scheduled` status check; SQLite already holds its write lock by
  this point in the transaction.
- Final serial production-chain regression passed `115` tests without the
  earlier Windows platform-probe stack; only existing framework/test-marker
  and pytest-cache warnings remained.
- Final immutable-retry review moved mutable fixture gates to first writes
  only; retries after live/finished/rescheduling compare the original evidence
  and retain its original timestamp.
- Added write-side equality checks for both probability version fields and
  restricted integrity-error retries to unique-key competition, with focused
  missing/tampered-version and NOT NULL/CHECK/FK negative cases.

## 2026-09-18 Final handoff

- Resumed the existing pytest session rather than rerunning it. The final
  post-hardening set completed: `98 passed, 1 warning in 114.95s`, covering
  Round 6.5 production evidence, the Round 6 consumer, the real dual-model
  integration case, and the Round 2 repository with pytest caching disabled.
- Re-ran `compileall -q app tests` successfully after the final code patches.
- Re-ran `git diff --check` successfully; only existing LF/CRLF conversion
  warnings were emitted. Untracked Round 6.5 files need a separate check.
- Read-only handoff review found no new code blocker and identified report
  wording to clarify first-write-only fixture gates and the application-side
  timestamp/clock-check boundary, without claiming COMMIT completion timing.
- Updated the Round 6.5 report and design with the final test result, accurate
  retry/version behavior, changed-file inventory, and the preserved ignored
  review database (`apps/api/.tmp/round65-review/round6-5.db`, 561,152 bytes).
- No commit, push, deployment, production database write, or cleanup-approval
  workaround was performed.
- Separately checked whitespace/conflict diagnostics for the untracked
  Round 6.5 source, tests, report, design, and scoped planning files using
  `git diff --no-index --check`; all passed.
- Marked Phase 5 complete after the final test, compilation, report review,
  and whitespace checks. The implementation is complete locally and remains
  undeployed; application timing still does not prove COMMIT-completion time.

## 2026-09-18 Squad fallback repair

- Added an ESPN evidence fallback when Dongqiudi returns an empty roster; empty
  Dongqiudi snapshots are no longer persisted as successful roster data.
- Added regression coverage for the fallback and preserved the source marker
  `espn-evidence-fallback` in fixture team data.
- Tightened Dongqiudi league normalization to require the matching country for
  EPL/La Liga names. Deployed the two scoped runtime files with backups and
  verified API health after restart.
- Production verification found an existing malformed fixture (`dongqiudi-54602722`:
  Australian clubs mapped to La Liga). It was marked `cancelled` with
  `excluded_invalid_competition_mapping`; the raw row was retained.
- Production `squad_backfill` now completes without targeting that malformed
  fixture. Local pytest could not run because the checkout venv points to a
  removed Python installation and the bundled runtime lacks pytest; compileall
  and remote `py_compile` passed.
