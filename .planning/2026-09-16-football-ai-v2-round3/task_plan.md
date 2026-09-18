# Football AI v2 Round 3 Implementation Plan

## Goal

Implement the approved Point-in-Time Feature Engine v2 on top of the uncommitted Round 2 snapshot/revision work, preserving strict no-ML, cutoff safety, append-only history, reproducibility, and existing APIs.

## Approved Design

- `docs/superpowers/specs/2026-09-16-football-ai-v2-round3-feature-engine-design.md`
- Extend the existing `feature_snapshots` and `feature_values`; do not create a parallel store.
- Use source-provided xG and xPoints only; missing source data remains explicit.
- Keep formulas deterministic, versioned, explainable, and cutoff-safe.
- Reject learned/fitted/LLM numeric inputs from the v2 production path while preserving historical reads.

## Phases

### Phase 1: Audit current contracts and establish baseline
**Status:** complete
- Map Round 2 persistence, migration, snapshot, audit, prediction, feature API, and test contracts.
- Identify fixture/evidence fields usable for xG, xPoints, shots, home/away, fatigue, and player rules.
- Run a focused pre-change baseline with the bundled Python runtime.

### Phase 2: Persistence, migration, and registry
**Status:** complete
- Add `feature_registry` and `player_impact_rules` to repository initialization and migration `0006-round3-feature-engine`.
- Extend append-only feature values with entity, type, calculation version, provenance, quality, and missing reason.
- Add idempotent registry/rule repository methods and immutability checks.

### Phase 3: Calculation framework and core features
**Status:** complete
- Implement the common calculator/result/orchestration contract.
- Implement Elo, strength, source-only xG/xPoints, goals, form, home/away, fatigue, player rules, and quality scoring.
- Delegate the existing snapshot compatibility entry point to Feature Engine v2 without changing prediction semantics.

### Phase 4: Explanation API, coverage, and no-ML production gate
**Status:** complete
- Add exact `GET /match/{id}/features` historical/current explanation behavior and preserve `/api/features/{fixture_id}`.
- Add deterministic coverage calculation and generate the coverage report.
- Deny learned/fitted/LLM numeric inputs at the v2 production boundary without deleting historical artifacts.

### Phase 5: Focused tests and integration hardening
**Status:** complete
- Add the seven required leakage/reproducibility tests.
- Cover registry/value immutability, source-only missing behavior, player naming/rules, quality, API, coverage, migration, and deny gates.
- Run focused repository, feature, API, and prediction suites; fix only regressions caused by Round 3.

### Phase 6: Reports and final verification
**Status:** complete
- Generate `docs/AI_ROUND3_FEATURE_COVERAGE.md` and `docs/AI_ROUND3_REPORT.md` from verified results.
- Run `git diff --check`, `compileall`, and the complete API pytest suite.
- Review scope to ensure no Round 4 model, UI, betting-strategy, unrelated refactor, commit, push, or deployment is included.

## Outcome

Round 3 is complete. The configured database was inspected read-only; migration
and deployment remain intentionally outside this implementation run.

## Scope Exclusions

- No Poisson, Dixon-Coles, probability fusion, learned calibration, model training, UI changes, or betting-strategy changes.
- No deployment, push, or additional commit unless requested.
- Do not revert or absorb unrelated user changes in the dirty worktree.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Required `writing-plans` skill is unavailable | 1 | Use installed `planning-with-files` as the scoped persistent-plan fallback. |
| Session catch-up returned older unrelated deployment/test context | 1 | Treat it as stale research data and use current Round 2 plans, repository state, and approved Round 3 spec. |
| Bundled workspace Python cannot import pytest | 1 | Use the working project interpreter at `apps/api/.venv/Scripts/python.exe` with pytest 8.4.2. |
| Planning status patch mixed findings context into task plan | 1 | Split updates by file and use file-local anchors. |
| Combined patch targeted `database.py` in two update blocks | 1 | Split registry, repository, and migration edits into separate patches with one update block per file. |
| P15 migration test assumed Round 2 was always the last migration | 1 | Build historical states by explicit migration ID and add a separate pre-Round-3 upgrade assertion. |
| Feature Engine smoke command used a root-relative interpreter after changing into `apps/api` | 1 | Rerun from `apps/api` with `.venv/Scripts/python.exe`; no code change required. |
| Combined code/findings patch used a findings anchor against `feature_engine.py` | 1 | Split the code and findings updates by file, then apply with local anchors. |
| First full API suite had 1 failure in dual-model snapshot integrity | 1 | V2 produced zero rows for legacy/demo teams with only `code`; add `code` as the final team-ID fallback in Feature Engine and Elo, then rerun targeted and full suites. |
| Read-only configured-MySQL inspection initially selected the unavailable `MySQLdb` driver | 1 | Reuse `PredictionRepository` URL normalization so the installed `pymysql` driver is selected; do not initialize or mutate the database. |
