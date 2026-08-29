# Findings

- `market_decision.py` already computes de-vig market probability and `expected_edge` for 1X2 and Asian handicap rows. P2 should reuse these rows and expose a canonical `edge`/`ev` view.
- `BankrollService._league_day_candidates` currently ranks only by expected edge and `_place_candidate` uses 10%-25% per-fixture and 50% daily exposure. P2 policy must be injectable while preserving legacy callers.
- `bets` and `bankroll_transactions` are the current accounting tables. No execution-specific table exists, so P2 requires an additive `bet_executions` ledger.
- `settle_bet` already has a metadata extension from P1. It must not overwrite frozen odds/stake/selection/line after an execution is created.
- `Settings` reads the repository `.env`; P2 defaults must be fields in the settings model and application wiring, not literals spread across services.
- P2 explicitly excludes frontend changes and real-money execution.
