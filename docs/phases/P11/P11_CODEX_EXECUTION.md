# P11 Codex Execution

1. Audit current odds models and P0/P2 separation.
2. Create OddsSnapshot/MarketSnapshot schema.
3. Build provider normalization.
4. Build timeline and consensus services.
5. Add implied probability/overround.
6. Add model-vs-market and CLV calculations.
7. Integrate prediction provenance and UI.
8. Add historical as-of tests.

Never use current odds for historical prediction. Never use edge alone as execution permission. Never overwrite original odds snapshots.
