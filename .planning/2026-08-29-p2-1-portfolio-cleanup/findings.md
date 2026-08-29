# Findings

- The application injects `PortfolioConfig`, but `BankrollService` still has a `portfolio_config is None` branch implementing old 10%-25% stake sizing, 50% daily exposure, and 0.03 edge eligibility.
- `repository.current_balance()` is the transaction-ledger cash balance. `BankrollService.summary()` adds open stakes to expose equity, while portfolio placement currently adds only the service model's open stakes before calling selection; this is the source of mixed account bases.
- `portfolio.py` already has candidate scoring, risk gates, selection, and an active status set, but account helper functions are incomplete and selection needs one canonical exposure snapshot.
- `DualBankrollService` invokes models independently. Global same-fixture exclusion can be enforced by Portfolio selection against all active bets and a deterministic tie-breaker, without creating a new model or Prediction row.
- Existing `market_decision.py` P0/P1 signal thresholds must remain unchanged; only production execution qualification moves to Portfolio.

## Resolved

- BankrollService now always owns a PortfolioConfig and no longer contains the legacy stake floor/cap, daily cap, or edge execution branch.
- Placement and summary paths derive cash, open exposure, and equity from the shared Portfolio helpers; active stakes are not added twice.
- Dual model orchestration and automation use global correlation selection before persistence, so one fixture produces at most one execution.
