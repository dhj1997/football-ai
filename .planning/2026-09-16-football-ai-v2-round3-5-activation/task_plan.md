# Football AI v2 Round 3.5 Activation

## Goal

Activate and validate the existing Feature Engine v2 against the configured real MySQL database without adding features, formulas, prediction models, or unrelated changes.

## Phases

### Phase 1: Read-only database and activation audit
**Status:** complete
- Confirm migration state, current rows, candidate fixtures, and the exact existing activation entry points without exposing credentials.

### Phase 2: Apply migration and activate a bounded sample
**Status:** complete
- Apply `0006-round3-feature-engine` idempotently and generate Feature Engine v2 data for the smallest useful recent real-data sample.

### Phase 3: Validate storage, leakage, API, and coverage
**Status:** complete
- Verify append-only history, cutoff safety, reproducibility, one persisted explanation response, and truthful coverage.

### Phase 4: Report and minimal verification
**Status:** complete
- Write the activation report; run only Round 3 tests, compileall, and `git diff --check`; stop before Round 4.

## Scope

- No new feature, formula, prediction logic, ML, Poisson, Dixon-Coles, Market Prior, fusion, backtest, UI, commit, or deployment.
- Preserve all existing dirty-worktree changes.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Windows rejected the `apps/api/app/*.py` path passed to `rg` | 1 | Search the directory with `-g '*.py'` instead; no files were changed. |
| Read-only DB audit referenced nonexistent `Settings.competition_id` | 1 | Construct `PredictionRepository` with its defaults; the failed attempt performed no writes. |
| `session-catchup.py` failed while printing prior context under Windows GBK | 1 | Continued from the supplied handoff summary and current plan/database state; no activation command was repeated. |

## Completion Evidence

- Read-only MySQL checks: 0006 applied; 62 registry definitions; 4 snapshots; 448 values; 4 PASS audits; 0 time-boundary violations; 0 null quality scores.
- Latest-per-fixture coverage: 3 LALIGA fixtures, 6 teams, 336 rows; coverage report regenerated with group, feature, status, and missing-reason statistics.
- Explanation API: `GET /match/sportsdb-2506220/features` returned 200 with 112 persisted features and PASS audit; validation observed SELECT-only database access and no automation lifespan.
- Minimal verification: `15 passed`, `compileall` passed, and `git diff --check` passed.
- Stopped before Round 4; no commit, push, deployment, or destructive rollback.
