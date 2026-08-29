# P5 Three-League Historical Data Pipeline

## Goal

Build a small, real, traceable CSL/EPL/LAL historical data pipeline with strict 100-per-league and 300-total limits, then feed it through P4 historical validation without changing P0-P4 semantics.

## Phases

### Phase 1: Registry and provenance
- Status: completed
- Add canonical three-league registry, provider capability/priority contracts, raw payload hash, identity mappings, and idempotent sync-run persistence.

### Phase 2: Bounded provider sync
- Status: completed
- Add paginated/limited fixture/result/odds sync orchestration with explicit unavailable states, retries, and no large downloads.

### Phase 3: Historical pipeline integration
- Status: completed
- Connect bounded records to P4 snapshots, 24h backfill, and CSL/EPL/LAL independent rolling evaluation.

### Phase 4: APIs and tests
- Status: completed
- Add read-only source/sync/coverage APIs and focused P5 integration, limit, identity, conflict, timestamp, and idempotency tests.

### Phase 5: Verification and delivery
- Status: in_progress
- Run proportional regression/lint/build/migration checks, report inventories and limitations, commit, and push directly to `main`.

## Constraints

- Work directly on `main`; no branch, PR, or cherry-pick.
- Only CSL/EPL/LAL; reject all other leagues.
- Enforce 100 fixtures per league and 300 total at the orchestration boundary.
- Preserve raw data and historical records append-only; never fabricate odds, lineups, injuries, CLV, or ROI.
- Reuse existing providers, P4 validation, P3 features, formal PredictionService, P1 settlement, and P2 portfolio.
