# Progress

## 2026-09-20

### Phase 1: Baseline and implementation map
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - User approved the committed specification and authorized implementation.
  - Read the complete `planning-with-files` fallback skill because the required
    `writing-plans` skill is unavailable.
  - Read the previous active plan, findings, progress, and session catch-up.
  - Created this isolated plan without modifying historical plan contents.
  - Confirmed the runtime repository is initialized at API module import and
    mapped the MySQL guard to the pre-construction settings boundary.
  - Mapped player-impact, provider, run persistence, ensemble, admin, proxy,
    backup, and deployment seams to existing code.
  - Found the restore-mismatch exit-code bug and missing pre-deploy DB gate.

### Phase 2: MySQL-only runtime and backup gate
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Started configuration, backup, readiness, and deployment gate changes.
  - Added the pre-repository MySQL runtime assertion and environment-contract
    validation while keeping direct SQLite repositories available to tests.
  - Replaced the SQLite admin backup action with a read-only MySQL verification
    marker status.
  - Made restore mismatch fail closed, added the non-secret marker, and inserted
    the backup/restore gate before deployment extraction.
  - Aligned runtime documentation and examples to MySQL-only non-test use.
  - Deferred execution of the real server backup gate to the mandatory
    pre-deployment step in Phase 8.
- Files created/modified:
  - `apps/api/app/production.py`
  - `apps/api/app/config.py`
  - `apps/api/app/main.py`
  - `apps/api/tests/conftest.py`
  - `apps/api/tests/test_p15_production.py`
  - `apps/api/tests/test_p15_api.py`
  - `deploy/backup-verify.sh`
  - `deploy/deploy.sh`
- Files created/modified:
  - `.planning/.active_plan`
  - `.planning/2026-09-20-mysql-production-activation/task_plan.md`
  - `.planning/2026-09-20-mysql-production-activation/findings.md`
  - `.planning/2026-09-20-mysql-production-activation/progress.md`

## Test Results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Specification `git diff --check` | No whitespace errors | Passed before commit `07b8004` | pass |
| Phase 2 focused API tests | P15 contracts pass | `14 passed, 1 warning` | pass |
| Deployment shell syntax | Both scripts parse | `bash -n` passed | pass |
| Database repository regression | Existing repository behavior preserved | `14 passed` | pass |
| Phase 2 final P15 rerun | Runtime/readiness/backup marker contracts pass | `14 passed, 1 warning` | pass |

### Phase 3: Deterministic player-impact activation
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Started mapping rule payloads to enriched fixture evidence and bounded jobs.
  - Added player-stat snapshot provenance to enriched squad rows.
  - Added content-addressed fixture-scoped absence-rule persistence with
    cutoff/source gates and Chinese display-name normalization.
  - Made the v2 feature consume only the latest matching fixture rule per
    player/impact type.
  - Wired rule generation into prediction context, lineup refresh, player-stat
    refresh, and a bounded automation job.
- Files created/modified:
  - `apps/api/app/player_stats.py`
  - `apps/api/app/player_impact.py`
  - `apps/api/app/feature_engine.py`
  - `apps/api/app/prediction_service.py`
  - `apps/api/app/automation.py`
  - `apps/api/app/config.py`

## Phase 3 Interim Checks

- Python compilation passed.
- Whitespace check passed with expected line-ending warnings only.
- Player impact, player statistics, and Round 3 feature tests passed:
  `26 passed`.
- Automation wiring and existing scheduler behavior passed: `20 passed`.
- Prediction service and dual-model regressions passed: `28 passed, 4 existing warnings`.

### Phase 4: ClubElo and transfer repair
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Started provider timeout/health and upcoming-target repair.
  - Added bounded ClubElo timeout/retry and shared success/failure sync records.
  - Preserved last-good ratings on empty/error responses.
  - Restricted transfer targets to upcoming scheduled fixtures, bounded attempts,
    localized stored/displayed player names, and separated outcome counters.
- Files created/modified:
  - `apps/api/app/clubeelo_provider.py`
  - `apps/api/app/transfers_sync.py`
  - `apps/api/app/automation.py`
  - `apps/api/app/main.py`
  - `apps/api/app/config.py`
  - `apps/api/tests/test_external_data.py`
  - `apps/api/tests/test_discipline_transfers_context.py`

## Phase 4 Checks

- ClubElo/external-data and transfer/context tests passed: `19 passed`.
- Full API source/test compilation passed.

### Phase 5: Backtest, research, and ensemble activation
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Started defining route-level eligibility and reusable ensemble summary logic.
  - Ran the combined Phase 5 research/backtest/ensemble/API suite: `80 passed, 10 failed`.
  - Began isolating changed-contract failures from later shared-state test contamination.
  - Prevented incomplete research, P12, and Round 6 reports from being persisted.
  - Replaced the global ensemble placeholder with bounded real current-fixture summaries.
  - Fixed a route/import name collision in the P12 leakage audit and made zero-sample
    responses report `insufficient_data` without persistence.
  - Updated Round 6 persistence fixtures to satisfy the 30-sample eligibility gate.
- Files created/modified:
  - `apps/api/app/main.py`
  - `apps/api/app/research_engine.py`
  - `apps/api/tests/test_api.py`
  - `apps/api/tests/test_p12_api.py`
  - `apps/api/tests/test_p14_research_engine.py`
  - `apps/api/tests/test_round6_temporal_backtest.py`

## Phase 5 Checks

- Research engine/API: `14 passed`.
- P12 API/engine: `13 passed`.
- Round 6 temporal backtest: `31 passed`.
- Shared API: `32 passed`.
- Full API source/test compilation passed.
- Whitespace check passed with line-ending warnings only.

### Phase 6: Admin operations and explicit demo mode
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Started mapping the existing operations panel, proxy fallback, and production readiness contract.
  - Added a read-only activation-status endpoint covering MySQL/readiness/backup,
    player-impact coverage, provider jobs and telemetry, ensemble availability,
    gate-passing evaluations, and explicit licensed-source gaps.
  - Added `WEB_DEMO_MODE` to settings and the production fail-closed contract.
  - Restricted all web proxy mock/success substitution to explicit server-side
    demo mode; upstream non-2xx responses are now preserved and connection
    failures return categorized 502/504 responses.
  - Extended the existing operations panel with activation metrics and controls
    for ClubElo, transfers, player statistics, player-impact rules, ensemble
    learning, and confirmatory research.
- Files created/modified:
  - `apps/api/app/config.py`
  - `apps/api/app/main.py`
  - `apps/api/app/production.py`
  - `apps/api/tests/test_p15_api.py`
  - `apps/api/tests/test_p15_production.py`
  - `apps/web/src/lib/server-proxy.ts`
  - `apps/web/src/lib/types.ts`
  - `apps/web/src/components/operations-panel.tsx`
  - `apps/web/src/app/api/backend/[...path]/route.ts`
  - `apps/web/src/app/api/admin/*`
  - `.env.example`

## Phase 6 Checks

- P15 API/production tests passed: `15 passed`.
- Web ESLint passed.
- Next.js production build and TypeScript checks passed.

### Phase 7: Focused verification and Git delivery
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Started final focused regression and browser verification.
  - Passed P15 (`15`), automation (`20`), Phase 5 (`58`), and final
    dual/automation/P15 (`46`) focused tests.
  - Passed API compile, Web ESLint, Next production build, both shell syntax
    checks, and staged whitespace validation.
  - Verified `/admin` at 1440px and 390px; fixed the existing mobile date-strip
    overflow and confirmed `scrollWidth == innerWidth == 390`.
  - Verified the player-impact manual action end to end through the Web proxy;
    it returned success and refreshed the operation state.
  - Committed implementation as `a2b4195` and pushed `07b8004..a2b4195` to
    `origin/main`.
- Files created/modified:
  - See commit `a2b4195`.

### Phase 8: Production deployment and verification
- **Status:** in_progress
- **Started:** 2026-09-20
- Actions:
  - Started deployment preflight from pushed HEAD `a2b4195`.
  - Isolated backup-verification temporary artifacts under a unique `mktemp`
    directory with validated, file-scoped cleanup after the first deployment
    attempt encountered fixed `/tmp` files owned by another server user.
  - Committed and pushed the deployment fix as `2ef6df2`.
  - Completed MySQL dump/restore verification: 37 cold tables matched and the
    verification marker was written for `db-20260920-124521.sql.gz`.
  - Deployed and built the application; both services became active. The API
    needed about 11 seconds to finish startup, so the script's 6-second probe
    was transiently early; a follow-up listener/journal check passed.
  - Verified MySQL health, public fixture/ensemble/backtest/research routes,
    internal admin routes, and matching local/remote hashes for four key files.
  - Preserved the intentional Nginx admin-route denylist; operator jobs remain
    callable only through the protected internal API.
  - Ran the four activation jobs. Player statistics were already fresh;
    ClubElo timed out, transfers had no provider IDs, and player-impact exposed
    a real list-vs-mapping context bug that must be fixed before Phase 8 closes.
  - Confirmed the malformed context also causes affected fixture-detail reads
    to return HTTP 500; began inspecting the exact persisted JSON field types.
  - Added read-boundary normalization for legacy Dongqiudi statistic lists;
    existing mapping statistics remain unchanged and unknown list fields are
    ignored without rewriting stored evidence.
  - Passed all player-impact tests (`8 passed`), the focused automation job
    regression (`1 passed`), compilation, and whitespace validation.
  - Committed the compatibility fix as `2f8caa4`; the first GitHub push attempt
    lost its HTTPS connection and left the local branch one commit ahead.
  - A second push and direct GitHub HTTPS probe timed out from the workstation;
    DNS resolves, while the repository proxy is reachable but returns 403 for
    this write path. Continue production validation and retry GitHub later.
  - Hardened the deploy script with a 30-attempt API readiness loop and
    fail-closed API/Web probes; committed it as `7cf092c`.
  - A third HTTPS push reset even though TCP 443 was reachable. SSH-over-443 is
    reachable but this workstation has no GitHub-authorized SSH key, so retain
    the HTTPS origin and continue looking for the existing credentialed route.
  - The Git Data API accepted blobs and an unreferenced test commit, but GitHub
    normalized commit metadata and produced a different SHA; the branch ref was
    deliberately not updated. Inspect the API commit serialization before any
    further write so local and remote history stay aligned.
  - Reproduced the API-created commit SHA locally: GitHub retained the `+0800`
    identity timestamp but serialized the supplied message without a trailing
    newline. This provides a safe path to publish and align both refs/trees.
  - Published the two commits through GitHub's official Git Data API and
    aligned local/remote `main` at `4238035` with identical tree `973d5fd`.
  - The next deployment was stopped before extraction by a three-table
    fingerprint drift while automation wrote during the backup window. Begin
    quiescing the API writer with guaranteed restart cleanup around the gate.
  - Committed/pushed API-write quiescing as `1eb2817`; the next restore matched
    all 41 tables and deployed successfully with API readiness plus Web 200.
  - Re-tested `dongqiudi-54419032`: fixture detail is HTTP 200. The player-impact
    job is now `success/completed` for 32 candidates with no errors, while all
    32 correctly remain `insufficient_data` because source evidence is missing.
  - Ran ensemble learning, confirmatory research, P12 backtest, manual research,
    and Round 6 evaluation. Only Round 6 passed its eligibility gates (11
    fixtures, 230 observations); the other workflows returned truthful draft
    or insufficient results without false persisted success rows.
  - Persisted the eligible Round 6 report as the only real backtest row;
    `round6:0eb512...` is `ok` and non-simulated. Research remains empty.
  - Found and fixed transfer identity resolution by reusing the stored,
    conflict-free API-Football team identity map for both sync and prediction
    evidence attachment. Focused transfer/context tests passed: `10 passed`.
  - Committed/pushed transfer resolution as `3a1a641`, restored/verified all 41
    MySQL tables again, deployed, built, restarted, and passed readiness probes.
  - Production transfer runs resolved 13/18 team appearances and stored 10 team
    snapshots with 8,077 records; three further teams hit HTTP 429 and five lack
    current-season identities. Verified recent evidence attachment directly.
  - Completed final public-route, no-mock, systemd, backup-marker, MySQL-row,
    GitHub SHA, and local/remote hash verification.

### Phase 9: Licensed-source handoff
- **Status:** complete
- **Started:** 2026-09-20
- Actions:
  - Re-audited player value, pre-match news, player absence/injury evidence,
    ClubElo, transfer identity/quota, and confirmatory research coverage.
  - Recorded exact provider records, provenance, licensing, history, identity,
    timestamp, authentication, and quota requirements for user-supplied sources.
- Files created/modified:
  - Planning evidence only; no fabricated provider implementation.
- Files created/modified:
  - `deploy/backup-verify.sh`

## Error Log

| Date | Error | Attempt | Resolution |
|---|---|---:|---|
| 2026-09-20 | Catch-up output could not encode U+2705 using GBK | 1 | Set task-scoped `PYTHONIOENCODING=utf-8` and reran successfully |
| 2026-09-20 | PowerShell/rg rejected a wildcard in the path argument | 1 | Switched to `rg -g 'test_*.py' apps/api/tests` |
| 2026-09-20 | Grouped `rg` expression was malformed by PowerShell quoting | 1 | Used direct file inspection and a simpler targeted patch |
| 2026-09-20 | Documentation scan named a nonexistent API env example | 1 | Switched to the root `.env.example` |
| 2026-09-20 | Player-impact test search reused invalid Windows path globs | 1 | Standardized future test searches on `rg -g` |
| 2026-09-20 | Grouped automation `rg` pattern was malformed by shell quoting | 1 | Use simple single-pattern searches or direct snippets for automation methods |
| 2026-09-20 | Combined findings/test patch did not match one context line | 1 | No partial edit occurred; split into exact small patches |
| 2026-09-20 | Research-test lookup reused Windows wildcard paths | 1 | Replaced with directory search and `-g` filters |
| 2026-09-20 | Phase 5 combined patch had an invalid hunk boundary | 1 | Patch was rejected atomically; split into smaller verified edits |
| 2026-09-20 | Phase 5 focused suite reported 10 failures after 80 passes | 1 | Re-run the affected tests in isolated groups and fix only failures caused by this phase |
| 2026-09-20 | Phase 6 combined config patch missed the `.env.example` anchor | 1 | No partial edit occurred; inspect the exact environment block and apply smaller patches |
| 2026-09-20 | Phase 6 multi-route Web patch had an invalid hunk boundary | 1 | No partial edit occurred; split proxy edits by route group |
| 2026-09-20 | Web lint rejected `load()` inside `useEffect` under `react-hooks/set-state-in-effect` | 1 | Refactor initial load to apply fetched state inside the asynchronous callback |
| 2026-09-20 | Global `agent-browser` command was not installed | 1 | Switch browser QA to the documented `npx agent-browser` invocation |
| 2026-09-20 | Parallel pytest suites raced while cleaning shared `.pytest_tmp` and hit `WinError 32` | 1 | Re-run with isolated per-suite base temp directories |
| 2026-09-20 | Unquoted agent-browser ref was parsed by PowerShell and the wait timed out | 1 | Quote the ref; the failed command did not trigger an operation |
| 2026-09-20 | Live manual player-impact job returned 404 and concurrent activation reads hit a SQLite savepoint error | 1 | Expose the primary context preparation method through `DualPredictionService` and guard migration execution with a process lock |
| 2026-09-20 | First production deploy stopped before extraction because fixed `/tmp/readiness.json` and `/tmp/mysqldump.err` were not writable | 1 | Switch backup verification to a unique `mktemp -d` workspace; no production code was changed |
| 2026-09-20 | A quoted Git Bash diagnostic command failed before contacting the server | 1 | Re-ran the bounded Workbench diagnostic from PowerShell with a single remote command argument |
| 2026-09-20 | Post-restart API probe ran before the 11-second startup completed | 1 | Confirmed service/listener health after startup; assess a bounded readiness wait in the deployment script |
| 2026-09-20 | GitHub HTTPS connection reset while pushing `2f8caa4` | 1 | Retry the same non-destructive push and verify the remote branch SHA |
| 2026-09-20 | GitHub HTTPS push reset again; SSH-over-443 rejected the local key | 3 | Keep official HTTPS origin and inspect available local proxy/network paths without exposing credentials |
| 2026-09-20 | Git Data API commit SHA differed from the local commit SHA | 1 | Leave `main` untouched; compare commit metadata and reproduce GitHub's exact serialization locally before updating the ref |
| 2026-09-20 | Restore fingerprint drifted by one row in three automation-written tables | 1 | Stop the API writer during dump/restore comparison and restart it from the cleanup trap on every exit |

## Reboot Check

| Question | Answer |
|---|---|
| Where am I? | Phase 1 baseline mapping |
| Where am I going? | MySQL boundary through deployment, then licensed-source handoff |
| What is the goal? | Complete and deploy every non-blocked activation item |
| What have I learned? | See `findings.md` |
| What have I done? | See this log |
