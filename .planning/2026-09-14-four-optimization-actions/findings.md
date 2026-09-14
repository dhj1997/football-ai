# Findings and Decisions

## Requirements

- Run the existing ensemble learning workflow using Poisson as a model input and keep promotion sample-gated.
- Shrink LLM probabilities toward the de-vig market prior in portfolio scoring only.
- Produce a confirmatory comparison after at least 30 settled fd-history samples: LLM versus Poisson, with Brier and ROI/CLV where execution data exists.
- Keep current short-term simulated stake discipline at 0.5-2%, with no interpretation of +11% ROI as proof of system edge while CLV is near zero.

## Initial Research

- `automation.py` already has `_learn_ensemble_weights`, which reads settled rows and registers a candidate/champion after protocol gates.
- `model_platform.py` already defines Poisson, LLM, and ensemble model contracts.
- `portfolio.py` has `baseline_market_shrinkage` and the new `llm_keep_weight` field, but no LLM shrinkage behavior yet.
- `bankroll.py` already shrinks Poisson fallback probabilities toward market odds and owns candidate placement/risk gates.
- `backtest_engine.py` already computes walk-forward ensemble metrics and confidence intervals.
- `research_engine.py` and settlement persistence must be checked for a reusable model comparison contract.
- Current default portfolio stake is 10%; automation has a fixed-stake override, so both paths need a single cap.

## Detailed Contracts

- `DualPredictionService.create` persists each model's frozen `model_probabilities`, adds the Poisson baseline to `base_predictions`, and computes the P3 ensemble. It does not yet use a learned registry artifact during live prediction creation.
- `AutomationRunner._learn_ensemble_weights` is already scheduled when a model registry service is present, but it registers every learned result as `candidate` and only promotes when the existing protocol reports at least 30 test samples plus positive naive-baseline Brier improvement.
- `weighted_ensemble` already accepts explicit registry weights and renormalizes weights for available members; this is the safest live integration point.
- `build_backtest_rows` groups settlement rows by fixture and preserves non-Poisson model probabilities plus the Poisson baseline. It currently exposes no direct per-model strategy ROI comparison.
- `Research Engine` has a confirmatory hypothesis/selection-rule contract and a 30-row sample status, but its report is hard-coded around ensemble-vs-naive metrics.
- `risk_gate` computes the final allowed stake. `select_portfolio` passes `requested_stake` through it, while `BankrollService._place_portfolio_candidate` currently replaces `max_single_bet_fraction` with `1.0` for automation fixed stakes.

## Technical Decisions

| Decision | Rationale |
|---|---|
| Use one portfolio helper for LLM shrinkage | Prevents prediction payload mutation and keeps the point-in-time market requirement explicit |
| Make confirmatory research an explicit read-only report/job | Avoids silently promoting a model based on a small or cherry-picked sample |
| Apply the 2% cap after fixed-stake and dynamic sizing | Ensures automation cannot bypass the short-term discipline |

## Open Questions Resolved

- User delegated the stake-policy choice; selected default 1% with configurable range capped at 2%.

## Current Implementation Findings

- `DualPredictionService.create` builds `base_predictions` and calls `weighted_ensemble` without registry weights; the runtime `/api/ensemble/{fixture_id}` path already reads the ensemble champion payload.
- `candidate_from_market_row` is the shared portfolio scoring boundary. It currently trusts `market_row.model_probability`, so LLM shrinkage belongs here and must leave the persisted prediction untouched.
- `BankrollService._place_portfolio_candidate` replaces `max_single_bet_fraction` with `1.0` for automation fixed stakes; this bypasses the intended short-term cap and must be removed.
- `market_decision.py` still exposes legacy 10%-25% stake constants, while `PortfolioConfig`/settings remain 10%-25%; visible decision metadata must be synchronized to 1%-2%.
