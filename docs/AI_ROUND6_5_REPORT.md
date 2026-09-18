# Football AI v2 Round 6.5 Report

Date: 2026-09-18

Round 6.5 adds production evidence infrastructure. It does not change any
prediction formula, market weight, calibration rule, or betting behavior.

## 1. Objective

Make every newly persisted Round 5 production probability independently
auditable as a real pre-match prediction revision. The evidence chain must
identify the fixture, cutoff, kickoff, feature snapshot, optional odds
snapshots, leakage audit, probability layers, revision, and the production
write-attempt time captured inside the final transaction.

## 2. Problem from Round 6

Round 6 correctly returned `insufficient_data`. Existing Round 5 audit rows did
not independently prove when a production write was attempted or which
prediction revision produced them. Their logical cutoff timestamps could not
be treated as production persistence evidence.

Round 6.5 does not loosen that rule. Legacy rows remain unverified.

## 3. Production Evidence Definition

`production_evidence_valid=true` is accepted only when the deterministic
validator proves all required identities, timestamps, probabilities, and
provenance. The record also carries
`evidence_kind=production_prediction` and the version
`round6.5-production-evidence-v1`.

Replay records, incomplete records, invalid probability vectors, and records
without an exact PASS leakage audit fail closed.

## 4. Timestamp Semantics

The four time classes remain distinct:

- `kickoff_at` is event time;
- feature `available_at` and odds `captured_at`/`source_updated_at` are data
  availability times;
- `prediction_cutoff_at` is the immutable model input boundary;
- `market_snapshots.persisted_at` is the application UTC wall-clock time
  assigned by the repository inside the final database transaction,
  immediately before evidence validation and insertion. It is not a database
  commit-completion timestamp.

A valid record requires
`prediction_cutoff_at <= persisted_at < kickoff_at`, while the cutoff itself
must be strictly before kickoff. After the market row is inserted, the
transaction checks the UTC clock again and rolls back all three new rows if
the application-side write path has reached or crossed kickoff before control
returns to the transaction manager. The new column is nullable so old records
remain NULL. No historical timestamp is inferred or backfilled.

## 5. Prediction Revision Association

The existing `prediction_revisions` table remains authoritative. Round 6.5
uses its stable composite identity:

```text
prediction_id:revision_number
```

The repository allocates or reuses the immutable revision in the same final
transaction and embeds this identity in the Round 5 evidence. The API response
may expose `prediction_revision_id` and `round5_market_snapshot_id` after the
transaction, but those response-only fields are not written back into the
already persisted prediction payload.

For a first evidence write, the writer also reads the persisted `fixtures` row
in that transaction, locks it with `FOR UPDATE` on MySQL, requires its status
to remain `scheduled`, and requires its kickoff to equal the caller's kickoff.
A stale or forged later caller timestamp therefore cannot extend the
production window. Identical retries look up existing evidence first and do
not reapply mutable fixture status or rescheduling gates.

This revision is the serving-prediction revision. Its persisted probability
vector must match the Round 5 evidence's `model_probability`. The Round 5
evidence remains the authoritative record for the complete model, market, and
final probability layers; no second probability revision is introduced.
Both probability model/calculation versions must also match the audit before
the writer opens the transaction, and Round 6 cross-checks the stored values.

## 6. Feature Provenance

The real prediction path runs the unchanged Round 4
`TransparentProbabilityEngine` from the persisted Round 3 feature snapshot.
The writer verifies that the feature snapshot exists and matches the revision
fixture, cutoff, version, and identifier. Every non-missing feature must have
`available_at <= prediction_cutoff_at`.

No parallel feature store was added.

## 7. Odds Provenance

The real prediction path reads existing immutable odds snapshots for the
fixture and passes them to the unchanged Round 5 engine. Round 5 performs its
existing cutoff filtering.

`MODEL_PLUS_MARKET` evidence must reference every selected odds snapshot and
prove both capture and provider-update times are no later than the cutoff.
`MODEL_ONLY` evidence must contain neither source odds IDs nor a market
probability.

## 8. Leakage Audit

The leakage audit is created append-only when the feature snapshot is audited.
The final production transaction loads the exact `leakage_audit_id`, verifies
its prediction, feature snapshot, cutoff, and PASS status, and links it to the
Round 5 evidence. It does not create or overwrite a second audit row.

FAIL, WARN, UNKNOWN, missing, or mismatched audit evidence cannot become valid
production evidence.

## 9. Append-only Behavior

Predictions, revisions, feature snapshots, odds snapshots, leakage audits, and
Round 5 evidence retain their existing immutable behavior. The change does not
update old revisions, rewrite old audits, delete history, or synthesize missing
provenance.

## 10. Concurrency and Idempotency

The final repository transaction inserts the prediction, allocates the
revision, verifies immutable prerequisites, and inserts the production Round 5
snapshot. Any failure rolls back the prediction, revision, and market evidence
together.

The production snapshot ID is derived from the immutable revision identity and
excludes the physical `persisted_at`. Retrying the same revision with identical
content returns the original row and persistence time. A changed payload for
that revision is rejected as immutable, even under concurrent writes.
An identical retry received after kickoff, a live/finished status change, or
rescheduling may return the already committed row carrying its original
pre-kickoff `persisted_at`; it cannot create a new row or change its
timestamp/content. Bounded retries handle unique-key competition across the
prediction, revision, and market-evidence tables; NOT NULL, CHECK, and foreign
key failures are not retried.

## 11. Historical Data Handling

Existing Round 5 rows are not backfilled. A NULL `persisted_at`, missing
revision identity, replay marker, or incomplete provenance remains excluded by
Round 6. The migration only adds a nullable column; it does not update data.

## 12. Production Path

`PredictionService._save_current()` now automatically calculates the unchanged
Round 4 and Round 5 layers from persisted inputs and invokes the atomic
production evidence writer. No second manual evidence endpoint is required.

Historical replay repositories continue through their existing revision write
barrier and never call the production evidence writer. The kickoff freeze is
checked before the final call, at the repository timestamp boundary, and once
more after the final insert. If the application-side post-insert check reaches
kickoff, all new rows are rolled back before the transaction manager commits.
This does not prove when COMMIT completes.

For the existing dual-model fan-out, one primary service owns the shared,
provider-independent Round 4/5 production evidence. Both provider-specific
prediction revisions are still retained, but they no longer create duplicate
Round 5 evidence for one fixture/cutoff.

If both teams lack every critical Round 4 feature, the normal prediction
revision remains available and the response marks production evidence
unavailable. No Round 5 record is created. Once a valid Round 4/5 result exists,
any evidence validation or atomic writer failure remains fail-closed with no
legacy fallback.

## 13. Validation

Focused coverage includes MODEL_ONLY and MODEL_PLUS_MARKET, real persistence
time, revision and audit associations, feature and odds cutoff safety, replay
rejection, PASS/FAIL/WARN/UNKNOWN behavior, historical NULL preservation,
idempotency, transaction rollback, kickoff boundary rejection, and a
write whose application-side post-insert clock check reaches kickoff. Final
hardening cases also cover retries after fixture changes, missing/tampered
probability versions, and non-unique integrity errors.

Results:

- latest run after the final hardening patches: `98 passed, 1 warning` in
  114.95 seconds, with `-q -p no:cacheprovider`, covering:
  `tests/test_round6_5_production_evidence.py`,
  `tests/test_round6_temporal_backtest.py`,
  `tests/test_prediction_service.py::test_real_dual_prediction_persists_two_revisions_and_one_round5_evidence`,
  and `tests/test_round2_repository.py`;
- previously completed Round 2 repository + Round 4 + Round 5 + production
  migration regression: `61 passed`; this is an earlier result, not the final
  post-hardening run;
- real dual-model SQLite integration: two provider revisions and exactly one
  shared Round 5 production evidence row, with revision/model-probability
  equality;
- isolated SQLite end-to-end smoke: one prediction, one revision, and one
  production market snapshot with a real timestamp and PASS audit;
- `compileall`: passed;
- `git diff --check`: passed, with only existing Windows LF/CRLF warnings.

The latest run completed without the transient Windows platform-probe stack
seen in an earlier run. Its only warning was the existing Starlette TestClient
`httpx` deprecation. No full suite or large historical backtest was rerun.

## 14. Real MySQL Validation

A read-only connection to the configured real MySQL database was used. No
initialization, migration, insert, update, or delete was executed.

Observed state on 2026-09-18:

- `market_snapshots`: 0 rows and no deployed `persisted_at` column;
- `prediction_revisions`: 0 rows;
- `leakage_audits`: 4 rows;
- `feature_snapshots`: 4 rows;
- `odds_snapshots`: 71,249 rows.

This confirms the local Round 6.5 migration has not been deployed and the real
database was not contaminated for validation.

## 15. Limitations and Round 6 Compatibility

Round 6.5 prepares future evidence; it does not make unverifiable history
verifiable. Round 6 therefore remains `insufficient_data` until the migration
and code are deployed and genuine pre-match production predictions accumulate.

Round 6 now consumes only records that pass the full Round 6.5 validator and
resolve to an existing, identity-matched revision. Its sticky FAIL/WARN/UNKNOWN
rules, evaluation-only behavior, and no-replay boundary remain strict.

`persisted_at` proves when the application attempted the evidence write within
the atomic transaction. Neither SQLite nor the configured MySQL path exposes a
portable transaction commit-completion timestamp, so an unusually delayed
commit crossing kickoff cannot be independently proven by this field. The
post-insert clock check minimizes that interval without claiming otherwise.

The ignored isolated review database
`apps/api/.tmp/round65-review/round6-5.db` remains on disk (561,152 bytes).
Cleanup approval was rejected by the approval backend; the file was preserved
and no workaround was attempted.

## 16. Final Status

Round 6.5 is complete locally. Migration
`0007-round6-5-production-evidence` is registered. Round 4 mathematics, Round 5
odds validation and 0.60/0.40 fusion, Elo, Poisson, Dixon-Coles, feature
weights, and betting behavior are unchanged. No ML, fitting, calibration,
optimization, commit, push, or deployment was performed.

Round 6.5 changed files, separate from the pre-existing dirty Round 1-6 work:

- API and repository: `apps/api/app/production_evidence.py` (new),
  `apps/api/app/database.py`, `apps/api/app/prediction_service.py`,
  `apps/api/app/dual_prediction_service.py`, `apps/api/app/production.py`,
  and `apps/api/app/temporal_backtest.py`.
- Tests: `apps/api/tests/test_round6_5_production_evidence.py` (new),
  `apps/api/tests/test_prediction_service.py`,
  `apps/api/tests/test_round6_temporal_backtest.py`, and
  `apps/api/tests/test_p15_production.py`.
- Documentation: `docs/AI_ROUND6_5_REPORT.md` and
  `docs/superpowers/specs/2026-09-17-football-ai-v2-round6-5-production-evidence-design.md`.
- Scoped planning: `.planning/.active_plan` and `task_plan.md`, `findings.md`,
  `progress.md` under `.planning/2026-09-17-football-ai-v2-round6-5/`.

The purpose is not to force an immediate historical Round 6 result. The
purpose is to accumulate real, verifiable, traceable production prediction
evidence from this point forward after deployment.
