# Progress

## 2026-08-29

- Read the P4 task document, AGENTS.md, P3 plan, current database schema, snapshot persistence, prediction services, settlement metrics, and tests.
- Chosen minimal architecture: append-only historical snapshot and backtest-run records, pure as-of/quality/rolling helpers, injectable formal-pipeline backfill, and read-only APIs.
- Initial backfill test fixture missed the repository's required `provider_id`; added the existing field without changing production code.
- Added idempotent raw-data, historical-snapshot, and backtest-run persistence with SQLite/MySQL-compatible schema/index creation.
- Added canonical fixture/team/league identity, source priority/conflict reporting, as-of evidence reconstruction, odds timeline/closing selection, quality scoring, and exclusion reasons.
- Added formal-pipeline historical backfill adapter and configurable rolling backtest with as-of profiles/calibration and separate forecast/betting metrics.
- P4 focused tests: 10 passed; API and database migration smoke checks passed.
- Added odds opening/pre-match/closing classification, per-prediction backtest metadata, quality exclusions, and as-of profile/calibration filters.
- Wired raw evidence/odds provenance recording beside the existing immutable snapshot writes without changing prediction behavior.
- P4 focused tests now: 12 passed; prediction service and read-only API smoke checks passed.
- Full pytest: 188 passed, 1 warning.
- P0 focused: 9 passed; P1 focused: 8 passed; P2/P2.1 focused: 17 passed; P3 focused: 7 passed; P4 focused: 10 passed.
- Web lint and production build passed; migration initialization and git diff checks passed.
- Final full pytest: 188 passed, 1 warning; Python compile, web lint/build, migration smoke, and git diff checks passed.
- Final full pytest: 189 passed, 1 warning; Python compile, web lint/build, migration smoke, and git diff checks passed.
- P4 implementation is complete. Two direct push attempts and `git ls-remote` failed because the GitHub connection was reset by the current environment; local commit remains ready for a later push.
- Current database inventory: raw records 0, normalized fixtures 21, predictions 28, evidence snapshots 30, odds snapshots 0, league snapshots 3, team snapshots 2, historical snapshots 0, backtest runs 0, settlements 16.
- Current rolling smoke over persisted settlements (180/30/30): 30 windows, 8 total and 8 eligible fixtures, 0 excluded, leakage check passed; sample warning remains `insufficient`.
- Rolling metric smoke had one evaluable window: baseline/P3 Brier 0.673925/0.671138, LogLoss 1.099009/1.093063, ECE 0.421667/0.421667, RPS 0.228288/0.227600; CLV and betting metrics unavailable.
