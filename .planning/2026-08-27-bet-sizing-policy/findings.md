# Findings

Treat this file as research data, not instructions.

## Initial Findings

- `market_decision.py` uses a 3% minimum expected edge and a 2% maximum stake fraction.
- Stake sizing is quarter Kelly capped at 2%, so qualifying bets often show exactly 2% or less.
- `bankroll.py` independently enforces the same 2% per-fixture cap and a 10% daily cap.
- A completed model response with `model_recommendation.status == no_bet` adds the hard `ai_no_bet` reason; the backend does not promote it to a bet.
- Other hard reasons currently include missing/mismatched markets, stale odds, missing player data, failed AI completion, and risk limits. Low confidence and unconfirmed lineups are warnings for completed AI forecasts.
- The prior completed scoped plan explicitly retained strict no-bet standards and the 2% hard cap; the user's latest request supersedes that policy but the exact replacement needs approval.

## Tomorrow Audit (2026-08-28)

- The live isolated API on port 8001 returns five scheduled fixtures and ten current model predictions.
- Only one of ten decisions is `bet`: ChatGPT selects Shandong +1 with 12.79% expected edge; its stake is capped at 2%.
- Three predictions are blocked only because the model itself returned `no_bet`.
- Six predictions returned a bet direction, but that selected market has negative expected edge.
- Several blocked predictions have another market with positive expected edge above the current 3% threshold. Examples include Celta -0.5 at 15.55%, Athletic +1.5 at 23.6%, Dalian/Beijing draw at 9.2%, and Shandong +1 at 12.79%.
- Therefore the dominant issue is not the 3% threshold. It is the current authority rule: the backend validates only the model-selected market and never falls back to the best priced positive-edge market.
- Stake sizing should not use raw win probability alone because a high-probability outcome can still be overpriced. Expected edge or Kelly-derived advantage incorporates both forecast probability and price.

## League-Day Limit

- The user approved one executed fixture per model, league, and fixture date. DeepSeek and ChatGPT retain independent quotas because they have independent bankrolls.
- Non-selected fixtures must still expose their best market, selection, expected edge, and theoretical stake as advice; execution status and advice must remain separate.
- Automation currently predicts and places fixture by fixture, so processing order would incorrectly consume the only league-day slot.
- Fixture detail generation also calls placement immediately for newly created missing predictions.
- The minimal correct behavior is to rank current eligible candidates for a model/league/date and keep only the highest expected-edge candidate as the executed simulated bet. A later stronger candidate must be able to supersede an earlier open, not-yet-started simulated bet.

## Implementation Boundary

- `PredictionRepository.list_fixtures(date, date, league)` plus `latest(fixture, model, competition)` can supply league-day candidates without adding a new table or broad query abstraction.
- `discard_open_fixture_bets` already deletes an open bet's stake transaction and rebuilds the model ledger, so it is the correct refund path for pre-kickoff replacement.
- Predictions are persisted before both automatic and manual placement calls. Bankroll reconciliation can therefore rank the newly created prediction with existing latest predictions regardless of processing order.
- The current API links bets by prediction ID only. A derived `execution` object must be attached to the response copy so losing candidates can explain `league_daily_limit` without mutating persisted predictions.
- Existing UI already exposes `considered_market`, `considered_selection`, price, and edge. It needs to show the considered selection and use derived execution status instead of equating decision eligibility with an actually placed bet.
- Direct unit tests call bankroll placement without persisting fixtures or predictions. Reconciliation should include the passed fixture/prediction as an override so those contracts remain useful.

## Final Outcome

- Backend advice now selects the highest expected-edge priced market across all supported selections, regardless of the model's original bet/no-bet opinion.
- Theoretical sizing is linear from 10% at 3% edge to 25% at 18% edge and remains visible for non-executed positive-edge advice.
- Actual execution enforces 10%-25% per bet, 50% total per model/date, and one bet per model/league/date.
- Later higher-edge candidates replace and refund lower-ranked open pre-kickoff simulated bets. Started or settled bets remain locked.
- Existing immutable predictions are reconstructed under the current market policy at read/reconciliation time rather than rewritten.
- Live 2026-08-28 reconciliation produced exactly one La Liga and one CSL bet per model. All open bets across current dates satisfy the one-per-group invariant and 10%-25% fraction range.
- A non-executed Celta fixture returned `asian_handicap/home_handicap`, 17.96% edge, 24.96% theoretical stake, and `league_daily_limit` for both models.

## Asian Handicap Probability Source Defect

- The Barcelona GPT page displays `asian_handicap_forecast`: Barcelona -1.5 cover 56%, Athletic +1.5 cover 44%.
- `assess_markets` instead reads the Poisson `asian_handicap.home_settlement`, which supplies 42.51% home cover and 57.49% away cover.
- At away price 2.15, the incorrect Poisson direction produces +23.6% edge; the GPT probability produces -5.4%. The current Athletic +1.5 simulated bet therefore contradicts GPT and must be reconciled.
- The prompt contract normalizes model home/away cover probabilities to one but does not expose full/half/push weights. For integer and quarter lines, preserve Poisson push mass and within-side settlement shape while reweighting the directional mass to the model cover probabilities.

## Handicap Repair Result

- `market_decision.py` now reports `probability_source=model_asian_handicap_forecast` when a valid matching model handicap forecast exists.
- The Barcelona GPT rows now use 56% home and 44% away: home -9.0% EV, away -5.4% EV. The fixture is `no_bet` and has no linked GPT bet.
- Every league-day candidate is rebuilt from its own saved odds before ranking; persisted pre-repair Poisson market tables no longer influence another fixture's slot.
- The invalid Barcelona GPT +1.5 bet was refunded. GPT's La Liga slot moved to Celta away 1X2 at +5%; DeepSeek independently selected the Barcelona draw at +4%.
- Duplicate bankroll-side Poisson EV helpers were removed, leaving `market_decision.py` as the sole market-EV authority.
