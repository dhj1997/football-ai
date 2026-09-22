# Progress

## 2026-09-20

- User approved approach A: values are evidence/context, with no new formula.
- Updated and committed the design as `8e8bd8d`.
- Confirmed the sample Dongqiudi player endpoint and historical value shape.
- Started Phase 1 contract inspection.
- Confirmed that provider, roster identity, MySQL payload storage, and existing
  web fields can be extended without a second value subsystem.
- Located the reusable automation job lifecycle, upcoming squad cache, manual
  job route, and activation-status composition.
- Completed cutoff and canonical-player identity tracing.
- First provider rewrite patch was rejected before any file change because it
  combined delete and add operations for one path; switching patch shape.
- Implemented the provider/parser, cache-only enrichment, merged MySQL history,
  cutoff selection, bounded sync, automation wiring, activation telemetry, and
  existing UI source/date copy.
- Focused first pass: 9 tests passed with one third-party deprecation warning.
- Automation and prediction regression: 38 tests passed with four existing
  pytest marker warnings; Python compileall and git diff check passed.
- `npm exec eslint` stalled without output and was stopped; switching to the
  local executable.
- Corrected an over-broad test patch before running the affected suite.
- Re-run after the test fix: 10 targeted tests passed; live provider parsing
  also matched the expected Chinese name and latest dated value.
- Added transport-stop coverage; 11 targeted tests passed. Removed the final
  obsolete `redisplay_authorized` frontend field found by the authorization scan.
- Python compileall, focused ESLint, TypeScript no-emit, git diff check, and the
  Next production build passed on the final code shape.
- Committed implementation as `7d47b77`; first GitHub push failed due to a
  reset/unreachable `github.com:443` connection.
- Pushed design and implementation commits to GitHub `main`; remote HEAD is
  `7d47b77`.
- Production preflight confirmed deployed `b265aa7`, active API/Web, and MySQL.
  The first backup attempt exited before quiescing due to CRLF shell line endings.
- Second backup command failed in local Workbench argument parsing before remote
  execution; simplified the quoting for the next attempt.
- Completed the production MySQL backup, restore verification, application
  deployment, bounded value backfill, and cached squad-identity repair.
- Pushed final `main` revision `7b53f84` to GitHub and confirmed the production
  `.deploy-revision` matches it exactly.
- Verified API/Web services active, MySQL health, four public routes, and the
  deployed key-file contents after normalizing the server's CRLF line endings.
- Browser QA confirmed the home fixture queue, standings, and the real
  `dongqiudi-54493261` squad panel with 51/51 values, Dongqiudi source labels,
  dates, and Chinese player names. Phase 6 is complete.
