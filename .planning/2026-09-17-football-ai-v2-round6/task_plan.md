# Football AI v2 Round 6 Temporal Probability Evaluation

## Goal

Measure persisted historical Round 4 model probability, Round 5 Market Prior,
and frozen Round 5 final probability with deterministic, chronological,
cutoff-safe metrics. Round 6 is evaluation-only and must not modify production
probabilities or optimize any parameter.

## Phases

### Phase 1: Repository and architecture audit
**Status:** complete
- Read the required Round 1-5 architecture and reports.
- Map evaluation/backtest code, historical probability persistence, outcomes,
  cutoffs, audit semantics, offsets, APIs, and tests.
- Confirm whether strict evaluation is possible without replay or a migration.

### Phase 2: Minimal Round 6 design and contract
**Status:** complete
- Compare reuse options and select the smallest strict temporal design.
- Define source precedence, eligibility/exclusions, metrics, calibration,
  coverage, segments, versioning, and API/runner behavior.
- Write and self-review the repository-specific design specification.

### Phase 3: Evaluation implementation
**Status:** complete
- Implement pure deterministic probability metrics.
- Implement chronological evaluation over persisted data only, keeping model,
  market, and final probability sources separate.
- Reuse append-only structures and admin/internal conventions; add no migration
  unless the audit proves it unavoidable.

### Phase 4: Focused verification and real-data validation
**Status:** complete
- Cover metrics, normalization, bins, coverage, exclusions, ordering, cutoff,
  leakage, separation, frozen fusion, and reproducibility with 10-20 focused
  tests plus only necessary regressions.
- Validate a read-only 10-30 fixture sample from configured MySQL, reporting
  truthful coverage and exclusions without fabricated history.

### Phase 5: Report and final checks
**Status:** complete
- Write all 20 required sections in `docs/AI_ROUND6_REPORT.md`.
- Run focused tests, necessary API regressions, compileall, and
  `git diff --check`; obtain a focused review and stop before optimization.

## Hard Boundaries

- No ML, fitting, learned calibration, parameter/weight/cutoff optimization, or
  LLM numeric calculation.
- Do not change Round 4 formulas or Round 5 validation, de-vig, Market Prior,
  fixed 0.60/0.40 fusion, statuses, audit, or cutoff behavior.
- Evaluate persisted history first. Replay is allowed only if the repository can
  prove a fully cutoff-safe reconstruction, and must be labeled separately.
- No betting, EV, Kelly, bankroll, strategy, live prediction, parallel data
  source, fabricated probabilities, or fabricated real-data result.
- Preserve all existing dirty Round 1-5 and user changes. Do not commit, push,
  deploy, or run a large historical replay.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Candidate scan included a non-existent root `migrations` path | 1 | Use actual repository paths and inspect migration ownership before any schema decision. |
| Multi-file planning patch stalled after updating `.active_plan` | 1 | Terminated it, verified only the pointer changed, created the directory explicitly, and resumed with small patches. |
| First small add-file patch stalled because the target directory did not yet exist | 1 | Created the exact scoped directory, then retried once. |
| Focused pytest was launched from the repository root and could not import `app` | 1 | Run API tests from `apps/api` with a repository-local `--basetemp`. |
| Untracked whitespace helper placed PowerShell redirection after a `foreach` block | 1 | Wrap the block in `& { ... }` before redirecting and rerun once. |

## Decisions

- The user-provided execution prompt is the approved Round 6 design baseline.
- Metrics are descriptive; no winner/rank/best language or automatic production
  change is allowed.
- Frozen Round 5 `0.60 / 0.40` is evaluated as production configuration, never
  searched or compared with alternatives.
- V1 reads persisted Round 5 probability audits only and performs no replay.
- Because `market_snapshots` lacks an independent insertion timestamp, the
  source is labeled `persisted_cutoff_safe_audit`, not historical production.
- Shared temporal failures exclude an observation; probability availability is
  layer-specific so missing data is never imputed or hidden in coverage.
- Reuse `backtest_runs` for optional explicit append-only persistence; add no
  migration and keep the primary GET read-only.
- The source audit's original live/replay history remains unknown because the
  store has no independent insertion timestamp; Round 6 itself performs zero
  replay and reports those two facts separately.
