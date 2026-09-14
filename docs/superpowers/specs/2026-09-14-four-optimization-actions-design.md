# Four Betting Quality Optimizations

## Status

Approved design for implementation on 2026-09-14.

## Context

The project already stores independent LLM and Poisson probabilities, runs a
P10 train/validation/test ensemble protocol, and has a P14 auditable research
pipeline. The requested follow-up is to make those controls operational while
keeping the current prediction and execution provenance boundaries intact.

The current portfolio default requests 10% of equity and the automation path
can bypass the single-bet fraction when a fixed amount is supplied. LLM
probabilities are also compared directly with market probabilities even when
the model is overconfident. Finally, the research report is centered on
ensemble-vs-naive metrics and does not directly compare each LLM with Poisson
on realized betting outcomes.

## Goals

1. Run learned ensemble weighting with Poisson and completed LLM members while
   preserving the existing sample and promotion gates.
2. Shrink LLM probabilities toward the point-in-time de-vig market prior only
   at portfolio candidate scoring time.
3. Add a pre-registered, read-only confirmatory report comparing LLM and
   Poisson after at least 30 settled Football-Data samples.
4. Enforce a short-term simulated stake policy of a 1% default and a hard 2%
   single-bet cap, including automation fixed-stake requests.

## Non-goals

- Do not mutate frozen prediction probabilities, settlement metrics, or the
  historical payload used for model evaluation.
- Do not promote a model from the confirmatory report.
- Do not add real-money execution, dynamic optimization of the 0.7 shrinkage
  weight, or unrelated provider/UI refactors.

## Design

### 1. Learned Ensemble Runtime

`AutomationRunner._learn_ensemble_weights` remains the training entry point.
Its dataset gate will require a Poisson baseline and at least one completed LLM
probability per usable fixture, and its result will continue through
`run_model_protocol`'s chronological splits. A learned record remains a
candidate until the existing test-sample and positive Brier-improvement gates
pass; only then may it become the `ensemble` champion.

The live P3 ensemble reader will use the champion's stored weights when one is
available and otherwise use the existing defaults. The response will expose
`weights_source` and the effective member weights so operators can distinguish
learned behavior from fallback behavior. No prediction payload is rewritten.

### 2. Portfolio-Only LLM Shrinkage

Add a pure portfolio helper that accepts normalized LLM probabilities, complete
1X2 odds, and `llm_keep_weight` (default `0.7`). It computes:

```
p_shrunk = 0.7 * p_llm + 0.3 * p_market_devig
```

and renormalizes the result. The helper is called while constructing LLM
market candidates, before edge/EV/score calculations. The stored prediction's
`model_probabilities` remains unchanged. Candidate and execution metadata
carry `shrinkage_applied`, `original_model_probability`,
`market_probability`, `shrinkage_weight`, and the bound `odds_snapshot_id`.

The market prior must come from the prediction's bound odds snapshot (or its
point-in-time equivalent supplied by the caller). Missing, malformed, or
incomplete odds cause a no-op with `shrinkage_applied=false`; the original
probability remains auditable and no synthetic market prior is created.

### 3. Confirmatory LLM-vs-Poisson Research

Extend the research layer with a fixed comparison operation that consumes
settlement rows carrying both an LLM probability and a Poisson baseline for the
same fixture. Rows are restricted to the Football-Data source marker when one
is present; rows without provenance are reported as unavailable rather than
silently mixed into the FD sample.

The operation is content-addressed and read-only. It pre-registers the
hypothesis and selection rule, requires at least 30 paired settled fixtures,
and returns `insufficient_sample` below that threshold. At or above the
threshold it reports per-model Brier, log loss, hit rate, and sample count;
ROI and CLV are included only for rows with a complete frozen execution chain,
with an explicit unavailable status otherwise. Existing chronological split
and leakage-audit results remain mandatory. The report never changes registry
status or live weights.

Expose the comparison through the existing admin research endpoint and add a
daily automation check that is idempotent: before 30 eligible rows it records
the gate status without creating a misleading success conclusion; once the
gate is met it archives one immutable run for the fixed hypothesis.

### 4. Short-Term Stake Discipline

Change the default portfolio request to `0.01` and the default single-bet cap
to `0.02`. Keep the existing daily, league, total-exposure, and drawdown gates.
Remove the automation-only replacement that sets `max_single_bet_fraction=1.0`.
Fixed stake requests therefore pass through the same `risk_gate` and are
clamped to at most 2% of current equity. A 0.5% lower bound is documented as
the recommended operating range but is not forced when exposure or eligibility
gates allow less; no bet remains a valid result.

## Failure Handling

- Missing LLM or Poisson members: register an insufficient-sample result and
  do not promote.
- Missing odds snapshot: preserve the LLM probability and mark shrinkage as
  not applied.
- Fewer than 30 paired FD settlements: return a non-conclusive report with no
  model-selection conclusion.
- Incomplete execution chain: report prediction metrics but mark ROI/CLV
  unavailable.
- Risk gate failure: place no bet and preserve reason codes.

## Testing

Add focused tests for:

- learned ensemble member/sample gates and champion/default weight source;
- exact LLM shrinkage math, normalization, missing-market no-op, and frozen
  prediction preservation;
- paired LLM-vs-Poisson metrics, the 30-row gate, FD provenance, idempotency,
  and leakage failure;
- dynamic and fixed stake requests capped at 2%, while existing exposure gates
  still apply.

Run the focused API tests, Python compilation, and available static checks.
If the current runtime lacks `pytest`, record that limitation rather than
claiming the tests ran.

## Rollout and Verification

Verify the final runtime through API responses and stored rows: learned versus
default ensemble source, shrinkage metadata and unchanged prediction payload,
research gate/report status, and actual selected stake fraction. Push the
resulting commits to `origin/main` only after the local worktree and tests are
reviewed.
