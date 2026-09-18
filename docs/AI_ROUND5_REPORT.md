# Football AI v2 Round 5 Report

## 1. Round 5 Summary

Round 5 adds one deterministic 1X2 market path after the unchanged Round 4
probability engine:

```text
Round 4 Model Probability + Cutoff-safe Market Prior
                         -> Fixed 0.60 / 0.40 Fusion
                         -> Final Probability
```

The implementation is strict No-ML. It does not train, fit, optimize, call an
LLM for numeric output, create a second odds provider, or change any Round 4
expected-goals, Poisson, Dixon-Coles, score-matrix, 1X2, O/U, or BTTS formula.

The main implementation is `apps/api/app/market_prior.py`. The existing
`GET /match/{fixture_id}/probability` route now returns separate model, market,
and final probability layers. No schema migration was required.

## 2. Existing Odds Provider

Round 5 consumes the repository's existing immutable `odds_snapshots`. It does
not call a new provider and does not create a parallel market-data store.

The active multi-bookmaker snapshots are populated by the existing Dongqiudi
adapter and sync service. The adapter already reads 1X2, Asian handicap, and
over/under markets and maps two available bookmaker feeds to neutral public
labels, market reference A and B. The existing API-Football/APISports adapter
remains available in the fixture-evidence architecture, but Round 5 operates on
persisted snapshots rather than adding a provider-specific calculation path.

Historical Football-Data closing prices can exist in the same store, but their
availability time is kickoff. The cutoff rule therefore prevents them from
being used to reconstruct an earlier pre-match prediction.

## 3. Odds Snapshot

The reused `odds_snapshots` schema already records:

- snapshot and fixture identifiers;
- market, selection, line, and decimal price;
- bookmaker and source;
- application capture time in `captured_at`;
- provider update metadata in `source_updated_at`;
- the original normalized payload.

Snapshots are append-only. Replaying an identical snapshot ID and payload is
idempotent; attempting to reuse an ID with changed content fails as immutable.
Round 5 groups the stored quote rows back into one snapshot before calculation.

The raw table does not have a separate `odds_snapshot_version` column. Raw
version identity is provided by the immutable snapshot ID and payload; some
provider adapters use content-derived IDs while others use stable UUID or
fixture/group identities. Round 5 adds explicit market calculation and fusion
versions to the derived audit.

## 4. Cutoff Safety

`captured_at` is the existing system's strongest `odds_available_at`
equivalent because it records when the application obtained the quote. Round 5
requires:

```text
captured_at <= prediction_cutoff_at
```

Equality is allowed. A later capture is outside the input set. Every 1X2 quote
must also have a valid capture time no later than the cutoff. If
`source_updated_at` is present at snapshot or quote level, it must parse and
must not be later than the cutoff. An empty quote-level value cannot mask an
invalid or future snapshot-level value.

If kickoff is known, `prediction_cutoff_at >= kickoff` disables market fusion
and returns `MODEL_ONLY`. Round 5 does not implement a live path.

## 5. Implied Probability

Each decimal price is validated as a non-null, non-boolean, finite number
strictly greater than `1`. Invalid data is rejected rather than coerced.

For each outcome:

```text
p_raw = 1 / decimal_odds
```

Only a complete set containing exactly `home`, `draw`, and `away` can form a
1X2 Market Prior.

## 6. De-vig Method

Round 5 reuses the existing transparent proportional de-vig primitive. For one
bookmaker:

```text
total_raw = p_home_raw + p_draw_raw + p_away_raw
p_market_i = p_raw_i / total_raw
```

The three de-vig probabilities are normalized to sum to `1`. No Shin, power,
odds-ratio, Bayesian, bookmaker-fitted, or learned method is used.

## 7. Market Margin

The bookmaker overround is:

```text
market_margin = p_home_raw + p_draw_raw + p_away_raw - 1
```

Each selected bookmaker retains its own raw implied probabilities, de-vig
probabilities, and margin. A non-positive overround fails closed in the reused
market primitive. The aggregate `market_margin` is the arithmetic mean of the
selected bookmaker margins; it is an audit metric, not a learned weight.

## 8. Market Prior

`build_market_prior` accepts only snapshots that satisfy all of the following:

- the fixture ID matches;
- the snapshot and quote timestamps are valid and cutoff-safe;
- source and bookmaker are present;
- the market is a complete 1X2 set;
- every selection and decimal price is valid;
- proportional de-vig succeeds with a valid margin.

The available result contains a content-addressed `market_prior_id`, market and
calculation versions, source odds snapshot IDs, selected bookmaker detail,
probabilities, margin, freshness, quality, and exclusion reasons. Invalid and
incomplete records remain visible in `excluded_snapshots`.

Valid older history is summarized by `eligible_snapshot_count` and
`superseded_snapshot_count`, rather than copying hundreds of normal superseded
snapshot IDs into every audit.

If no complete cutoff-safe 1X2 market exists, the prior is explicitly
`unavailable`, probabilities remain `None`, and `missing_reason` is retained.
No demo, random, historical guess, model copy, or LLM fallback is created.

## 9. Multiple Bookmaker Handling

For every `(source, bookmaker)` pair, Round 5 selects the latest valid complete
snapshot at or before the cutoff. Snapshot ID is the deterministic tie-break
when capture times are equal.

Each selected bookmaker is de-vigged independently. The per-outcome values are
then aggregated by simple arithmetic mean and normalized once more:

```text
market_i = normalize(mean(bookmaker_1_i, ..., bookmaker_n_i))
```

Every bookmaker has equal weight. There is no learned reputation score,
historical performance weight, dynamic quality weight, or outlier model.

## 10. Model Probability

The Round 4 `TransparentProbabilityEngine` remains the sole source of
`model_probability`. It consumes an audit-passed Round 3 Feature Snapshot and
does not read odds. Round 4 rejects consumed feature sources containing market
or odds data and exposes `market_independent=true` and `no_ml=true` audit checks.

Round 5 requires those checks and requires complete feature snapshot, model
version, and calculation version provenance. It validates that the Round 4
probability vector already sums to one without rounding or renormalizing the
source values. The original Round 4 `probabilities` response field is retained
unchanged for existing clients.

## 11. Deterministic Fusion

When the Market Prior is available:

```text
final_i = 0.60 * model_i + 0.40 * market_i
```

The resulting vector is normalized for stable serialization. An input payload
that already carries a Round 5 audit, fusion version, or fusion-applied marker
is rejected, preventing a second market application. The audit records a
`market_fusion_count` of `1` for `MODEL_PLUS_MARKET` and `0` for `MODEL_ONLY`.

Changing odds does not change `model_probability`. Changing Round 4 features
does not change a Market Prior built from the same odds snapshots.

## 12. Fusion Weight

The immutable `MarketPriorConfig` centrally defines:

| Field | Value |
| --- | ---: |
| Model weight | 0.60 |
| Market weight | 0.40 |
| Market model version | `market-prior-v1` |
| Market calculation version | `round5-market-prior-v1` |
| Fusion version | `round5-fixed-fusion-v1` |
| Audit version | `round5-probability-audit-v1` |

Weights must be finite, non-negative, and sum to one. The serialized policy is
marked `fixed_not_historically_optimized` and includes a deterministic config
hash. The 0.60/0.40 split is a transparent policy choice, not an accuracy or
ROI claim and not a historically optimized parameter.

## 13. Final Probability

The API distinguishes:

- `MODEL_PLUS_MARKET`: `market_prior` is present and `final_probability` is the
  fixed fusion result;
- `MODEL_ONLY`: `market_prior` is `None`, the missing or disabled reason is
  explicit, and `final_probability` exactly preserves `model_probability`.

The response exposes `model_probability`, `market_prior`,
`final_probability`, `market_status`, `market_margin`, market/fusion versions,
fusion configuration, detailed Market Prior, and the Round 5 audit. Each
available 1X2 vector sums to one.

## 14. Probability Provenance

The derived audit records the complete Round 5 chain:

```text
Feature Snapshot
  -> Round 4 model/calculation versions and Model Probability
  -> source Odds Snapshot IDs and selected bookmaker inputs
  -> Market Prior ID, version, probabilities, and margin
  -> fixed Fusion Version, config hash, and weights
  -> Final Probability and market status
```

Selected-bookmaker detail retains prices, raw implied probabilities, de-vig
probabilities, capture/update timestamps, and margins. Missing mandatory Round
4 provenance fails closed rather than producing a successful audit with null
identifiers.

## 15. Append-only / Revision Handling

Round 5 reuses the existing `market_snapshots` table for content-addressed
probability-audit records. Both `MODEL_PLUS_MARKET` and `MODEL_ONLY` produce a
persistable audit record. The latter keeps `market_probability=None`, a null
overround, the unchanged model/final vector, and `missing_reason`.

Identical capture is idempotent. Same ID with changed content fails immutable.
The insert path also re-reads and compares after a concurrent unique-key race,
so simultaneous identical admin captures remain idempotent. A different cutoff
or different source input creates a different content ID and never changes an
older record.

Persistence is explicit through the existing authenticated
`POST /api/admin/fixtures/{fixture_id}/market-snapshot` route. The public
probability GET remains read-only, consistent with Round 4. Round 5 does not
automatically write these layers into `prediction_revisions.payload`; it uses
the existing `market_snapshots` audit store and does not claim automatic
historical prediction-revision capture. No historical prediction or revision
is updated.

## 16. Real Data Validation

Read-only validation used the configured MySQL database after the final audit
payload changes. It found 4 latest-audit-PASS Round 3 feature snapshots across
3 unique fixtures. All 3 fixtures had two complete real Dongqiudi bookmaker
snapshots and returned `MODEL_PLUS_MARKET`. No data was inserted or modified.

### Fixture-level results

| Fixture | Cutoff UTC | Model H/D/A | Market H/D/A | Final H/D/A | Mean margin | Eligible / superseded |
| --- | --- | --- | --- | --- | ---: | ---: |
| `sportsdb-2506219` | `2026-09-16T03:41:21Z` | 0.350196 / 0.267533 / 0.382270 | 0.890512 / 0.068061 / 0.041428 | 0.566323 / 0.187744 / 0.245933 | 0.049568 | 92 / 90 |
| `sportsdb-2506220` | `2026-09-16T03:41:22Z` | 0.848176 / 0.106060 / 0.045763 | 0.691297 / 0.195797 / 0.112905 | 0.785425 / 0.141955 / 0.072620 | 0.048249 | 12 / 10 |
| `sportsdb-2506222` | `2026-09-16T03:41:21Z` | 0.350156 / 0.315318 / 0.334526 | 0.278304 / 0.266706 / 0.454990 | 0.321415 / 0.295873 / 0.382711 | 0.049160 | 92 / 90 |

For every row, model, market, and final displayed values sum to `1.000000`
within serialization precision.

### Selected bookmaker calculations

| Fixture / reference | Raw odds H/D/A | Raw implied H/D/A | De-vig H/D/A | Margin |
| --- | --- | --- | --- | ---: |
| `2506219` / A | 1.06 / 14.00 / 23.00 | 0.943396 / 0.071429 / 0.043478 | 0.891423 / 0.067494 / 0.041083 | 0.058303 |
| `2506219` / B | 1.08 / 14.00 / 23.00 | 0.925926 / 0.071429 / 0.043478 | 0.889601 / 0.068627 / 0.041772 | 0.040833 |
| `2506220` / A | 1.38 / 4.75 / 8.50 | 0.724638 / 0.210526 / 0.117647 | 0.688288 / 0.199966 / 0.111746 | 0.052811 |
| `2506220` / B | 1.38 / 5.00 / 8.40 | 0.724638 / 0.200000 / 0.119048 | 0.694306 / 0.191629 / 0.114065 | 0.043686 |
| `2506222` / A | 3.40 / 3.50 / 2.10 | 0.294118 / 0.285714 / 0.476190 | 0.278515 / 0.270557 / 0.450928 | 0.056022 |
| `2506222` / B | 3.45 / 3.65 / 2.09 | 0.289855 / 0.273973 / 0.478469 | 0.278093 / 0.262855 / 0.459052 | 0.042297 |

The corresponding feature snapshot IDs are:

- `sportsdb-2506219`: `feature:9b381caf2fc62b67889e5bfdbc8975747e8b8d6f44b7444b9503c39542d40ddb`
- `sportsdb-2506220`: `feature:6da8f4f0cb6f1ebd1f4eadb40486db711cea1a4c27dd7cfb839a89455fe2e7c0`
- `sportsdb-2506222`: `feature:c2ad06250c78ad25578fba908937a9f71f26607296aa6276e649dfa7ea53a99e`

The program also retained the exact selected source odds snapshot IDs in each
Market Prior audit.

## 17. Test Results

The final risk-proportionate verification includes:

- Round 4 + Round 5 + P11 + targeted probability API: `39 passed`;
- Round 2 repository regression: `26 passed`;
- complete API regression: `27 passed`;
- Python `compileall` for `apps/api/app` and `apps/api/tests`: passed;
- `git diff --check`: passed, with only existing LF/CRLF conversion warnings;
- trailing-whitespace scan for untracked Round 5 files: passed.

Focused Round 5 cases cover decimal-odds validation, invalid/null/unsupported
markets, implied probability, de-vig, margin, cutoff equality and rejection,
snapshot/quote source-update safety, latest complete bookmaker selection,
multi-bookmaker aggregation, normalization, exact model preservation,
MODEL_ONLY, fixed fusion, exactly-once rejection, independence, deterministic
replay, kickoff freeze, No-ML gates, required provenance, append-only
persistence, immutable conflict rejection, and durable MODEL_ONLY audit.

## 18. Known Limitations

Round 5 intentionally does not implement:

- ML or LLM numeric prediction;
- learned market weights or learned calibration;
- bookmaker historical weighting or ranking;
- odds movement or closing-line prediction;
- EV, Kelly, staking, betting recommendation, or strategy optimization;
- backtest optimization or large-scale historical replay;
- live prediction;
- Asian handicap or O/U Market Prior redesign.

The current quality policy validates completeness, timestamps, finite prices,
positive margin, provider availability, and bookmaker count. It records
freshness and margin but does not impose a learned/dynamic freshness threshold,
margin threshold, or outlier score. Multiple bookmakers remain equal-weight.

Round 5 audit persistence is an explicit admin action and uses
`market_snapshots`; it is not automatic prediction-revision persistence. The
deterministic audit `created_at` is the prediction cutoff logical time, not a
wall-clock insertion timestamp. These are documented boundaries, not claims of
missing predictive performance.

No accuracy, ROI, market-beating, bookmaker-beating, or optimal-weight claim is
made. That would require a separate temporal evaluation design.

## 19. Round 6 Boundary

Round 5 stops at validated real odds, proportional de-vig, Market Prior,
fixed-weight deterministic fusion, explicit audit persistence, focused tests,
and real-data evidence.

It does not enter EV, Kelly, staking, strategy, backtesting, live prediction,
LLM numeric output, learned calibration, or any ML work. Those require separate
scope and approval.
