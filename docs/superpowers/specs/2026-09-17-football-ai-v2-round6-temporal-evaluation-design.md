# Football AI v2 Round 6 Temporal Evaluation Design

## Scope

Round 6 measures the Round 4 model probability, Round 5 Market Prior, and Round
5 final probability preserved in persisted Round 5 audit records. It is
evaluation-only: it does not recompute a historical prediction with current
code, fit anything, search parameters, rank the three probability sources, or
change Round 4/5 production behavior. Persistence alone does not prove whether
an audit was originally produced live or by an earlier replay.

## Considered Approaches

1. **Evaluate persisted Round 5 probability audits (selected).** Reuse the
   cutoff, three probability layers, source odds IDs, feature snapshot ID,
   versions, and frozen fusion provenance already stored in
   `market_snapshots`.
2. **Replay current Round 4/5 code over old fixtures.** Rejected because a
   current-code replay is not evidence of what was known or predicted at the
   historical time, and the available history does not prove a complete
   cutoff-safe replay chain.
3. **Extend the legacy backtest/evaluation engines.** Rejected because those
   paths learn weights, fit calibration, bootstrap statistics, and/or simulate
   betting, all outside Round 6.

## Historical Source Contract

The only Round 6 forecast source is a persisted `market_snapshots` record whose
nested payload has `snapshot_type=round5_probability_audit`. P11 research
snapshots in the same table are ignored as non-forecast records. A Round 5
audit supplies:

- `prediction_cutoff_at` and `feature_snapshot_id`;
- model, market, and final 1X2 probabilities;
- probability, market, calculation, and fusion versions;
- the fixed fusion weights and config hash;
- exact source odds snapshot IDs and Market Prior identity.

The table does not have an independent insertion timestamp, and Round 5 uses
the logical cutoff as `created_at`. Therefore Round 6 labels this source
`persisted_cutoff_safe_audit`, not `historical_production_prediction`. It can
prove that referenced inputs were no later than the cutoff; it cannot prove
that the audit row itself was written before kickoff. The source record's
historical/live/replay origin is therefore `unknown`. Each observation records
`replayed_prediction=null`, `replay_status=unknown_no_persisted_at`, and
`round6_replay_performed=false`. Report provenance records
`round6_replay_count=0` and
`source_replay_status=unknown_no_persisted_at`. These fields state that Round 6
v1 itself performs zero replay; they do not prove that a source audit was never
created by an earlier replay. Multiple different audits for the same fixture
and cutoff are excluded as `ambiguous_probability_revision`.

## Temporal Eligibility

Evaluation units are unique `fixture + prediction_cutoff_at` observations and
are sorted by kickoff, cutoff, fixture ID, and audit ID. Shared eligibility
requires a fixture, parseable kickoff, finished numeric result, valid pre-match
cutoff, resolvable feature snapshot, persisted leakage evidence, canonical
`LeakageAuditService(...).audit_feature_snapshot(..., persist=False) == PASS`,
and cutoff-safe referenced odds. Any historical leakage `FAIL` is sticky and
excludes the observation even if a later audit says `PASS`; missing or only
unknown/WARN evidence also excludes it.

Probability eligibility is layer-specific after shared temporal eligibility.
A missing or invalid model, market, or final vector is never filled from
another layer; it removes only that layer from metrics and coverage and records
the reason. This preserves MODEL_ONLY observations for model/final measurement
without pretending Market Prior existed. A `MODEL_PLUS_MARKET` audit must carry
exactly one fusion and the frozen `0.60 / 0.40` configuration, and its stored
final vector must equal that fixed fusion. Round 6 validates this provenance
but never fuses the values again.

## Cutoff Segments

The existing scheduler offsets `24,12,6,1,0.5` hours are reused. Its current
ceiling-window semantics define non-overlapping segments: a positive lead time
belongs to the smallest configured offset greater than or equal to it. Values
outside the configured horizon are reported as `other`; post-kickoff values are
excluded. Every configured segment is emitted even when empty, with
`status=insufficient_data` below the fixed display threshold of 30.

## Metrics And Reporting

`ProbabilityEvaluationService` is a pure deterministic calculator with no
database, provider, prediction, or LLM access. It uses:

- multiclass Log Loss with versioned epsilon `1e-15`;
- summed three-class Brier Score;
- standard normalized 1X2 RPS over cumulative `H` and `H+D` terms;
- argmax Accuracy as an auxiliary metric;
- ten descriptive one-vs-rest calibration bins and descriptive ECE;
- explicit sample counts, layer coverage, and `min_samples=30` status.

Probability vectors must be finite, non-negative, and already sum to one within
an explicit floating-point tolerance. Only that small drift is normalized.
The report contains overall layer metrics, layer calibration, coverage,
cutoff/availability/league/season segments, exclusions, chronological audit
observations, source/version provenance, and a deterministic dataset
fingerprint. It presents metrics side by side without winner/rank language.

## API And Persistence

An authenticated `GET /api/admin/backtest/probability` is read-only and exposes
only date, league, and bounded sample controls. It has no weight, mode, seed,
training, strategy, or cutoff-search parameter. An explicit authenticated POST
may persist the same deterministic report in the existing immutable
`backtest_runs` table under a content-addressed ID. GET never writes, identical
POST input reuses the immutable run, and no migration is required.

## Verification

Focused tests cover metric formulas, strict normalization, calibration bins,
coverage, exclusions, chronological ordering, cutoff safety, sticky leakage
failure, exact odds provenance, probability-layer separation, frozen fusion,
duplicate ambiguity, deterministic fingerprints, append-only storage, and the
admin read-only API. Real MySQL validation uses a narrow fixture window and a
source-selection limit of at most 30 candidate fixtures. The limit bounds
fixture reads before evaluation; it is not an after-the-fact observation slice.
Zero evaluable finished fixtures is a valid `insufficient_data` result and is
never replaced with replay or synthetic data. The validation path performs no
database write.
