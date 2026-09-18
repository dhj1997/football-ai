# Football AI v2 Round 6.5 Production Evidence Design

## Objective

Round 6.5 hardens the existing Round 5 persistence boundary so a newly
persisted deterministic probability can be distinguished from a later replay
or an old audit that only has logical cutoff time. The change preserves the
existing Round 4 formulas, Round 5 market math, Round 6 eligibility gates, and
all append-only stores.

## Canonical Evidence Contract

Production evidence is valid only when one immutable prediction revision is
linked to the same fixture and cutoff as its Round 3 feature snapshot, its
Round 5 audit, and (when `MODEL_PLUS_MARKET`) every selected odds snapshot. The
contract requires:

- `prediction_revision_id`, fixture ID, cutoff, and kickoff;
- cutoff strictly before kickoff;
- an application UTC `persisted_at` captured inside the final transaction at
  the database write boundary (not a commit-completion timestamp),
  greater than or equal to cutoff and strictly before kickoff;
- model and final probability vectors that are finite, non-negative, and sum
  to one;
- feature values available no later than cutoff;
- an append-only leakage audit whose status is `PASS`;
- odds IDs and cutoff-safe odds timestamps for `MODEL_PLUS_MARKET`, or no
  market probability and no market IDs for `MODEL_ONLY`;
- `production_evidence_valid=true` and `evidence_kind=production_prediction`.

Replay and historical rows never receive a synthetic timestamp. Existing
`market_snapshots` rows remain nullable and are not rewritten.

## Persistence Boundary

The repository keeps the existing prediction, revision, feature, odds, and
leakage tables. A single final transaction inserts the prediction, allocates
the append-only revision number, verifies the existing PASS leakage audit, and
inserts the Round 5 market evidence. The revision identity is represented as
`prediction_id:revision_number`; it is stored in the Round 5 audit payload and
does not introduce a second revision table. After the final insert, the
repository checks the UTC clock again; reaching or crossing kickoff aborts and
rolls back the entire transaction before control returns to the transaction
manager. This is an application-side check, not a COMMIT-completion guarantee.
For a first evidence write, the writer reads the persisted fixture kickoff in
the same transaction, locks that row on MySQL, requires the persisted status
to remain `scheduled`, and requires the caller value to match.

The serving revision persists the same deterministic probability vector as
Round 5 `model_probability` and records the Round 4 probability model and
calculation versions. The immutable Round 5 evidence is authoritative for the
complete model, market, and final probability layers. The repository rejects
any revision/evidence probability mismatch before opening the write
transaction. Both probability model/calculation versions must also match.

`market_snapshots.persisted_at` is the only schema addition. It is nullable for
legacy rows and is deliberately excluded from the immutable snapshot ID,
which derives solely from the prediction revision identity. This keeps retries
idempotent, rejects conflicting content for one revision through the existing
primary key, and preserves the application write timestamp as independent
provenance.
If an identical retry arrives after kickoff, the transaction validates and
returns the existing committed row with its original pre-kickoff timestamp;
only a new write is subject to fixture status/kickoff gates and the final clock
check. Later live/finished/rescheduled fixture changes do not invalidate an
identical retry, and conflicting content remains immutable.

The leakage audit is an immutable prerequisite persisted when the feature
snapshot is audited. The final transaction inserts the prediction, allocates
the revision, verifies and links that existing PASS audit, and inserts the
Round 5 evidence. It does not create a duplicate audit row.

## Production Path

The read-only probability route remains read-only. The existing current
prediction path calls the repository's atomic Round 6.5 writer after a valid
Round 4/5 result is available. Historical replay repositories are rejected.
Manual research snapshots remain non-production because they have no revision
association or production timestamp.

When the existing dual-model service fans out one shared fixture/cutoff, only
its primary service owns the provider-independent Round 4/5 production
evidence. Both model-specific prediction revisions remain append-only. This
prevents duplicate evidence from making the same cutoff ambiguous to Round 6.

If deterministic Round 4 cannot calculate because both teams lack all critical
feature evidence, the ordinary prediction revision remains available but no
Round 5 production evidence is created. Other validation or atomic-write
failures remain fail-closed and do not fall back.

## Validation and Compatibility

Validation is fail-closed and deterministic. Kickoff freeze remains unchanged.
Round 6 may consume a new row only when the complete production provenance is
present; old rows without independent persistence timing remain unavailable to
the evaluation. No model, calibration, optimization, or betting behavior is
changed.
