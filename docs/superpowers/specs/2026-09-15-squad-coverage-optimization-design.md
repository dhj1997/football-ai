# Squad Coverage Optimization Design

## Goal

Ensure the seven-day fixture window receives team rosters early enough for match-detail display, while retrying genuinely empty provider rosters without creating an aggressive request loop.

## Chosen Approach

- Change the default Dongqiudi schedule lookahead from 36 hours to 168 hours so it matches the existing seven-day fixture window.
- Run `squad_backfill` hourly and allow at most 12 new team fetches per run.
- Treat a fixture side as complete only when its `squad` is a non-empty list.
- Re-fetch an empty cached team snapshot only after the existing team cache TTL has elapsed. Do not attach an empty roster to fixture data.

This keeps the existing fixture twin and team snapshot architecture. It does not add tables, identity services, or eager ESPN synchronization.

## Data Flow

1. Hourly Dongqiudi schedule synchronization reads seven days and attaches Dongqiudi match IDs to matching canonical fixtures.
2. Hourly squad backfill selects future fixtures whose home or away squad is empty.
3. A non-empty cached Dongqiudi team snapshot is reused immediately.
4. A missing snapshot is fetched; an empty snapshot is fetched again only after `team_cache_ttl_minutes`.
5. Only a non-empty roster is written to `free_team_data`; downstream match evidence continues to use it as the existing fallback.

## Failure Handling

- Provider exceptions remain bounded in the job result.
- Empty provider rosters are recorded as bounded errors and remain eligible for a later TTL-based retry.
- The per-run limit and hourly cadence bound external requests during initial catch-up.

## Verification And Deployment

- Add focused default-setting tests for 168 hours, 60 minutes, and 12 teams.
- Add backfill tests covering empty attached squads and empty cached snapshots before and after TTL expiry.
- Run the focused automation/config suite, then the full API suite because `AutomationRunner` is shared infrastructure.
- Deploy through the existing server package flow, restart API/Web, force schedule synchronization and bounded squad backfill, then remeasure production coverage and health.
