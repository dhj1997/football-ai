# Fixture Evidence Preservation Design

## Problem

Hourly fixture synchronization replaces every fixture in the date window with a fresh provider payload. Evidence added later to the cached fixture, including `evidence`, `evidence_synced_at`, and `lineup_confirmed`, is therefore lost. Finished fixtures are not analyzed again, so their detail page remains empty after the next fixture refresh.

## Chosen Design

`PredictionRepository.replace_fixtures` will merge durable evidence fields from an existing fixture with the newly fetched provider payload before replacing the synchronized window. Provider-owned fields such as status, score, kickoff, teams, and venue continue to come from the new payload.

The repository will also expose a focused recovery operation that restores missing current evidence from the latest immutable evidence snapshot for a fixture. Recovery only writes when the current fixture has no evidence, keeps the current provider-owned fixture fields, and copies the snapshot context plus its synchronization metadata.

For the affected Valencia vs Real Betis fixture, the existing latest snapshot will be used once after deployment. No prediction, bet, settlement, or bankroll record will be changed.

## Alternatives Rejected

- Moving all fixture evidence into normalized tables would solve ownership more broadly but requires an unnecessary migration for this bug.
- Reading evidence only from prediction snapshots in the UI would hide the overwrite while leaving automation and API consumers with missing data.

## Failure Handling

- A fixture without previous evidence remains unchanged.
- A fixture without a valid evidence snapshot cannot be recovered and returns `None`.
- Existing evidence is never overwritten by an older snapshot.
- Provider refresh failures retain the existing stale-cache behavior.

## Verification

- Repository test: evidence fields survive a fixture-window replacement while provider status and score update.
- Repository test: missing evidence restores from the latest immutable snapshot and recovery is idempotent.
- Existing schedule-sync and repository tests continue to pass.
- Live verification confirms the affected fixture contains restored recent form and the page renders it after another fixture refresh.
