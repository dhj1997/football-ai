# P2.1 Portfolio Engine Cleanup Design

## Scope

Consolidate the production betting path around the existing deterministic Portfolio Engine. This cleanup removes the old BankrollService stake/exposure policy from production, centralizes account money semantics, and verifies global cross-model fixture selection. It does not change P0/P1 prediction, settlement, CLV, calibration, or prediction-freeze behavior. It does not add Kelly, real bookmaker execution, or new models.

## Single policy boundary

`BankrollService` will always receive a `PortfolioConfig` and delegate candidate eligibility, ranking, risk checks, portfolio selection, and stake allocation to `portfolio.py`. The old 10%-25% stake floor/cap, 50% daily exposure, and 0.03 execution threshold will be removed from its production code. The `market_decision` layer may continue to emit its existing upstream decision signal for P0/P1 compatibility, but Portfolio alone decides whether a bet is executable.

## Canonical account semantics

`portfolio.py` will expose the only shared account helpers:

- `active_bet_statuses` is the single set used by all exposure calculations.
- `cash_balance` is the sum of the account's append-only bankroll transactions.
- `open_exposure` is the sum of stakes for active bets in that account.
- `equity = cash_balance + open_exposure`.
- `exposure_snapshot` derives daily, league, and total active stake from the same account rows and the same equity base.

Stake allocation receives this snapshot, calculates one requested stake from equity, clamps it once against all remaining limits, and passes the resulting amount to persistence. It must not add open exposure to the bankroll a second time or count a stake twice.

## Global candidate selection

`select_best_candidates` will sort all model candidates using the existing deterministic candidate score, then EV, edge, model key, and prediction id as stable tie-breakers. It will keep one candidate per `fixture_id`/`correlation_group`, so DeepSeek, GPT, and Poisson candidates for one fixture cannot create multiple bets. Existing league/day/total limits then operate on the selected candidates.

The current sequential model orchestration will use the same global correlation rule when checking an existing portfolio. Poisson remains an input candidate only; no new prediction row or model is introduced.

## Persistence and API

Existing `bets` and `bet_executions` persistence remains unchanged except for consuming the canonical stake/exposure result. Prediction and settlement payloads remain immutable in their existing fields. API output may expose the canonical account snapshot and selected candidate metadata; frontend files remain untouched.

## Verification

Add focused tests for the canonical cash/equity/exposure functions, every active status, zero/double-count edge cases, daily/league/total limits, drawdown, deterministic ties, and an integration path that places DeepSeek/GPT/Poisson candidates for the same fixture and produces exactly one execution for the highest score. Run the full existing API suite, focused P2.1 tests, migration idempotence, frontend lint/build, and `git diff --check`.
