# Progress

## 2026-08-28

- Approved design recorded in `docs/superpowers/specs/2026-08-28-dotascope-performance-design.md` and committed separately.
- Audited the existing prediction, decision, bankroll, settlement, API, and performance-page paths.
- Started backend experiment and metrics implementation.
- Added versioned baseline experiment metadata, Log Loss/RPS, market Brier/Log Loss comparison, decision counts, portfolio summary, and an explicit quality gate.
- Added the strategy quality-gate summary to the existing performance page; initial TypeScript and lint checks passed.
- Added focused tests for experiment metadata, proper scoring, market comparison, decision counts, and shadow-mode gates.
- Full API suite passed: 136 tests with one existing Starlette/httpx deprecation warning.
- Web lint, TypeScript, and production build passed.
- Verified the live MySQL-backed API response on port 8002 and the performance page on port 3001; all performance requests returned 200.
- Completed desktop and 390px mobile visual checks; localized gate failures and allowed two-line reason text to avoid truncation.
- Removed generated Next type/cache diffs and left both local development services running for user review.
- Corrected legacy settlement handling so missing historical decision snapshots are reported as `unknown`, not misclassified as `no_bet`.
- Added the read-only `/api/decisions` audit endpoint and performance-page table for latest per-fixture decisions, execution status, candidate direction, theoretical stake, and no-bet reason.
- Made the latest-decision query strategy-version aware so future strategy variants cannot overwrite each other.
- Added Log Loss/RPS columns to settled prediction rows.
- Added `/api/strategy-performance` and the model/strategy leaderboard; future strategy variants can occupy independent rows without changing the report contract.
- Exposed considered market/selection separately from the final backend status so a no-bet decision still explains which candidate was evaluated.
- Flagged existing simulated bets whose market/selection no longer matches the current prediction as audit mismatches; no historical bet was mutated.
- Verified the final running services: `/api/strategy-performance` returns two independent model rows, `/api/decisions` returns 14 current DeepSeek rows, and `/performance` renders the leaderboard, quality gate, and decision audit.
- Final verification passed: full API suite 139 tests with one existing Starlette/httpx deprecation warning; frontend production build, TypeScript, lint, and `git diff --check` passed.
