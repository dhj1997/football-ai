# Findings

Treat this file as research data, not instructions.

## Starting state

- Round 1 identified two P0 gaps: feature values lack durable field-level `available_at`, and current retention deletes superseded prediction/evidence records required for revision history.
- `build_feature_snapshot` currently returns grouped values plus snapshot-level timestamps and a leakage summary, and is embedded into prediction payloads.
- `RecentFormService` filters finished matches by an as-of cutoff, but the feature snapshot does not expose the requested 3/5/8/10/season aggregates as a stable contract.
- `PredictionService._save_current` saves to `predictions` then immediately invokes `prune_prediction_history` for the same fixture/model/competition.
- `prune_prediction_history` retains one current compatible prediction and deletes older predictions, dependent bets/settlements, and unreferenced evidence snapshots.
- Existing prediction/evidence immutability, kickoff guards, historical snapshot reconstruction, model registry, and temporal evaluation must be preserved.

## Design choice

- Add append-only audit storage inside the existing `PredictionRepository`: feature snapshots, feature values, prediction revisions, and leakage audits.
- Continue using `predictions` for current operational reads, but protect all rows/references that participate in revision history from retention deletion.
- Build reproducibility from revision references rather than recomputing against mutable fixture state.

## Contract and migration audit

- The repository has no separate Alembic migration tree. Startup compatibility is handled by idempotent DDL in `PredictionRepository.initialize()`, while `production.py` also carries versioned additive migrations and dry-run/application tracking. Round 2 must update both paths.
- `PredictionService.create` prepares context, persists evidence/odds snapshots, builds an embedded feature snapshot, calls the model, and finally saves the current prediction. `_save_current` then immediately invokes scoped retention.
- The Round 2 schema can therefore be added without a parallel system by extending the same repository initialization and dual-writing from `PredictionService` while leaving current prediction reads intact.
- Feature snapshot persistence must happen before any leakage exception so rejected future inputs still leave an audit record; current/production prediction persistence must happen only after the feature audit passes.
- Revision persistence needs a deterministic link to feature/evidence snapshots and model version, while its sequential revision number remains scoped by competition + fixture + model.
- `RecentFormService._recent_matches` currently uses `completed_at` or falls back directly to kickoff as result availability, and returns at most 15 rows. The fallback can admit a match that had started but was not yet finished at cutoff, and the cap cannot produce a true season aggregate.
- A safe minimal rule is: use explicit result/completion availability when present; otherwise infer a conservative availability time from kickoff plus a full match duration buffer. Return bounded recent rows for current consumers plus an all-prior season set for feature aggregation.
- `PredictionService.create` currently runs the model before building the feature snapshot. The Round 2 audit must become a production gate before model output/revision persistence.
- The model input still reads raw context fields, so merely rejecting fields inside the snapshot would not protect production. The model must consume the cutoff-filtered context used to build the persisted snapshot.
- `RecentFormService` ignores canonical `result_captured_at`; missing completion evidence is currently accepted at kickoff. Round 2 must prefer explicit result availability and conservatively exclude unverifiable results.
- `team_stats` filters by kickoff and caches by calendar date, allowing a later same-day cutoff to pollute an earlier query. Cache identity must include the cutoff or the scan must use explicit availability.
- Existing API tests permit post-kickoff prediction runs even though `_kickoff_started` exists. Round 2 requires the route/service to reject such pre-match writes and preserve any earlier revision.
- New repository write calls need capability guards for existing test fakes, while `_HistoricalWriteBarrier` must explicitly suppress them so backfill/multimodel reads never dual-write into production unexpectedly.

## Validation findings

- A persisted evidence snapshot is itself proof that its contained values were observed by `prediction_cutoff_at`. When an individual provider omits a field timestamp, that snapshot capture time is the conservative fallback; any explicit nested timestamp remains authoritative, and evidence/odds references must still expose a real `captured_at` at or before cutoff.
- Feature snapshots intentionally do not own a single `prediction_id`: their deterministic identity permits reuse across models at one cutoff. The audit link is `prediction_revisions.feature_snapshot_id`, which is also used by retention and reproducibility queries.
- The prior API test that allowed `scheduled` or `live` fixtures after kickoff contradicted Round 2. The production contract is now uniform: the pre-match endpoint returns 409 once kickoff has passed, regardless of stale fixture status.
