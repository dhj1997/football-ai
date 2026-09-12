# Scheduled Evidence Refresh Findings

## Current Runtime

- Production uses FastAPI's in-process `AutomationRunner` under systemd.
- Current production values include `AUTOMATION_ENABLED=true`, `AUTOMATION_ANALYSIS_ENABLED=false`, `AUTOMATION_TICK_SECONDS=60`, fixture interval 60 minutes, analysis interval 5 minutes, prediction lead 36 hours, evidence refresh limit 1, schedule lookback 1 day, and schedule cache TTL 1440 minutes.
- The deployed app uses MySQL and has a private API plus a public Next.js proxy.

## Current Data Flow

- `ScheduleSyncService._refresh` asks the schedule provider for `today - lookback_days` through `today + 1` and persists that window.
- API-Football evidence fetch includes predictions, H2H, injuries, lineups, odds, squads, and public team profiles in one multi-request call.
- ESPN evidence can provide recent form, season-series H2H, rosters/availability, lineups, team profiles, squads, and odds when it matches an event.
- The evidence chain falls back API-Football -> ESPN -> TheSportsDB partial. TheSportsDB partial evidence intentionally has no H2H, injuries, lineup, or odds.
- `AutomationRunner._analyze_upcoming` currently combines evidence refresh, model prediction, and simulated betting, so enabling it would create model activity rather than only fetch data.
- Dongqiudi has separate daily schedule/initial enrichment and final-window prematch jobs, but its H2H data is embedded in provider-specific analysis and does not cover every schedule row.

## Current Online Symptom

- `sportsdb-2506199` is finished with empty evidence, including H2H, recent form, injuries, and synced timestamp. It cannot be retroactively populated by the current detail route, which only auto-enriches scheduled/live fixtures.
- Recent online job history shows hourly fixture syncs and 5-minute Dongqiudi prematch checks; no dedicated evidence job is present. Historical accumulation also reports an unrelated existing `canonical_fixture_id` error.

## Verification and Deployment

- Daily fixture sync now covers `today - 1` through `today + 7` in China time and is due once per China calendar day.
- Daily evidence refresh runs independently of model prediction and bankroll placement; production analysis remains disabled.
- Lineup refresh scans every five minutes and persists one marker for each configured 60-minute and 30-minute window, skipping the second window after an earlier confirmed lineup.
- TheSportsDB's free endpoint returned HTTP 429 after roughly 30 requests; schedule requests now retry with bounded delays and the controlled seven-day sync completed successfully.
- Production job history confirms fixture success (`request_count=36`, `item_count=33`), evidence success (`refresh_count=23`), and lineup success. Public tomorrow fixtures expose H2H/availability/team data for provider-supported matches.
- One provider limitation remains explicit: ESPN's public endpoint returns HTTP 403 in this environment, so API-Football is the primary source for complete evidence; matches without a provider response remain marked partial rather than fabricated.
