# P5 Three-League Historical Data Pipeline

## Scope

Support only CSL, EPL, and LAL historical data. The pipeline preserves raw/provider provenance, maps records to canonical identities, bounds storage to at most 100 canonical fixtures per league and 300 total, and reuses P4 historical snapshots/backfill/rolling validation. It does not add models or alter P0-P4 prediction, settlement, portfolio, or execution semantics.

## Registry and Providers

Create one registry for canonical league codes, provider capabilities, and per-entity source priority. Existing providers remain adapters for scheduled fixtures/evidence; P5 orchestration rejects unsupported leagues before any request. Provider responses are ingested page-by-page with configurable season/date/cursor/limit parameters and stop immediately at the per-league/global cap.

## Provenance and Identity

Raw records use SHA-256 payload hashes and append-only idempotency. Canonical league/team/fixture mappings retain source IDs and unresolved/conflict status. Conflicting provider values are stored as conflict records with the selected value and resolution method; no silent overwrite occurs. All timestamps are normalized to UTC.

## Historical Flow

The bounded order is league -> team -> fixture -> result -> odds -> HistoricalSnapshot. Odds timeline derives opening/pre-match/closing from existing snapshots strictly before kickoff; absent provider history remains unavailable. A 24-hour historical prediction delegates to the formal PredictionService through P4's backfill adapter and never directly inserts predictions.

## Sync and APIs

Add idempotent `data_sync_runs` persistence with bounded retry/error categories and read-only source, sync, league coverage, and historical data endpoints. Provider failure degrades to unavailable/stale status and does not stop API startup.

## Verification

Add focused tests for whitelist/caps, identity/dedup/conflict, raw hash append-only behavior, UTC timestamps, odds leakage, backfill/rolling boundaries, source unavailability, sync idempotency, and a CSL/EPL/LAL end-to-end mocked pipeline. Run existing P0-P4 tests proportionally plus full pytest, lint/build, migration, and diff checks.
