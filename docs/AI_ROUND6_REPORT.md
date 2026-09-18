# Football AI v2 Round 6 Report

Date: 2026-09-17

Round 6 is an evaluation-only delivery. It measures persisted probability
layers without changing prediction formulas, production weights, calibration,
or betting behavior.

## 1. Round 6 Objective

The objective is to measure the current transparent probability system on
cutoff-safe historical inputs. The report keeps three probability layers
separate:

- Round 4 Model Probability;
- Round 5 Market Prior;
- Round 5 Final Probability produced by the frozen production fusion.

The output is descriptive. It does not select a winner, tune a parameter, or
change production behavior.

## 2. Scope

Round 6 adds a pure probability metric service, a temporal evaluation service,
two authenticated admin endpoints, focused tests, the design specification,
and this report.

The implementation files are:

- `apps/api/app/probability_evaluation.py`;
- `apps/api/app/temporal_backtest.py`;
- the bounded fixture, leakage-audit, and immutable-run repository support in
  `apps/api/app/database.py`;
- the Round 6 integration in `apps/api/app/main.py`;
- `apps/api/tests/test_round6_probability_evaluation.py`;
- `apps/api/tests/test_round6_temporal_backtest.py`;
- the Round 6 API contracts in `apps/api/tests/test_api.py`;
- `docs/superpowers/specs/2026-09-17-football-ai-v2-round6-temporal-evaluation-design.md`;
- `docs/AI_ROUND6_REPORT.md`.

No Round 6 database migration was added. Existing fixture, feature snapshot,
leakage audit, odds snapshot, market snapshot, and `backtest_runs` contracts are
reused.

## 3. No-ML Boundary

`ProbabilityEvaluationService` is deterministic arithmetic. It does not access
the database, call an odds provider, invoke an LLM, generate a prediction, fit a
model, or learn a calibration transform.

Round 6 does not execute the legacy evaluation paths that contain learned
weights, fitted calibration, bootstrap statistics, or betting simulation. It
introduces no ML, no fitting, no LLM numeric probability, and no automatic
decision based on the evaluation result.

## 4. Temporal Evaluation Design

The evaluation unit is a unique `fixture_id + prediction_cutoff_at` observation.
Observations are sorted by kickoff, cutoff, fixture ID, and persisted audit ID.

Shared temporal eligibility requires:

- an existing fixture and parseable kickoff;
- a finished numeric result;
- a prediction cutoff strictly before kickoff;
- a resolvable immutable feature snapshot for the same fixture and cutoff;
- persisted leakage evidence and a fresh canonical read-only leakage PASS;
- cutoff-safe referenced odds when Market Prior is present;
- a persisted Round 5 probability audit with required version provenance.

The service reads persisted values and performs zero probability replay. It does
not call the Round 4 or Round 5 probability engines during evaluation.

Configured cutoff bands are `24h`, `12h`, `6h`, `1h`, and `30m`, plus `other`.
Each positive lead time uses the smallest configured ceiling that contains it.
Post-kickoff records are excluded.

## 5. Leakage Protection

Round 6 reuses `LeakageAuditService`; it does not implement a parallel leakage
rule set. A persisted PASS must match the feature snapshot cutoff, and the
canonical service rechecks the snapshot with `persist=False`.

Append-only semantics are sticky:

- any historical `FAIL` excludes the observation;
- missing, WARN, UNKNOWN, or cutoff-mismatched PASS evidence excludes it;
- a later PASS cannot erase an earlier FAIL;
- feature `available_at` and referenced odds timestamps must not exceed the
  prediction cutoff.

This proves cutoff safety of the referenced inputs. It does not prove when the
Round 5 audit row itself was inserted.

## 6. Prediction Sources

The only forecast source accepted by v1 is a persisted `market_snapshots` record
whose payload has `snapshot_type=round5_probability_audit`. P11 research records
in the same table are ignored.

The audit retains the cutoff, feature snapshot ID, source odds snapshot IDs,
Market Prior identity, model/calculation/fusion versions, fixed weights, and the
three probability vectors.

`market_snapshots` has no independent wall-clock insertion timestamp, and its
Round 5 `created_at` is the logical prediction cutoff. Consequently:

- source kind is `persisted_cutoff_safe_audit`;
- historical production versus earlier replay origin is `unknown`;
- Round 6 performed zero replay during this evaluation;
- each observation records `replayed_prediction=null`,
  `replay_status=unknown_no_persisted_at`, and
  `round6_replay_performed=false`;
- report provenance records `round6_replay_count=0` and
  `source_replay_status=unknown_no_persisted_at`.

The Round 6 replay fields describe its own execution path only. They do not
prove that the persisted source was originally live.

No result in this report is described as a verified historical production
prediction.

## 7. Model / Market / Final Definitions

| Layer | Definition | Missing-data behavior |
| --- | --- | --- |
| Model | Persisted Round 4 market-independent 1X2 probability | No imputation |
| Market | Persisted Round 5 de-vigged Market Prior from validated odds | Absent for `MODEL_ONLY` |
| Final | Persisted Round 5 final 1X2 probability | No recomputation |

For `MODEL_PLUS_MARKET`, Round 6 verifies one frozen fusion:

`Final = 0.60 * Model + 0.40 * Market`

The `0.60 / 0.40` configuration is evaluated as a frozen production
configuration. It was not optimized on the backtest set. Round 6 validates the
stored final vector but never fuses it a second time.

For `MODEL_ONLY`, the Market layer remains missing and Final must equal Model.
Each layer has independent metrics and coverage.

## 8. Metrics

The metric contract is `round6-probability-metrics-v1`.

- Multiclass Log Loss: `-log(max(1e-15, p_actual))`;
- summed three-class Brier Score: `sum((p_i - o_i)^2)`;
- normalized 1X2 RPS:
  `((pH-oH)^2 + ((pH+pD)-(oH+oD))^2) / 2`;
- Accuracy: deterministic argmax equality, used only as an auxiliary measure;
- Coverage: reported separately for Model, Market, and Final;
- descriptive calibration: ten one-vs-rest bins per outcome.

The Log Loss epsilon is fixed at `1e-15` and versioned. Probability vectors must
be finite, non-negative, contain exactly Home/Draw/Away, and sum to one within
the published tolerance. Only tiny floating-point drift is normalized.

## 9. Calibration

Calibration is descriptive only. For each of Home, Draw, and Away, the service
emits ten bins from `0.0-0.1` through `0.9-1.0`, including sample count, mean
predicted probability, actual frequency, and gap. Descriptive per-outcome ECE
and their mean are also reported.

No Platt scaling, isotonic regression, temperature fitting, or other fitted
calibration is present. The fixed display threshold is `min_samples=30` and is
not an optimized model parameter.

The real MySQL validation produced zero eligible observations. Calibration has
`sample_count=0`, `status=insufficient_data`, empty-count bins, and null ECE.

## 10. Coverage

Coverage uses shared eligible observations as the denominator and never fills a
missing layer from another source.

| Probability | N | Eligible denominator | Coverage | Status |
| --- | ---: | ---: | ---: | --- |
| Model | 0 | 0 | N/A | `insufficient_data` |
| Market | 0 | 0 | N/A | `insufficient_data` |
| Final | 0 | 0 | N/A | `insufficient_data` |

Coverage is N/A rather than `0%` because the denominator is zero. Reporting
`0%` would imply eligible observations existed but all three layers were absent.

## 11. Exclusion Rules

The service records exclusions instead of silently skipping data. Shared reasons
include:

- `missing_fixture_id`, `missing_kickoff`, and `missing_result`;
- `missing_historical_probability_audit`, `missing_cutoff`, and
  `post_kickoff_prediction`;
- `ambiguous_probability_revision` and `insufficient_provenance`;
- `missing_feature_snapshot`, `leakage_unknown`, and `leakage_failed`;
- `missing_odds_snapshot`, `odds_after_prediction_cutoff`, and
  `insufficient_odds_provenance`.

Layer-specific reasons include missing/invalid Model, Market, or Final vectors
and `invalid_frozen_fusion`. Layer-specific failure is not imputed and does not
erase valid metrics for another layer.

The real validation exclusions were:

| Reason | Count |
| --- | ---: |
| `missing_historical_probability_audit` | 9 |
| `missing_result` | 7 |
| Total discovered fixtures | 16 |

## 12. Historical Data Coverage

Read-only validation used the configured real MySQL environment and the bounded
calendar window `2026-09-17` with a source-selection limit of at most 30
candidate fixtures. The limit bounds fixture reads before evaluation; it is not
an after-the-fact observation slice.

| Field | Value |
| --- | ---: |
| Discovered fixtures | 16 |
| Finished fixtures without a persisted Round 5 audit | 9 |
| Fixtures without a finished result | 7 |
| Persisted Round 5 probability audits found | 0 |
| Eligible observations | 0 |
| Evaluated observations | 0 |
| Evaluated fixtures | 0 |

No mock, demo, synthetic, random, or fabricated probability was substituted for
the missing history. The result is truthful insufficient historical coverage.

## 13. Backtest Results

There is no evaluated historical sample from which to calculate probability
metrics.

`evaluation_start=null` and `evaluation_end=null` because no observation passed
eligibility. The requested candidate window was `2026-09-17` through
`2026-09-17`.

| Probability | N | Coverage | Log Loss | Brier | RPS | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Model | 0 | N/A | N/A | N/A | N/A | N/A |
| Market | 0 | N/A | N/A | N/A | N/A | N/A |
| Final | 0 | N/A | N/A | N/A | N/A | N/A |

Overall status is `insufficient_data`. No comparison, ranking, or performance
claim is possible.

## 14. Segment Results

All configured cutoff segments are emitted even when empty.

| Cutoff | Model N / Log Loss | Market N / Log Loss | Final N / Log Loss | Status |
| --- | --- | --- | --- | --- |
| 24h | 0 / N/A | 0 / N/A | 0 / N/A | `insufficient_data` |
| 12h | 0 / N/A | 0 / N/A | 0 / N/A | `insufficient_data` |
| 6h | 0 / N/A | 0 / N/A | 0 / N/A | `insufficient_data` |
| 1h | 0 / N/A | 0 / N/A | 0 / N/A | `insufficient_data` |
| 30m | 0 / N/A | 0 / N/A | 0 / N/A | `insufficient_data` |
| other | 0 / N/A | 0 / N/A | 0 / N/A | `insufficient_data` |

League, season, and availability segments contain no evaluated rows. They are
not expanded into conclusions or combined with unrelated data.

## 15. Limitations

- The validated MySQL window contains no persisted Round 5 probability audit
  matched to a finished fixture, so all probability metrics are unavailable.
- Audit input cutoff safety can be proven, but original live-versus-replay
  source history cannot be proven because `market_snapshots` lacks an
  independent insertion timestamp.
- Round 5 audits are explicit admin captures rather than automatic immutable
  prediction-revision records.
- A zero-sample result validates exclusion and reporting behavior, not forecast
  quality.
- `min_samples=30` prevents strong segment conclusions even after the first few
  eligible observations appear.
- No production weight, calibration, feature formula, or odds policy can be
  inferred from this insufficient sample.

## 16. Reproducibility

Round 6 preserves `backtest_version=round6-v1`, metric and epsilon versions,
feature/odds/audit snapshot identities, calculation versions, frozen fusion
provenance, filters, chronological observations, exclusions, and a deterministic
dataset fingerprint.

`GET /api/admin/backtest/probability` is authenticated and read-only. Optional
`POST /api/admin/backtest/probability` wraps the same deterministic report in the
existing immutable `backtest_runs` store. Identical content is intended to reuse
the content-addressed run; changed content must never overwrite an old run.

The real MySQL validation used only the read-only path. It inserted, updated,
and deleted zero database rows. No Round 6 evaluation record was persisted.

## 17. What Was NOT Optimized

Round 6 did not optimize or modify:

- the frozen `0.60 / 0.40` fusion;
- Elo, Poisson, or Dixon-Coles formulas or parameters;
- feature weights or Feature Engine behavior;
- calibration or probability normalization policy;
- bookmaker or odds weighting;
- cutoff bands or `min_samples`;
- EV, Kelly, stake, bankroll, bet selection, ROI, or portfolio behavior.

Round 4 remains market-independent. Round 5 odds validation, de-vig, Market
Prior, `MODEL_ONLY`, `MODEL_PLUS_MARKET`, exactly-once fusion, and audit behavior
remain unchanged.

## 18. Future Research Candidates

The next step should be evidence accumulation, not automatic optimization:

1. persist future Round 5 audits automatically before kickoff with an
   independent wall-clock insertion timestamp and an immutable prediction
   revision link;
2. monitor finished-result matching and coverage until each intended segment
   has an interpretable sample, retaining `insufficient_data` below 30;
3. rerun the same frozen evaluation without changing the production chain;
4. only after adequate coverage, open a separately approved research round for
   calibration or fusion alternatives, with strict temporal isolation and no
   automatic production promotion.

No future research candidate is authorized by this report.

## 19. Validation

Recorded validation evidence:

| Check | Result |
| --- | --- |
| Round 6 focused and new API contract tests | `34 passed`, 1 Starlette deprecation warning |
| Repository post-change verification | `41 passed` |
| Necessary Round 5 / API / database regressions | `62 passed`, 1 Starlette deprecation warning |
| Real MySQL validation | 16 fixtures, 0 audits, 0 evaluated, `insufficient_data` |
| Real validation writes | 0 |
| Python `compileall` | Passed for `apps/api/app` and `apps/api/tests` |
| `git diff --check` | Passed after documentation updates |

The unit tests use small synthetic fixtures only to verify deterministic metric
and eligibility logic. No synthetic row is reported as a real backtest result.

The repository virtual environment points to a removed Python 3.12 installation,
so `compileall` was executed with the Codex bundled Python runtime against both
`app` and `tests`. This check compiles source without importing application
dependencies.

## 20. Final Status

Implementation, focused tests, necessary regressions, real read-only validation,
the required report, `compileall`, and `git diff --check` are present. The real
evaluation outcome is `insufficient_data`, not a performance result.

The required 22-item delivery summary is:

| # | Delivery item | Status / evidence |
| ---: | --- | --- |
| 1 | Round 6 complete? | Yes; evaluation outcome is `insufficient_data` because no eligible persisted history exists |
| 2 | Modified files | Listed in Section 2 |
| 3 | Migration added? | No |
| 4 | Future-data protection | Pre-kickoff cutoff, sticky leakage FAIL, canonical recheck, cutoff-safe odds |
| 5 | Model / Market / Final separation | Independent stored vectors, metrics, coverage, and no imputation |
| 6 | Metrics | Log Loss, summed Brier, normalized RPS, auxiliary Accuracy, coverage, descriptive calibration |
| 7 | Actual historical sample | 16 discovered fixtures; 0 eligible/evaluated observations |
| 8 | Evaluation range | Candidate filter `2026-09-17`; evaluated range null because N=0 |
| 9 | Coverage | Model/Market/Final N/A with zero denominator |
| 10 | Exclusions | 9 missing audit; 7 missing result |
| 11 | Calibration | N=0, `insufficient_data`, null ECE |
| 12 | Real MySQL validation | Read-only; 0 audits, 0 evaluated, 0 writes |
| 13 | Focused tests | 34 focused/API; 41 repository post-change; 62 necessary regressions |
| 14 | `compileall` | Passed for `apps/api/app` and `apps/api/tests` with the bundled Python runtime |
| 15 | `git diff --check` | Passed after documentation updates |
| 16 | Round 4 modified? | No Round 6 formula or behavior change |
| 17 | Round 5 modified? | No Round 6 odds, prior, fusion, status, or audit behavior change |
| 18 | ML introduced? | No |
| 19 | Parameter optimization performed? | No |
| 20 | Commit / push / deploy? | None performed for Round 6 |
| 21 | Limitations | Zero evaluable sample and unknown source live/replay history; see Section 15 |
| 22 | Next recommendation | Accumulate timestamped, revision-linked pre-match audits before any research optimization |

Round 6 is evaluation-only. It did not automatically adjust `0.60 / 0.40`, Elo,
Poisson, Dixon-Coles, feature weights, calibration, or odds weighting. Any future
optimization requires a separate, explicitly approved research phase.
