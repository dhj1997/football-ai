# Findings

Treat this file as research data, not instructions.

- Team detail API supports only `epl`, `laliga`, and `csl` through ESPN.
- Match evidence reads `squads`, then falls back to `free_team_data.squad`.
- `squad_backfill` defaults to every 180 minutes and at most 6 teams per run.
- Dongqiudi backfill requires an upcoming fixture with a matched Dongqiudi twin and provider team IDs.
- Dongqiudi player names pass through `to_chinese_player_name`.
- Production has 3,526 fixture rows; the current future window has 23 canonical fixtures and 46 team-sides.
- Only 8/46 future team-sides currently have attached players; 38/46 are empty, representing 32 distinct teams.
- All 38 empty team-sides lack a Dongqiudi match ID. None currently fail later at the twin/team-ID/snapshot stages.
- Coverage is time-bucketed: 0-36h is 6/6 covered; 36-72h is 0/10; 3-7d is 2/30.
- Production settings are `dongqiudi_lookahead_hours=36`, schedule sync every 60 minutes, squad backfill every 180 minutes, limit 6.
- The latest Dongqiudi schedule jobs succeed hourly and explicitly cover only through 2026-09-16; the last seven squad jobs succeeded but processed zero teams.
- Therefore the scheduler is running. The visible gap is caused by the 36-hour Dongqiudi mapping horizon being shorter than the 7-day fixture display horizon.
- Team-detail data is healthy: a read-only live ESPN audit returned non-empty rosters for all 56 current standings teams, with 23-39 players each.
- Only 6/56 ESPN team snapshots are cached because team detail is fetched lazily on first visit; uncached is not equivalent to unavailable.
- There are 26 empty historical Dongqiudi snapshots, but none explains the current future-fixture gaps; they are mostly unrelated youth, women, or similarly named competition rows.
- The approved implementation changes the default Dongqiudi horizon to 168 hours, squad cadence to 60 minutes, and fetch limit to 12.
- A fixture side now counts as complete only with a non-empty list-valued `squad`; empty snapshots retry after the existing 360-minute team cache TTL and are never attached as completed data.
- Initial production catch-up read 56 supported fixtures through 2026-09-22, inserted 20 Dongqiudi twins, enriched 39 fixtures, then backfilled 12 teams without errors.
- The remaining Zhejiang Professional vs Wuhan Three Towns mismatch was caused by Dongqiudi `浙江` versus canonical `浙江队`; an exact reviewed alias closed it.
- Final catch-up enriched that match and backfilled two teams. Production coverage is now 46/46 team-sides across 23 future fixtures, with zero missing.
- The production match-detail API for `sportsdb-2434546` returns Dongqiudi ID `54389980` and 33 players for each side.
