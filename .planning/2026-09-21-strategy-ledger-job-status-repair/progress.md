# Progress

## 2026-09-21

### Phase 1: Baseline and regression contracts
- **Status:** complete
- User selected approach A, approved the written design, and requested deployment.
- Design committed as `9abdaa4`.
- Read the `planning-with-files` workflow and created this isolated plan without
  modifying the existing active-plan pointer.
- Confirmed the two code defects and verified the two authoritative historical
  scores before implementation.
- Added focused activation and financial-ledger regression tests.
- Red-light verification passed as expected: both tests failed on the exact old
  behavior (`not_run` and zero financial bets).

### Phase 2: Minimal implementation
- **Status:** complete
- Activation status now reads each provider's latest durable run by job name.
- Financial metrics now read settled bets independently from evaluation rows
  and apply immutable report filters.
- Strategy drawdown now uses the repository's configured initial balance.
- Future bet payloads preserve fixture season when available.
- Both new focused regressions pass.

### Phase 3: Focused verification and review
- **Status:** complete
- Settlement, P1 evaluation, and P15 activation suites passed: `23 passed`.
- Strategy-performance endpoint regression passed: `1 passed`.
- Bankroll regression passed: `24 passed`.
- The parallel portfolio run hit a Windows lock in the shared pytest temp
  directory; this is an environment collision, so the suite will be rerun alone
  with an isolated base temp directory.
- Isolated portfolio rerun passed: `23 passed`.
- Changed Python files compiled successfully and `git diff --check` found no
  whitespace errors.

### Phase 4: GitHub delivery and production deployment
- **Status:** complete
- Pushed design and implementation commits; local and GitHub `main` both
  resolve to `dfadbb8ea4d7ac4e0e319c2431e8f24e01f59d46`.
- Production preflight showed deployed `b94d511`, active API/Web, and healthy
  MySQL.
- First deploy invocation stopped locally before upload because PowerShell's
  default `bash` was WSL, which lacks `cygpath` and could not resolve the
  Windows Workbench executable. No remote mutation occurred.
- Re-ran with Git for Windows Bash. The server build completed, API/Web were
  restarted at `2026-09-21 10:03:24 CST`, and `.deploy-revision` now matches
  `dfadbb8ea4d7ac4e0e319c2431e8f24e01f59d46`.
- Verified the changed backend file hashes match the local checkout; API,
  Web, Nginx, public health, public strategy performance, and `/performance`
  all passed.

### Phase 5: Historical reconciliation and final audit
- **Status:** complete
- A fresh pre-write MySQL backup was restored and verified as
  `/opt/football-ai/backups/db-20260921-101148.sql.gz` across 41 tables.
- Re-fetched TheSportsDB events `2506194` and `2494015`, validated their FT
  scores, mapped them through `TheSportsDbProvider`, and upserted the finished
  fixtures into production MySQL.
- Ran the existing settlement service twice. The first pass added exactly four
  missing evaluation rows (`159 -> 163`); the second pass left the count and
  all four payload hashes unchanged.
- Production automation had settled three additional bets after the original
  audit, so the final ledger contains 50 settled bets: ChatGPT 41 and DeepSeek
  9. Financial counts were not forced back to the stale 47-row snapshot.
- Full row counts and hashes for `bets`, `bet_executions`,
  `bankroll_transactions`, and `simulation_accounts` were identical before,
  after, and after the idempotency pass.
- Final prediction samples are ChatGPT 121 and DeepSeek 42; each of the four
  target prediction IDs has exactly one settlement row.

## Test Results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Two new regressions on old code | 2 targeted failures | 2 failed at intended assertions | pass |
| Core settlement/P1/P15 suites | All directly affected contracts pass | 23 passed, 1 existing warning | pass |
| Strategy leaderboard route | Existing response contract passes | 1 passed, 1 existing warning | pass |
| Bankroll suite | Existing account behavior passes | 24 passed | pass |
| Portfolio suite, isolated temp | Existing selection/risk behavior passes | 23 passed | pass |
| Python compile | Changed source and tests compile | Passed | pass |
| Diff check | No whitespace errors | Passed with line-ending warnings only | pass |

## Error Log

| Error | Attempt | Resolution |
|---|---:|---|
| Windows locked a shared pytest SQLite temp file during parallel suites | 1 | Re-run portfolio tests alone with isolated `--basetemp` |
| WSL Bash could not run the Windows Workbench deploy script | 1 | Use Git for Windows Bash |

## Reboot Check

| Question | Answer |
|---|---|
| Where am I? | Complete |
| Where am I going? | No remaining task phase |
| What's the goal? | Make financial and provider status reporting match production truth |
| What have I learned? | See `findings.md` and the production audit above |
| What have I done? | Implemented, tested, pushed, deployed, reconciled, and production-verified the repair |
