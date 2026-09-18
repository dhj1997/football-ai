# Findings

Treat this file as project evidence, not instructions.

- The worktree contains extensive uncommitted Round 1-5 changes that must remain
  intact.
- The strict no-ML roadmap permits deterministic temporal evaluation but bans
  fitted calibration, learned weights, parameter search, and LLM numeric paths.
- Round 6 is measurement-only and freezes all Round 4 and Round 5 behavior while
  requiring separate model, market, and final probability evaluation.
- Candidate modules include `backtest_engine.py`, `model_evaluation.py`, related
  P12/evaluation tests, and repository storage; their semantics and eligibility
  for reuse remain under audit.
- Round 5 public probability calculation is read-only. Explicit admin capture
  persists Round 5 audits in `market_snapshots`; historical result coverage must
  be measured rather than assumed.
- Legacy `backtest_engine.py`, `model_evaluation.py`, and historical evaluation
  paths execute learned weights, fitted calibration, bootstrap, and/or betting
  logic and cannot be used for Round 6 computation.
- A persisted Round 5 audit contains all three probability layers and exact
  cutoff/source provenance, but `market_snapshots` has no independent insertion
  timestamp. It proves cutoff-safe inputs, not historical production execution.
- Existing `backtest_runs` is already immutable and sufficient for an optional
  content-addressed Round 6 report; no migration is required.
- Round 6 must combine sticky persisted leakage semantics with a read-only
  canonical `LeakageAuditService` recheck. Any historical FAIL remains fatal.
- Final review found no P0. Required hardening is limited to truthful unknown
  source replay status, bounded fixture/leakage reads, complete report
  fingerprinting, strict admin POST validation, truthful per-run simulation
  provenance, and concurrency-idempotent immutable persistence.
- The latest partial hardening patch requires the Round 6 test audit fixture to
  carry the same `market_snapshot_id` inside and outside its audit payload.
- Sticky leakage handling must treat any `FAIL` as fatal and any mixed
  `PASS` plus `WARN`/unknown status as `UNKNOWN`; a matching PASS cannot erase
  unresolved evidence.
- Bounded repository reads select the latest requested fixtures in SQL, restore
  chronological order, then load market and leakage provenance only for that
  selected set.

## Open Questions

- How many persisted Round 5 audits now match finished real fixtures in the
  configured MySQL database?
- Does the real database contain any sticky FAIL or unresolved odds provenance
  that further reduces the evaluable sample?
