# Progress

## 2026-08-29

- Read AGENTS.md, the P2.1 request, the current Portfolio/Bankroll/database/API implementation, and existing tests.
- Confirmed canonical semantics: cash balance from transaction ledger, active exposure from one shared status set, equity as cash plus active exposure, and global fixture correlation across models.
- Presented approaches and received approval for the Portfolio-only hard switch.
- Wrote the approved design; implementation is beginning with canonical Portfolio primitives.
- Added shared active statuses, ledger cash, active stake exposure, equity, and account exposure snapshots.
- Added deterministic one-candidate-per-correlation-group selection with stable model/prediction tie-breakers.
- Removed BankrollService legacy stake/exposure branches and routed placement, execution previews, summaries, and automation through Portfolio.
- Added legacy open-bet normalization to the current Portfolio stake once, without restoring legacy thresholds.
- Added focused canonical boundary tests and a DeepSeek/GPT/Poisson candidate selection integration test.
- Focused tests: 36 passed. Full API suite: 169 passed, 1 warning. Web lint/build passed. Diff check passed.
- P2.1 implementation and verification complete; changes committed and pushed to `main`.
