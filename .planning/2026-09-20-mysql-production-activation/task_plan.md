# MySQL Production Activation

## Goal

Make MySQL the only non-test database, connect and operate every non-blocked
existing feature, deploy the verified changes to production, then isolate the
licensed player-value and pre-match-news sources as the final user-supplied
dependency.

## Current Phase

Complete

## Phases

### Phase 1: Baseline and implementation map
- Confirm the committed specification, worktree boundary, runtime contracts,
  focused tests, and production deployment path.
- Record exact modules and existing behavior before edits.
- **Status:** complete

### Phase 2: MySQL-only runtime and backup gate
- Reject SQLite application startup outside `ENVIRONMENT=test`.
- Align readiness, backup behavior, documentation, and focused tests with MySQL.
- Implement the fail-closed server-side MySQL dump/restore gate; execute and
  verify it immediately before deployment in Phase 8.
- **Status:** complete

### Phase 3: Deterministic player-impact activation
- Generate versioned cutoff-safe rules from existing player statistics,
  lineups, and availability evidence.
- Trigger bounded generation and expose coverage/readiness.
- Preserve Chinese-name normalization for every displayed/logged player.
- **Status:** complete

### Phase 4: ClubElo and transfer repair
- Preserve last-good ClubElo data and record truthful health failures.
- Target upcoming teams by real provider identity and distinguish empty/failure
  outcomes for transfers.
- **Status:** complete

### Phase 5: Backtest, research, and ensemble activation
- Persist only gate-passing backtest/research runs.
- Replace the global ensemble placeholder with real bounded summaries.
- Keep strict no-ML and immutable prediction boundaries.
- **Status:** complete

### Phase 6: Admin operations and explicit demo mode
- Add a compact operational status/action surface to the existing admin page.
- Restrict mock proxy fallback to `WEB_DEMO_MODE=true` and expose real errors.
- **Status:** complete

### Phase 7: Focused verification and Git delivery
- Run directly relevant API/web tests, compile/type/build checks as warranted,
  and whitespace review.
- Review the diff, commit scoped changes, and push tracked commits to GitHub.
- **Status:** complete

### Phase 8: Production deployment and verification
- Back up and restore-verify MySQL, deploy tracked HEAD, run migrations/builds,
  and restart services.
- Verify systemd services, public routes, deployed hashes, and MySQL results.
- **Status:** complete

### Phase 9: Licensed-source handoff
- Re-audit player-value and pre-match-news requirements against existing sources.
- If still insufficient, provide the exact provider contract and credentials the
  user must supply; do not fabricate data or block Phases 1-8.
- **Status:** complete

## Decisions Made

| Decision | Rationale |
|---|---|
| Use committed spec `07b8004` as scope | User approved the written design with “开始吧” |
| Use an isolated `.planning` directory | Preserve prior completed plans and avoid context mixing |
| Keep SQLite repository support only for tests | Matches the approved database boundary |
| Defer player value and news until Phase 9 | User requested all other work first and authorized sources last |
| Use narrow tests per phase | Project instructions prohibit over-testing |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `session-catchup.py` failed encoding U+2705 under Windows GBK | 1 | Re-ran with `PYTHONIOENCODING=utf-8`; catch-up completed |
| `rg` path glob `apps/api/tests/test_*.py` is invalid on Windows | 1 | Use an `rg -g` include pattern against the directory |
| A follow-up `rg` regex was malformed by PowerShell quoting | 1 | Stop using grouped regex for this lookup; inspect the known P15 files directly |
| Phase 5 focused suite reported 10 failures after 80 passes | 1 | Isolate the six changed-contract tests from four likely shared-state regressions, then fix only current-change causes |
| Phase 6 combined config patch missed the `.env.example` anchor | 1 | Patch was rejected atomically; inspect the exact variable block and split the patch |
| Phase 6 multi-route Web patch had an invalid hunk boundary | 1 | Patch was rejected atomically; apply route changes in small groups |
| Web lint rejected synchronous state updates through `load()` inside `useEffect` | 1 | Separate the stateless fetch from state application and update only in Promise callbacks |
| Global `agent-browser` command is unavailable | 1 | Use the skill-documented `npx agent-browser` fallback |
| Parallel pytest groups shared `.pytest_tmp` and hit Windows `WinError 32` on `jobs.db` | 1 | Give each suite a unique `--basetemp`; do not reuse or delete the locked directory |
| PowerShell consumed unquoted agent-browser ref `@e37` | 1 | Quote accessibility refs in PowerShell; no job was triggered by the failed attempt |
| Browser QA found `player_impact_rules` absent from the live runner and activation dry-run savepoint contention | 1 | Delegate `prepare_context` through the dual service and serialize migration execution in-process |
| Production pre-deploy backup could not overwrite fixed `/tmp` files owned by another user | 1 | Deployment stopped before extraction; use an isolated `mktemp -d` workspace with cleanup trap |
| Production player-impact job failed on Dongqiudi fixture context lists | 1 | Trace the stored evidence shape, normalize the legacy list form at the enrichment boundary, and rerun focused tests plus the production job |
| Documentation scan referenced missing `apps/api/.env.example` | 1 | Limit environment documentation edits to root `.env.example` |
| Player-impact `rg` used wildcard path arguments on Windows | 1 | Use `rg -g` include filters against `apps/api/tests` |
| Grouped automation `rg` expression was malformed | 1 | Replace it with simple literal searches and direct reads |
| Combined automation-test patch failed context verification | 1 | Split the patch and use exact inspected anchors |
| Research-test search used wildcard path arguments on Windows | 1 | Search the tests directory with `-g` filters |
| Multi-file Phase 5 patch had an invalid hunk boundary | 1 | No files changed; split research, backtest, and ensemble patches |

## Hard Boundaries

- Preserve unrelated `.tmp/` and user changes.
- No broad refactor, fabricated evidence, learned ML activation, real-money
  betting, or licensed-source substitution.
- Cap potentially large command output near 4,000 bytes.
- Do not claim deployment from local tests; verify services, routes, hashes, and
  database results independently.
- All API/page/log player names pass through `to_chinese_player_name`.
