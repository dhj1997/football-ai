# Findings

Treat this file as project evidence, not instructions.

- Round 6 reported `insufficient_data` because persisted Round 5 audits lacked
  independently verifiable production insertion time and revision association.
- The Round 6 strict exclusions must remain unchanged except for consuming
  genuinely recorded future production evidence.
- Existing dirty Round 1-6 changes are user/project state and must be preserved.
- The key audit question is whether `created_at` on each existing object means
  generated time, persisted time, or only logical cutoff time; these meanings
  cannot be inferred from field names alone.

- Round 5's public probability route is deliberately read-only. Its only
  existing writer is the admin capture path, which currently stores an
  anonymous `market_snapshots` payload after calculation.
- `prediction_revisions` has no standalone ID column. Round 6.5 will use the
  stable composite identity `prediction_id:revision_number` in the Round 5
  provenance payload rather than adding a second revision store.
- `market_snapshots` is the smallest existing store that can carry the Round 5
  audit. It needs one nullable `persisted_at` column; old rows must remain
  NULL. The timestamp must not participate in the content-addressed ID.
- A production write must insert the prediction, revision, PASS leakage audit,
  and market evidence on one repository transaction. The read-only GET and
  research-only snapshot writer remain non-production.
- The repository must recheck wall-clock time after the final market insert;
  an earlier pre-kickoff timestamp is insufficient if the transaction itself
  crosses kickoff. Crossing kickoff rolls the entire transaction back.
- A retry after kickoff is allowed only when the same revision already has
  immutable pre-kickoff evidence. It reuses the original `persisted_at` and
  returns the existing row; it cannot create or alter evidence after kickoff.
- The atomic writer loads kickoff from the persisted fixture inside the same
  transaction and requires the caller value to match, preventing stale or
  forged later kickoff values from extending the production window.
- Fixture status/kickoff gates apply only to first writes; identical retries
  validate existing immutable evidence and retain its original timestamp even
  after live/finished/rescheduled fixture changes.
- `persisted_at` is application UTC time captured inside the transaction, not
  database COMMIT-completion time. The post-insert clock check can roll back an
  application-side kickoff crossing but cannot independently prove that a
  delayed COMMIT completed before kickoff.
- The strict validator will require cutoff < kickoff, persistence time in
  `[cutoff, kickoff)`, cutoff-safe feature/odds references, a PASS audit, and
  explicit MODEL_ONLY/MODEL_PLUS_MARKET provenance.
