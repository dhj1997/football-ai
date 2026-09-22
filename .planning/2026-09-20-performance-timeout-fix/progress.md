# Progress

## 2026-09-20

- Reproduced the production error in a real browser.
- Timed every performance-dashboard endpoint through the public proxy and the
  internal FastAPI listener.
- Confirmed N+1 bet reads, duplicate decision requests, eager P6 recomputation,
  and the four-second proxy deadline.
- Wrote and reviewed the scoped repair design; implementation started.
- Added batch bet lookup, reused the latest persisted model evaluation, removed
  the duplicate decision request, and scoped the report-read proxy fallback.
- Focused API tests passed: 5 passed. Python compilation, focused ESLint,
  TypeScript no-emit, and whitespace validation also passed.
- Added a regression assertion that fails if the decision route performs a
  single-prediction bet read. The focused suite still passed 5 tests.
- The final Next.js production build passed.
- Committed the implementation as `12704d5` and pushed GitHub `main`.
- The first deployment wrapper stopped before running the script because
  PowerShell could not resolve `head`; retrying with the pipe inside Git Bash.
- Deployment completed from `12704d5`: MySQL backup/restore verification passed
  for 41 tables, the Web build passed, and both systemd services restarted.
- Production timings after deployment: decisions `200` in 2.65s/3.71s,
  strategy `200` in 0.34s, backtest `200` in 3.08s, model evaluation `200` in
  1.56s, and `/performance` `200` in 0.12s.
- Browser QA showed the populated model-review dashboard with no timeout error.
  Server-normalized hashes for all four changed runtime files match `HEAD`.
- Updated `/opt/football-ai/app/.deploy-revision` to `12704d5` after hash
  verification. Restored the build-generated `next-env.d.ts` change.

## 2026-09-21 Recurrence

- Reproduced the production dashboard alert in a browser.
- Isolated the top-level 504 to `/api/decisions?model=all`; strategy performance
  remained fast, while backtest and model evaluation correctly used their
  longer report deadlines.
- Confirmed the remaining N+1 path for predictions without linked bets.
- Concurrent diagnosis amplified the existing backlog until API, MySQL, SSH,
  and Workbench stopped responding. No database or code writes were made.
- The user restarted ECS. Public root and health recovered to HTTP 200.
- Phase 7 started: add a no-bet regression, eliminate the second lookup, and
  give the decision report the existing bounded report-read timeout.
- Added the focused no-bet regression. Red-light verification failed at the
  expected `bet_for_prediction` call inside `execution_for_prediction`, proving
  the residual N+1 path before implementation.
- Added an explicit `bet_lookup_complete` boundary to the single- and
  multi-model execution views. The decision report now passes the known no-bet
  result from its batch query and performs no second repository read.
- Added `api/decisions` to the existing 30-second GET-only report-read set;
  ordinary proxy traffic remains on the four-second deadline.
- Initial backend/frontend verification processes completed, but their output
  was lost when the command wrapper yielded after 30 seconds. Re-running the
  smallest named checks with retained session IDs before treating them as pass.
- Focused backend verification passed: 4 tests covering no-bet batching,
  linked-bet mismatch reporting, placed-bet execution views, and frozen
  execution views.
- Focused route ESLint produced no errors. `npx --no-install tsc --noEmit`
  resolved to a global placeholder package and printed a false-success warning;
  use the repository's actual TypeScript binary for the real type check.
- Repository-local ESLint and TypeScript binaries both passed. Changed Python
  sources compiled successfully, and `git diff --check` reported no whitespace
  errors beyond existing line-ending warnings.
- After the server restart, resumed from the scoped plan and reviewed the final
  four-file diff. The planning catchup helper found older unsynced context but
  could not print it in the Windows GBK console because it contained a Unicode
  check mark; no project files were changed by that helper.
- Final focused verification passed after the formatting patch: four selected
  regression functions expanded to 12 passing cases. The route ESLint check,
  repository-local TypeScript no-emit check, Python compilation, and
  `git diff --check` all passed.
- Phase 8 is complete. Phase 9 started with a source-only commit planned for
  the four tracked runtime/test files; unrelated planning and temporary files
  remain excluded.
- Committed the four-file fix as `9da2626` and pushed GitHub `main`.
- Deployment backup/restore verification passed for 41 MySQL tables; the
  production Web build passed and both services restarted active. All four
  deployed file hashes match local `HEAD`, and `.deploy-revision` is now the
  full `9da2626` commit.
- Sequential production checks passed: public root, health, and performance
  returned HTTP 200; the all-model decisions report returned HTTP 200 in about
  4.04 seconds through the public proxy.
- Browser QA opened the production performance page and reached its initial
  ledger-loading state without an immediate timeout. The tab object did not
  support `getState()`; reacquire it through `cua.getTab` for the final snapshot.
- Final browser QA completed after reacquiring IAB tab `3` with its string ID.
  The page rendered the full dashboard, 126 decision rows, and 42 simulated
  bets without a backend-timeout alert. Nottingham Forest vs Coventry is shown
  as settled `全输 -90.97`.
- Phase 9 is complete: GitHub, production deployment, service/health/hash
  checks, sequential route timings, and one normal browser load all passed.
- The scoped completion checker reports `ALL PHASES COMPLETE (9/9)` after the
  plan was expressed in its canonical status format.
