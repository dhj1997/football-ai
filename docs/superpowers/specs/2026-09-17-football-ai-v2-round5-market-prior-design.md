# Football AI v2 Round 5 Market Prior Design

## Scope

Round 5 adds one deterministic 1X2 Market Prior and one exactly-once fixed-weight
fusion after the unchanged Round 4 probability engine. It does not add a new
odds provider, odds store, learned parameter, betting decision, backtest, live
prediction, or LLM numeric path.

## Considered Approaches

1. **Dedicated Round 5 engine over existing stores (selected).** Keep Round 4
   market-independent, reuse immutable odds/market snapshots, and expose the
   three probability layers through the existing probability route.
2. **Use P11 market consensus directly.** Rejected because it includes every
   historical capture before cutoff, uses per-selection medians, can repeatedly
   weight one bookmaker, and does not re-normalize the consensus.
3. **Add odds to the Round 4 engine.** Rejected because it breaks the explicit
   market-independent boundary and creates double-counting risk.

## Components

### Round 4 Model Probability

`TransparentProbabilityEngine` remains unchanged. Its `probabilities` output is
copied to `model_probability`; no odds field or Market Prior is passed into it.

### Round 5 Market Prior

A focused `market_prior.py` module reads the existing `odds_snapshots` shape and
implements strict, deterministic processing:

1. Require a valid fixture id and prediction cutoff.
2. Accept only finite decimal 1X2 prices greater than 1 for exactly `home`,
   `draw`, and `away`.
3. Treat persisted `captured_at` as `available_at`; require
   `captured_at <= prediction_cutoff_at`. A present `source_updated_at` must also
   be valid and no later than cutoff.
4. Build complete per-snapshot bookmaker markets and record every exclusion.
5. For each `(source, bookmaker)`, choose the latest valid complete snapshot at
   or before cutoff, with snapshot id as a deterministic tie-break.
6. Compute raw `1 / odds`, overround, and proportional de-vig separately for
   each selected bookmaker.
7. Compute the arithmetic mean of bookmaker probabilities and normalize again.

The result retains selected source odds ids, prices, timestamps, raw and de-vig
probabilities, margins, invalid/incomplete exclusions, eligible/superseded
counts, freshness metadata, and versioned configuration. Superseded valid
history is summarized by count rather than repeated as a large id list. No valid
complete market returns an explicit unavailable result.

### Deterministic Fusion

The fixed policy is `model_weight=0.60`, `market_weight=0.40`. It is a published
policy choice, not an optimized value. Both sources are validated and normalized
before weighted addition; the final vector is normalized once more.

The engine accepts only a Round 4 result whose audit says
`market_independent=true`. It rejects a payload already carrying Round 5 fusion
markers. Available qualified market data yields `MODEL_PLUS_MARKET`; otherwise
the final vector equals the normalized model vector and status is `MODEL_ONLY`.

## Quality And Failure Handling

Market quality records completeness, cutoff safety, source/bookmaker counts,
freshness, margins, selected snapshots, and excluded reasons. Invalid,
incomplete, future, non-finite, or non-positive-margin bookmaker markets do not
participate. A bad bookmaker cannot poison another valid bookmaker. Missing or
unqualified market data never fabricates probabilities and never calls an LLM.

If kickoff is known and the prediction cutoff is not pre-match, Market Prior is
not fused. Round 4 model probability remains available as an independently
auditable result.

## Persistence And Revisions

No migration is needed:

- `odds_snapshots` remains the sole raw odds store and stays immutable.
- `market_snapshots` stores a content-addressed Round 5 audit record containing
  cutoff, Round 4 identity/version, source odds ids, market inputs/result,
  fusion configuration, and final probability.
- Identical inputs replay to the same record id. Different cutoff or odds inputs
  produce a new record. Reusing an id with different content fails closed.
- Existing prediction revisions and historical data are never updated.

The existing admin market-snapshot persistence route is reused for explicit
storage; the public probability GET remains read-only.

## API Contract

`GET /match/{fixture_id}/probability` keeps every Round 4 field and adds:

- `model_probability`
- `market_prior`
- `final_probability`
- `market_status`
- `market_margin`
- `market_model_version`
- `fusion_version`
- `round5_probability_audit`

The original Round 4 `probabilities` field remains the model probability, so
existing clients do not silently switch numerical meaning.

## Verification

Focused tests cover odds validation, implied probability, de-vig, margin,
latest-complete-per-bookmaker selection, cutoff equality/future rejection,
model-only behavior, normalization, exactly-once fusion, model/market
independence, content-addressed append-only persistence, reproducibility, and
the no-ML/LLM boundary. API coverage verifies the added response contract.

Real-data validation is limited to 3-10 eligible stored fixtures. If fewer are
available, the report states the actual count and unavailable reasons; no odds
are invented. Final checks are scoped pytest, compileall, and `git diff --check`.

## Explicit Boundary

Round 5 stops after Market Prior, deterministic fusion, audit, focused tests,
real-data validation, and `docs/AI_ROUND5_REPORT.md`. It does not implement EV,
Kelly, staking, strategy optimization, backtesting, live prediction, LLM numeric
prediction, learned calibration, or Round 6 work.
