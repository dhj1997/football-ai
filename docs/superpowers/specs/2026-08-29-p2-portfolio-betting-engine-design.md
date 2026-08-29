# P2 Portfolio / Betting Engine Design

## Scope

Implement the P2 deterministic portfolio and paper-betting layers on top of the existing P0/P1 prediction, odds, market-decision, bankroll, and settlement code. The change stays on the `main` branch, does not modify the frontend, does not connect to a real bookmaker, and must not mutate frozen prediction data.

## Architecture

The runtime flow is:

`Prediction -> Signal -> BetCandidate -> Risk Gate -> Portfolio -> Stake -> Paper Execution -> Settlement -> Forecast/Betting Performance`

`apps/api/app/portfolio.py` will own pure value objects and deterministic calculations:

- `BetCandidate` contains fixture/prediction/model identity, market selection and line, frozen odds, model and market probabilities, edge, EV, confidence, data quality, odds age, historical CLV, risk score, correlation group, and a transparent ranking score.
- Candidate creation reuses `market_decision.py` market rows and derives `edge = model_probability - market_probability` and `ev = model_probability * odds - 1`.
- Candidate eligibility requires completed AI evidence, complete-enough data, fresh odds, `edge >= min_edge`, `ev >= min_ev`, and a passing risk gate.
- Portfolio selection sorts by deterministic configured score and accepts at most one candidate per fixture correlation group, then applies league, daily, and total exposure limits.
- Stake allocation uses a configured fixed bankroll fraction and clamps it by every remaining exposure limit. Kelly is intentionally out of scope.

`BankrollService` remains the orchestration boundary. Its existing `_league_day_candidates` behavior will be routed through the portfolio layer, while legacy method and payload fields remain readable. New placement metadata is derived from the candidate and never written back into the prediction.

## Configuration

The existing settings model will expose P2 defaults without hard-coding policy in the service:

- `min_edge = 0.05`, `min_ev = 0.05`
- `max_odds_age_minutes = 180`
- `stake_fraction = 0.01`
- `max_single_bet_fraction = 0.01`
- `max_daily_exposure = 0.05`
- `max_league_exposure = 0.02`
- `max_total_exposure = 0.10`
- `max_drawdown = 0.30`
- deterministic score weights for EV, edge, confidence, data quality, historical CLV, odds freshness, and risk penalty

The constructor remains compatible with existing tests and callers; application wiring passes the configured policy explicitly.

## Execution Ledger

Add an idempotent `bet_executions` table with `execution_id` as the primary key and a unique prediction/selection execution identity. It stores fixture/prediction/model/market/selection/line, frozen odds and stake, request and execution times, source, and status (`PENDING`, `EXECUTED`, `CANCELLED`, `REJECTED`, `SETTLED`). Settlement may only add result, profit/loss, settled time, and CLV metadata. Existing `bets` and bankroll transactions remain the compatibility/accounting surface.

## API and performance

Existing API routes remain available. Bankroll, bets, fixture detail, and decision responses gain derived candidate/risk/exposure/execution fields where available. Forecast metrics remain separate from betting metrics; betting metrics report bet count, wins/losses, stake, profit, ROI, average CLV, and maximum drawdown. No frontend changes are included.

## Safety and errors

- A failed risk gate always produces zero allowed stake and no execution.
- Freshness is evaluated from capture/update timestamps; settlement never reloads current odds to replace frozen execution odds.
- Drawdown at or above the configured maximum blocks new paper executions.
- Same-fixture candidates are correlated by `fixture_id`; only the highest-ranked candidate is selected in the first version.
- SQLite and MySQL migrations are additive and idempotent; no historical rows are deleted or rebuilt.

## Verification

Add focused tests for Edge, EV, candidate thresholds, risk-gate zero stake, single/day/league/total limits, fixture correlation, frozen execution fields, CLV, and drawdown. Run the affected API tests, then the complete API suite plus frontend lint/build, migration idempotence, and `git diff --check`.
