# P7 Recent Form Data Pipeline

## Scope

P7 provides deterministic recent-form features for CSL, EPL, and LAL only. It reuses the existing `fixtures` table and canonical fixture payloads; it does not add a second match database or change P0-P6 prediction, settlement, portfolio, validation, or evaluation algorithms.

## Data Flow

`RecentFormService` reads fixtures for one canonical team and an `as_of` timestamp. It keeps only provider-finished matches with a completed score and `kickoff <= as_of`, orders by `kickoff DESC, fixture_id DESC`, and truncates to 15. It derives overall, home-only, and away-only aggregates with explicit sample counts and `unavailable`/`insufficient`/`ok` status. P3's existing `FORM_DECAY_LAMBDA` remains the only weighting algorithm.

The service exposes `GET /api/team-form/{team_id}?as_of=...`. Prediction context preparation resolves the fixture's two teams through the same service and injects the resulting rows into the existing `recent_form` evidence shape, so DeepSeek, GPT, Poisson, and historical reconstruction share one as-of view.

## Safety and Compatibility

Future, live, postponed, cancelled, invalid-score, unsupported-league, and cross-league records are excluded. No odds are synthesized. Existing evidence remains authoritative when it is richer, while the P7 form rows are marked with source, `as_of`, and sample metadata. All changes are additive and keep existing database history immutable.

## Verification

Focused tests cover the 15-match cap, insufficient and unavailable samples, future/status exclusion, stable ordering, home/away splits, as-of reconstruction, three-league isolation, API validation, prediction timestamp leakage, and the P6 historical backfill boundary. The existing P0-P6 tests remain unchanged and are run with the normal repository validation commands.
