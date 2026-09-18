# Football AI v2 Round 6.5 Production Evidence Hardening

## Goal

Make every newly persisted Round 5 production probability auditable as a
pre-match production revision with real persistence timing and complete links
to fixture, cutoff, feature snapshot, odds snapshot, and leakage audit. Keep
Round 6 strict and preserve all existing Round 1-6 behavior and user changes.

## Phases

### Phase 1: Repository and contract audit
**Status:** complete
- Map the actual Round 5 calculation and persistence path.
- Inventory timestamps, revision IDs, feature/odds/audit links, schemas, and
  kickoff-freeze behavior.
- Confirm whether existing fields are sufficient; do not assume a migration.

### Phase 2: Minimal evidence design
**Status:** complete
- Select one canonical production evidence contract and validation function.
- Define atomic/ idempotent behavior for MODEL_ONLY and MODEL_PLUS_MARKET.
- Record the decision in the scoped findings and design document.

### Phase 3: Production-path implementation
**Status:** complete
- Add the smallest automatic evidence persistence hardening to the real
  Round 5 production path.
- Reuse the existing prediction revision, snapshot, and audit stores.
- Keep old records nullable/unmodified and reject incomplete new evidence.

### Phase 4: Focused verification
**Status:** complete
- Add approximately 10-15 focused tests covering timestamps, links,
  cutoff/leakage, append-only behavior, idempotency, kickoff freeze, and both
  market modes.
- Run only relevant Round 4/5/6 regressions.

### Phase 5: Real-data validation and report
**Status:** complete
- Perform a minimal read-only real MySQL inspection and isolated SQLite write
  smoke test; never contaminate production history.
- Write `docs/AI_ROUND6_5_REPORT.md` with truthful limitations and Round 6
  compatibility.
- Run compileall, diff checks, final review, and mark all phases complete.

## Hard Boundaries

- No ML, fitting, calibration, optimization, betting, or formula changes.
- Do not relax Round 6 eligibility or backfill historical timestamps.
- Do not create a second revision, audit, feature, odds, or backtest store.
- No commit, push, deploy, or writes to the real production database.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Focused atomic-writer test used a forged evidence SHA-256 | 1 | Compute the fixture hash from the canonical JSON payload |
| Direct SQLAlchemy MySQL URL selected missing `MySQLdb` driver | 1 | Use `PredictionRepository` URL normalization to select existing PyMySQL driver without initialization |
| Two P15 migration tests expected the migration list to stop at `0006` | 1 | Include `0007` and assert its nullable `persisted_at` column contract |
| First SQLite smoke reused an intentionally minimal writer fixture that Round 4 rejected | 1 | Use the real Round 3 Feature Engine to build complete deterministic inputs; dispose the SQLite engine before cleanup |
| Planning catch-up could not launch the removed base Python interpreter behind the project venv | 1 | Restore context from the scoped plan files and current git diff; use an available Python launcher for verification |
| Real dual-model integration fixture omitted repository-required `fixture_date` | 1 | Derive `fixture_date` from each historical fixture kickoff before upsert |
| Final review found a transaction could cross kickoff after assigning `persisted_at` | 1 | Recheck UTC after the final market insert and roll back the transaction at/after kickoff |
| Exact temporary review database cleanup was rejected by the approval backend because its configured reviewer model was unavailable | 1 | Preserve the isolated ignored file, do not bypass approval, and report its exact path |
| Final review found the writer trusted the caller kickoff instead of the persisted fixture | 1 | Load kickoff inside the transaction and require the caller value to match exactly |
| Application wall-clock validation necessarily occurs before the database commit completes | 1 | Keep the post-insert fail-closed check and document that `persisted_at` is an in-transaction write timestamp, not a database commit timestamp |
| Dual-model SQLite integration built the target fixture but persisted only its history rows | 1 | Persist the target fixture with a kickoff-aligned `fixture_date` before exercising the real production transaction |
| Final regression printed Windows `0x800703e5` during Python platform metadata probing | 1 | Pytest continued and completed 114/114; record as non-fatal runtime noise rather than retrying an already verified suite |
| A combined patch placed the test fixture hunk under the database file | 1 | Patch verification rejected the entire operation; split code and test operations before retrying |
| Resumed read-only checks could not launch because the runner was not ready | 1 | Reestablish a terminal with a bounded `Get-Location` check before continuing |
| Final file inventory included nonexistent `apps/api/scripts` | 1 | Limit inventory to the existing app, tests, docs, and scoped planning paths |

## Decisions

- Treat the user-provided Round 6.5 execution prompt as the approved scope.
- Prefer existing `created_at`/revision timestamps only when their semantics
  are verified; otherwise add at most one minimal nullable field.
- New production evidence must fail closed when any required provenance is
  absent or temporally invalid.
