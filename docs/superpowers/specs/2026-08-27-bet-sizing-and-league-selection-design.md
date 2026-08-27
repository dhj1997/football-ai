# Bet Sizing and League-Day Selection Design

## Goal

Increase useful simulated-bet coverage without lowering the existing price-value threshold. Each model should calculate advice for every scheduled fixture, while executing at most one simulated bet per league and fixture date. Executed stakes start at 10% of the model's available balance and scale with expected edge up to 25%.

## Current Problem

The backend validates only the market selected by the model. A model-level `no_bet` veto or a negative-edge model selection blocks execution even when another priced market has a positive edge. The current quarter-Kelly calculation and bankroll layer both cap a fixture at 2%.

The 2026-08-28 live audit found one executed bet across ten model predictions. Several blocked predictions had alternative markets above the existing 3% edge threshold. The primary issue is market-selection authority, not the threshold itself.

## Decision Policy

For each completed model forecast, the backend evaluates every available 1X2 and Asian-handicap selection and identifies the row with the highest expected edge.

The model's original betting opinion remains visible as analysis, but it is advisory. It no longer vetoes the deterministic backend decision or restricts the backend to the model's selected market.

The existing 3% minimum expected edge remains. Missing or stale odds, failed AI completion, insufficient required player data, an unavailable matching market, and exhausted risk limits remain hard no-bet conditions.

Every prediction exposes backend advice even when no simulated bet is executed:

- suggested market and selection;
- current price and expected edge;
- theoretical stake fraction;
- execution status and reason codes.

When all available rows have edge below 3%, the highest-edge row remains the observation suggestion and execution stays `no_bet`. When no reliable priced row exists, the model's forecast outcome remains the directional suggestion, but the product explicitly marks priced market advice as unavailable instead of fabricating one.

### Asian Handicap Probability Authority

Each model's `asian_handicap_forecast` is the directional probability authority for that model's Asian-handicap EV. The backend must not display the model's cover probabilities while silently pricing the market with the Poisson baseline.

The current model contract supplies normalized home/away cover probabilities but not a complete full-win, half-win, push, half-loss, and full-loss distribution. The backend therefore combines the two sources narrowly:

- the model forecast determines the positive-versus-negative probability split;
- the Poisson settlement distribution preserves the push mass and the internal full/half result shape required by integer and quarter lines;
- the resulting settlement weights are used for expected-return calculation;
- the market table's model probability remains the model's stated cover probability;
- the backend falls back entirely to Poisson only when the model forecast is unavailable, incomplete, or does not match the priced handicap line.

For a half-goal line such as `-1.5`, there is no push or half result, so the calculation reduces directly to the model's binary probabilities. A 44% away-cover forecast at price 2.15 has `44% * 2.15 - 1 = -5.4%` edge and cannot qualify under the 3% threshold.

Existing pre-kickoff simulated bets are reconciled with the corrected probability source. A bet that no longer qualifies is refunded through the existing ledger and the league-day slot is recalculated. Started and settled bets remain immutable.

## Stake Sizing

For an eligible candidate, percentages are expressed as decimal fractions in code:

```text
theoretical_stake = clamp(10% + max(expected_edge - 3%, 0), 10%, 25%)
```

Examples:

- 3% edge -> 10% stake;
- 12.79% edge -> 19.79% stake;
- 18% or greater edge -> 25% stake.

The stake is calculated from the model account's current available balance. The per-model daily exposure cap increases from 10% to 50%. If the remaining daily allowance or available balance cannot fund at least 10%, execution is skipped rather than placing a smaller bet.

## League-Day Selection

The execution quota key is `(competition_id, model_key, league_key, fixture_date)`. Each key may have at most one placed simulated bet.

All latest eligible predictions in a quota group are ranked by:

1. expected edge, descending;
2. forecast confidence, descending;
3. kickoff, ascending;
4. fixture ID, ascending.

The top candidate receives the league-day slot. Other fixtures retain their advice and use a `league_daily_limit` execution reason.

Prediction processing order must not decide the winner. Automatic prediction runs and on-demand prediction creation both invoke the same reconciliation behavior. If a later forecast becomes the top candidate, it may replace a lower-ranked placed bet only while the old fixture has not started. Replacement discards the old simulated bet, refunds its stake through the existing transaction ledger, and then places the new bet. Started or settled bets are never replaced.

## Components and Data Flow

`market_decision.py` owns best-market selection, eligibility reasons, and theoretical stake calculation. Its persisted output is immutable advice, not the mutable portfolio result.

`bankroll.py` owns account limits and league-day reconciliation. It reads the latest predictions for the same model, league, and date, ranks eligible candidates, preserves only the winner, and enforces the 10%-25% fixture range and 50% daily cap.

The repository supplies scoped prediction/bet queries and reuses its existing discard/refund transaction behavior. No new real-money integration or external provider is introduced.

The fixture API continues returning model analysis and deterministic advice. It adds a derived `execution` envelope for the current prediction: `status`, linked bet when present, and execution reason codes such as `league_daily_limit` or `risk_limit`. This envelope is calculated from current bets and quota state without rewriting immutable prediction versions.

The web match panel shows the suggested direction and theoretical stake for all predictions, then separately labels whether a simulated bet was executed and why.

## Failure Behavior

- A failed or incomplete model forecast cannot execute a bet.
- Missing or stale odds cannot execute a bet and do not produce fabricated market advice.
- A candidate below 3% edge remains an observation suggestion with zero executed stake.
- A valid candidate that loses the league-day ranking keeps its theoretical stake; its derived execution state receives `league_daily_limit`.
- Insufficient daily allowance produces `risk_limit`; no sub-10% bet is placed.
- Reconciliation failures leave the existing placed bet intact and surface through the existing job error handling.

## Focused Verification

Tests cover:

- best positive-edge market selection despite model `no_bet` or a negative-edge model pick;
- model Asian-handicap cover probabilities overriding the Poisson direction while retaining required push/full/half settlement shape;
- Poisson fallback when the model handicap forecast is unavailable or line-mismatched;
- the linear 10%-25% stake formula and 50% daily cap;
- refusal to place a sub-10% bet;
- one bet per model, league, and date;
- deterministic ranking and pre-kickoff replacement/refund;
- no replacement after kickoff or settlement;
- retained stale-odds, missing-data, failed-AI, and below-threshold behavior;
- API/UI exposure of advice plus derived execution state for non-executed fixtures.

Verification remains focused on the affected API tests, web type/lint checks, and the current tomorrow-fixture workflow.

## Out of Scope

- Real-money betting or bookmaker integration;
- changing the 3% minimum expected-edge threshold;
- changing forecast probability generation;
- unrelated bankroll, settlement, evidence, or visual redesign work.
