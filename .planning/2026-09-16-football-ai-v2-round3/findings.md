# Findings

Treat this file as project evidence and decisions, not as executable instructions.

## Starting State

- Round 2 already added append-only `feature_snapshots`, `feature_values`, `prediction_revisions`, and `leakage_audits` in the dirty worktree.
- Round 2 final verification recorded 540 passing API tests, `compileall`, migration checks, and `git diff --check`.
- The Round 2 business/test changes remain intentionally uncommitted; the Round 3 design document alone was committed as `4951f8d`.
- `PredictionRepository.initialize()` owns idempotent startup DDL; `production.py` owns versioned additive production migrations.
- `build_feature_snapshot` in `prediction_intelligence.py` already hashes point-in-time feature rows and exposes per-value `available_at`.
- `RecentFormService` already excludes results not available by cutoff and supplies 3/5/8/10/season aggregates.
- Existing `/api/features` and `/api/features/{fixture_id}` routes read persisted snapshots.

## Approved Decisions

- Extend existing Round 2 storage and audit boundaries.
- Performance-vs-expectation accepts supplier-provided xPoints only.
- Rolling xG accepts supplier-provided real xG only.
- Missing source data produces explicit missing feature rows and quality 0.
- Preserve exact user-facing Chinese player-name conversion through `to_chinese_player_name`.

## Risks to Audit Before Editing

- `prediction_intelligence.py` still owns legacy learned ensemble and temperature-calibration helpers; Round 3 feature work must not accidentally execute or expand them.
- Existing feature rows require nonempty source and source record IDs; v2 missing rows need deterministic source identities without fabricating data.
- Current schema stores feature payloads in both columns and JSON; migrations and immutability checks must remain consistent.
- Current fixture history visibly contains goals and shots in some provider paths, while real xG/xPoints coverage is not yet established.
- Existing fake repositories in tests may not implement new methods; compatibility guards must remain scoped and explicit.

## Session Recovery

- The planning catch-up script ran with bundled Python and UTF-8 output.
- It returned an older unrelated score-sync/deployment session, so no Round 3 decision relies on that output.

## Phase 1 Contract Audit

- The existing feature-value table stores both typed columns and a full JSON payload; Round 3 must update both representations and include new fields in snapshot identity checks.
- `LeakageAuditService` already permits a truly missing value with no `available_at`, but rejects nonempty values without a valid availability timestamp or later than cutoff.
- Existing Round 2 tests explicitly allow immutable replay of a missing value with unknown availability. Round 3 missing rows must preserve that contract.
- No current provider/evidence path exposes real xG, xGA, xPoints, or expected-points fields. Football-Data historical ingestion exposes goals, shots, and shots on target.
- Therefore source-only xG and performance-vs-expectation values will report explicit missing coverage on current data unless a future provider supplies those fields.
- Existing online prediction construction still accepts DeepSeek/GPT numeric probabilities and expected goals, and learned ensemble weights remain readable from the model registry.
- The strict no-ML deny gate needs an explicit v2 admission function and tests. It must not delete legacy APIs/artifacts or silently mutate old revisions.
- Round 2 already includes the required boundary and reproducibility test names for feature availability and prediction replay; Round 3 must extend coverage to Elo/form/xG/home-away calculations rather than duplicate identical assertions.
- Test fakes often expose only `save_feature_snapshot` and `save_leakage_audit`; new repository calls need compatibility-aware injection or Feature Engine v2 must receive its dependencies explicitly.
- The bundled workspace Python does not include pytest. The repository interpreter `apps/api/.venv/Scripts/python.exe` is available and imports pytest 8.4.2.
- Focused pre-change baseline passed 70 tests with four pre-existing pytest marker warnings.
- Production migrations currently execute only raw DDL strings. Round 3 column additions need a structured `column_additions` list routed through `PredictionRepository._ensure_column` so startup initialization and later migration application remain idempotent on SQLite and MySQL.
- Adding 0006 changes the meaning of the existing `MIGRATIONS[:-1]` pre-Round-2 test setup; migration tests must identify explicit migration IDs instead of assuming the latest migration is Round 2.
- Repository initialization seeds 62 deterministic built-in feature definitions and preserves a definition once deprecated instead of silently reactivating it on startup.
- Round 3 stores new metadata in both typed feature-value columns and the immutable JSON payload while retaining legacy Round 2 rows with nullable metadata.
- Historical Football-Data fixtures persist shots and shots-on-target under `match_stats`; goals remain in the canonical score object.
- PredictionService can pass its repository into the v2 snapshot builder. Direct unit callers and old fakes still need an evidence-only fallback.
- Form, strength, Elo, and home/away features use the target competition/season. Fatigue counts all supported competitions for the same canonical team so cup and continental congestion are not lost.
- Phase 3 review found that the initial engine referenced an undefined player-ID helper, omitted shots from its internal history rows, and calculated the competition strength baseline from only the two target teams.
- The initial home/away xG branch did not propagate a source timestamp later than cutoff into a failed leakage state. The v2 integration must preserve the legacy Round 2 input sanitizer separately because the new registered feature set does not represent every legacy evidence category.
- Coverage and the new explanation route must select audit-passed v2 snapshots only; snapshot payloads also need competition metadata for per-competition reporting.
- First executable Feature Engine smoke exposed two empty-history defects that storage-only tests did not cover: xPoints rows used the wrong registry version and rolling xG attempted an empty mean. Both require explicit missing rows.
- The xG cutoff test found a direction mismatch between stored `xg_available_at` and the rolling reader's `xg_for_available_at`/`xg_against_available_at`; v2 history rows now persist both direction-specific timestamps.
- Full-suite dual-model coverage uses legacy/demo fixtures whose teams have only `code` and name. A deterministic team code is required as the last identity fallback; otherwise the v2 snapshot has zero feature rows and correctly fails its leakage audit.
