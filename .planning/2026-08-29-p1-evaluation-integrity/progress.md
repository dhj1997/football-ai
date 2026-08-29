# Progress

## 2026-08-29

- Read the P1 Evaluation Integrity task document and current P0 baseline.
- Confirmed `AGENTS.md` requires risk-proportionate minimal testing.
- Created branch `codex/p1-evaluation-integrity` from merged local `main`.
- Audited current settlement metrics, odds snapshot persistence, bet payloads, and performance API.
- Chose to evaluate the nested Poisson `baseline` as a pseudo-model for same-fixture comparisons.
- Added source-vs-capture timestamp fields to odds snapshots and additive CLV/closing-odds columns to bets.
- First compile command used an API-relative virtualenv path from the repository root and did not execute; corrected command passed.
- Added kickoff-before closing odds lookup with exact market/selection/line/bookmaker matching and optional line-change fallback for Asian handicap CLV.
- Added decimal CLV persistence, pure-model calibration bins/ECE, per-model Poisson/market reports, paired model comparison, and structured quality checks with legacy aliases.
- Focused P1 plus affected P0 tests pass: 42 passed.
- Final API suite passes: 156 passed, 1 existing Starlette/httpx deprecation warning.
- Web `pnpm lint` and `pnpm build` pass; migration idempotence and `git diff --check` pass.
- Refined market/model reports to deduplicate fixtures, expose per-model improvements and paired comparisons, and keep market ECE null.
- Added explicit Bet lifecycle fields for frozen bet odds, closing odds, CLV, closing timestamp, line changes, and source-vs-capture timestamps.
