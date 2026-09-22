# Progress

## 2026-09-20

- User approved方案 A and then approved implementation.
- Committed the reviewed design as `6dbdc9a`.
- Re-read the prior completed MySQL activation plan without modifying it.
- Inspected provider, transfer storage, Elo, research automation, activation
  status, and focused test contracts.
- Started Phase 1.
- Added Dongqiudi player-detail transfer mapping with bounded, paced roster
  traversal and Chinese-name normalization.
- Added provider-namespaced transfer snapshots, Dongqiudi-first target
  resolution, API-Football fallback, and prediction-time source-aware reads.
- Focused provider/transfer tests pass: `41 passed`.
- Completed Phase 1 and started Phase 2.
- First Elo-focused run passed 37 tests and failed only because the new test
  fixture omitted repository-required `fixture_date`; corrected the fixture.
- Elo provenance verification passed: `38 passed`.
- Completed Phase 2 and started Phase 3.
- Added parameterized research thresholds and separated direct paired
  LLM-vs-Poisson evaluation from rolling-window eligibility.
- Added a distinct 20-29 sample exploratory automation job while retaining the
  30-sample Football-Data confirmatory job.
- Exposed exploratory and confirmatory archive counts separately in the
  activation API and operations panel.
- Focused research, automation, and activation tests passed: `33 passed`.
- Diff review found that job pre-checks counted all prediction rows rather than
  actual LLM/Poisson pairs; changed both jobs to use the comparison sample
  counter and added threshold-floor coverage.
- Research threshold verification passed after the correction: `34 passed`.
- Combined affected API suite passed: `113 passed, 1 warning`.
- Web ESLint and API `compileall` both passed.
- Completed Phase 3 and started the delivery review in Phase 4.
- Delivery review found future finished fixtures could appear in local Elo
  provenance IDs even though they were excluded from the rating; aligned IDs
  to the same cutoff filter.
- Added partial Dongqiudi player-detail diagnostics so validated transfers are
  retained while failures are counted; rate limits and transport failures stop
  further player requests in the bounded team fetch.
- Final affected API suite passed after review fixes: `114 passed, 1 warning`.
- API `compileall`, Web ESLint, and `git diff --check` passed.
- Completed Phase 4 and started scoped commit/deploy work in Phase 5.
- Committed implementation as `b265aa7` and pushed both pending commits to
  GitHub `main`; remote `refs/heads/main` resolves to the same full SHA.
- Production MySQL backup/restore gate passed against 41 tables; backup is
  `/opt/football-ai/backups/db-20260920-153704.sql.gz`.
- Deployed the tracked `HEAD` archive with an application backup at
  `/opt/football-ai/backups/app-20260920-before-b265aa7.tar.gz`.
- Server Next.js build and TypeScript checks passed; API/Web are active and
  deployed revision is `b265aa750209ba9ee5403a4a956c47c22fc1ce93`.
- Public `/`, `/standings`, `/api/backend/health`, and today's fixture route
  return HTTP 200; archive hashes match the deployed key files.
- Production transfer job saved 256 records across six Dongqiudi snapshots:
  161/161 player details fetched, zero failures, zero fallback calls.
- Exploratory job reported 100 all-source pairs and correctly skipped the
  20-29 early archive; FD confirmatory research remains `0/30`, so no research
  archive was fabricated. Activation reports exploratory/confirmatory `0/0`.
- Phase 5 complete.
