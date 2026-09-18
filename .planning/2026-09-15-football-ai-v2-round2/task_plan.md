# Football AI v2 Round 2 Plan

## Goal

Implement only P0 Data Integrity, point-in-time Feature Snapshot, append-only Prediction Revision History, freeze/retention protection, reproducibility, and LeakageAuditService on top of the existing P0-P17 system.

## Approved Design

- Increment existing repository/schema and prediction flow; no parallel data system.
- Persist immutable feature snapshots/values, prediction revisions, and leakage audit results.
- Every feature value carries `available_at` and `prediction_cutoff_at`; violations reject production eligibility and are audited.
- Keep the current prediction table as the serving/operational surface while revisions form the permanent audit chain.
- Retention must preserve predictions/evidence/features/revisions used by the audit chain.

## Phases

### Phase 1: Inspect contracts and migration surface
- Status: complete
- Map feature construction, rolling form, prediction save/freeze, retention dependencies, schema initialization, APIs, and tests.

### Phase 2: Feature integrity and leakage audit
- Status: complete
- Add per-feature metadata, strict time checks, rolling windows, persistence, and LeakageAuditService.

### Phase 3: Prediction revisions and retention protection
- Status: complete
- Add append-only revision persistence, reproducibility references, freeze/live isolation, and safe retention behavior.

### Phase 4: Tests and integration
- Status: complete
- Added the requested focused tests plus repository audit-chain and forged-PASS regression coverage; related unit/integration suites are green.

### Phase 5: Report and final verification
- Status: complete
- Wrote `docs/AI_ROUND2_REPORT.md`; final full suite, compile, migration checks, diff check, and scope review passed.

## Scope Exclusions

- No XGBoost, Transformer, new ML model, LLM refactor, large UI change, or Live Prediction implementation.
- No production deployment, commit, or push unless separately requested.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Revision/retention audit sub-agent hit HTTP 429 | 1 | Continue the audit in the primary thread; no implementation impact. |
| Project `.venv` points to a missing Python 3.12 executable | 1 | Use the bundled workspace Python for syntax/tests; do not mutate dependencies. |
| Initial focused test run: one stale 3-tuple unpack and protected system pytest temp dir | 1 | Fixed the tuple unpack; rerun with a unique workspace `--basetemp` and cache disabled. |
| Expanded integration run found an obsolete post-kickoff API expectation | 1 | Updated the old contract test: all pre-match writes after kickoff return 409. |
| Dual-model integration rejected observed lineup/H2H fields without provider timestamps | 1 | Use the immutable evidence snapshot cutoff as the observation-time fallback; explicit source timestamps still take precedence and referenced snapshots are independently audited. |
| Session catch-up found an older Claude transcript but failed while printing a Unicode check mark under Windows GBK | 1 | Treat the transcript as unavailable; recover from the actual Round 2 plan files, handoff summary, and current git diff instead. |
