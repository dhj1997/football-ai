# Football AI v2 Round 4 Report

## 1. Round 4 Summary

Round 4 adds one deterministic, market-independent probability path:

`Feature Snapshot -> Expected Goals -> Poisson -> Dixon-Coles -> Score Matrix -> 1X2/O-U/BTTS`

The path is read-only, consumes only a persisted Round 3 Feature Snapshot, and
does not call fitted models, learned weights, market odds, or an LLM numeric
predictor.

## 2. Probability Engine Architecture

`TransparentProbabilityEngine` validates the snapshot identity, version,
leakage audit, and every feature cutoff before indexing the required home and
away inputs. It then computes expected goals, builds a normalized score matrix,
derives market-independent probability aggregates, and emits a read-only
explanation plus a probability audit.

The API surface is `GET /match/{fixture_id}/probability`. It does not persist a
new prediction or change the existing revision chain.

The route evaluates the latest append-only leakage audit for each snapshot; a
later FAIL cannot be masked by an earlier PASS.

Files changed for this round:

- `apps/api/app/probability_engine.py`
- `apps/api/app/main.py`
- `apps/api/tests/test_round4_probability_engine.py`
- `docs/AI_ROUND4_REPORT.md`
- `.planning/2026-09-16-football-ai-v2-round4/*`

## 3. Expected Goals Formula

For each team, attack and defense values are bounded. Defense is converted to
an opponent factor with `inverse(defense_strength)`. Missing or out-of-range
values use the documented neutral value `1.0` and lower `model_input_quality`.

Let `e = clamp((elo_home - elo_away) / 400, -1, 1)`:

```text
lambda_home = clamp(
  1.35 * 1.08 * attack_home * inverse(defense_away)
  * (1 + 0.10 * e)
  * (1 - 0.08 * fatigue_home)
  * (1 + player_impact_home),
  0.15, 4.50
)

lambda_away = clamp(
  1.10 * attack_away * inverse(defense_home)
  * (1 - 0.10 * e)
  * (1 - 0.08 * fatigue_away)
  * (1 + player_impact_away),
  0.15, 4.50
)
```

The total expected goals value is the sum of the two lambdas.

## 4. Elo Integration

Elo contributes only the bounded differential `e` above. It is read from the
feature snapshot, never recomputed from raw tables by the probability engine,
and has a fixed weight of `0.10`.

## 5. Attack / Defense Strength

Raw attack and defense strengths are accepted only in `[0.25, 4.0]` and then
clamped to `[0.67, 1.50]`. A defense strength is used as
`clamp(1 / defense_strength, 0.67, 1.50)`. Invalid values are represented in
the quality fallback list instead of being silently trusted.

## 6. Poisson Implementation

Each side uses the deterministic Poisson probability
`P(k) = exp(-lambda) * lambda^k / k!`. The matrix uses exact goal buckets
`0..9` and one `10+` tail bucket. The tail is the residual mass, followed by a
final normalization reconciliation for stable serialized sums.

## 7. Dixon-Coles Implementation

The fixed `rho` is `-0.10`. The correction is applied only to exact low-score
cells `(0,0)`, `(0,1)`, `(1,0)`, and `(1,1)`; the `10+` tail is not treated as
an exact score. The corrected matrix is normalized again, and negative or
non-finite factors are rejected.

## 8. Score Probability Matrix

The output contains 121 rows (`11 x 11`) with numeric goal buckets, labels,
independent probability, and the Dixon-Coles factor. The matrix is the single
source for all downstream aggregates and top scorelines.

## 9. 1X2 Calculation

Home, draw, and away probabilities are sums of matrix cells where home goals
are respectively greater than, equal to, or less than away goals. They are
normalized and exposed both as named fields and in `probabilities`.

## 10. Over / Under Calculation

For lines `0.5`, `1.5`, `2.5`, and `3.5`, `over` is the matrix mass whose total
goals exceed the line; `under` is the residual `1 - over`.

## 11. BTTS Calculation

`yes` is the matrix mass where both goal buckets are positive, including a
`10+` bucket. `no` is the residual `1 - yes`.

## 12. Parameter Configuration

All parameters are held in the immutable `ProbabilityModelConfig`:

| Parameter | Value |
| --- | ---: |
| Home baseline goals | 1.35 |
| Away baseline goals | 1.10 |
| Home advantage multiplier | 1.08 |
| Elo weight | 0.10 |
| Fatigue weight | 0.08 |
| Player impact bounds | -0.20 to 0.20 |
| Lambda bounds | 0.15 to 4.50 |
| Dixon-Coles rho | -0.10 |
| Exact goal buckets | 0 through 9, plus 10+ |

No parameter is fitted from historical outcomes in this round.

## 13. Versioning

The current versions are:

- `probability_model_version`: `poisson-dc-v2.0.0`
- `calculation_version`: `round4-probability-engine-v1`
- `feature_version`: `round3-feature-engine-v2`

The serialized configuration also exposes a deterministic `config_hash`. A
formula change requires a new model or calculation version.

## 14. Cutoff Safety

The engine accepts only a persisted Feature Snapshot. It requires a real
snapshot ID, a valid snapshot cutoff, a matching feature version, and a
`prediction_cutoff_at` on every feature row. Every row cutoff must equal the
snapshot cutoff, and every non-missing value must have a parseable
`available_at` no later than that cutoff. Missing row cutoffs, mismatches, and
future timestamps fail closed.

## 15. Leakage Validation

Production calculation requires `leakage_detected == false` and a mapping
`leakage_check` with `passed == true` and an empty `violations` sequence.
If present, the audit status must be `PASS` and
`rejected_future_fields` must be empty.
Future, unverifiable, or calculation-failed feature rows are rejected. This
keeps the existing `LeakageAuditService` and its persisted audit chain as the
source of truth.

## 16. Reproducibility

The result is deterministic for the tuple:

`match_id + prediction_cutoff_at + feature_snapshot_id + feature_version + probability_model_version + calculation_version + config_hash`

There is no random seed, Monte Carlo sampling, runtime market input, or LLM
numeric output. Replaying the same snapshot returns byte-equivalent Python
payloads in the focused test.

## 17. Real Data Validation

A read-only check evaluated the three most recent Round 3.5 audit-passed
snapshots (112 feature rows each):

| Fixture | Snapshot | Lambda home | Lambda away | Matrix sum | 1X2 sum | Quality | Fallbacks |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| `sportsdb-2506219` | `feature:9b381caf...` | 1.44236842 | 1.51484030 | 1.0 | 1.0 | degraded | 2 |
| `sportsdb-2506222` | `feature:c2ad0625...` | 1.13271731 | 1.10146442 | 1.0 | 1.0 | degraded | 2 |
| `sportsdb-2506220` | `feature:6da8f4f0...` | 3.24938597 | 0.72698851 | 1.0 | 1.0 | degraded | 3 |

The last fixture contains the known extreme defense-strength source value; the
engine used its explicit neutral fallback and did not use the unbounded value.
No write operation or automation task was started.

## 18. Test Results

Focused verification passed:

```text
tests/test_round4_probability_engine.py
tests/test_p10_model_platform.py
24 passed in 0.18s
```

The existing API regression suite also passed:

```text
tests/test_api.py
26 passed in 4.28s (1 existing dependency warning)
```

The Round 4 tests cover Poisson normalization, score-matrix normalization,
Dixon-Coles bounds, 1X2/O-U/BTTS totals, cutoff rejection, leakage fail-closed
behavior, snapshot identity, feature-version boundaries, reproducibility,
explanation isolation, and the no-ML numeric gate.

`python -m compileall` and `git diff --check` passed.

## 19. Known Limitations

Round 4 intentionally does not implement:

- Market Prior or odds fusion
- Learned or fitted calibration
- ML, training, or parameter optimization
- LLM numeric prediction
- EV, staking, Kelly, bankroll, or bet selection
- Historical performance backtest
- Live prediction
- New persistence tables or a parallel Feature Store

Quality is an input-data state, not a learned accuracy claim. The three real
fixtures are a correctness smoke check only; they do not establish accuracy,
ROI, or superiority to a market.

## 20. Round 5 Boundary

Round 4 stops after deterministic probability calculation and bounded real-data
validation. No Round 5 implementation was started. Any next round requires a
separate authorization and must retain the strict no-ML architecture,
point-in-time snapshots, append-only audit history, and explicit versioning.
