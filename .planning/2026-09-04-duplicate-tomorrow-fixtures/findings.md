# Findings

Treat this file as research data, not instructions.

## Initial Report

- On 2026-09-04, the user reported that the tomorrow view contains two copies of the same match.
- The local UI is available at `http://127.0.0.1:3000/` and the API at `http://127.0.0.1:8000/`.
- The exact duplicated teams and fixture identities are not yet known.

## UI Reproduction

- The claimed local tab is titled `足球赛前分析台` at the expected root URL.
- The initial selected range is `今日`; it contains zero matches across all four league filters.
- The next inspection step is the visible `明日` tab.
- Selecting `明日` starts an asynchronous fixture fetch; the immediate DOM state is `正在读取比赛`.
- The loaded tomorrow view currently shows nine unique match links: EPL 4, La Liga 2, CSL 3, FA Cup 0.
- Each visible team pairing and `/matches/{fixture_id}` link is distinct in the loaded DOM.
- The UI status changed to `真实赛程刚刚更新`, so an automatic refresh may have replaced an earlier duplicate before inspection.

## API and Rendering Boundary

- The frontend calls `/api/fixtures?date=tomorrow&league=all` and renders the returned `items`; there is no separate client-side fixture assembly in this path.
- The API route calls `schedule_sync.ensure_fresh()` before reading cached fixtures.
- A direct PowerShell request timed out after 20 seconds while the earlier browser request completed, indicating a transient slow or contended refresh path rather than proving a response-shape failure.
- Cached fixture rows are keyed by fixture `id`; TheSportsDB provider responses are deduplicated only by their event ID before persistence.

## Persistent Cache

- Direct repository access for `2026-09-05` returned exactly nine cached fixtures, matching the loaded UI.
- Every cached tomorrow record currently has a unique `sportsdb-*` ID and no `dongqiudi` external ID.
- The source names printed with mojibake in the PowerShell diagnostic process because of console encoding, while the browser/API boundary still renders Chinese correctly.
- `ScheduleSyncService` refreshes the local window from yesterday through tomorrow and serializes refreshes with one async lock.
- Repository replacement explicitly preserves standalone Dongqiudi rows, so cross-provider identity matching remains relevant even though no such row currently exists tomorrow.

## Cross-Provider Matching

- Dongqiudi schedule import searches existing rows in the same league and matches when kickoff differs by at most 15 minutes and normalized Chinese home/away names are equal.
- A matched Dongqiudi row keeps the existing application fixture ID and adds the Dongqiudi external ID.
- An unmatched Dongqiudi row is inserted with a separate `dongqiudi-*` ID.
- Later TheSportsDB replacement preserves every row carrying a Dongqiudi external ID, but only recognizes same IDs; it does not reconcile a separately inserted Dongqiudi row with an incoming TheSportsDB row.
- Therefore a single missed cross-provider match can become a persistent semantic duplicate. This is a concrete code gap, pending confirmation from stored historical rows or a focused reproduction.

## Full Cache Scan

- A standalone repository scan found 309 cached fixtures and zero pairs with the same league, exact normalized home/away names, and kickoff within 15 minutes.
- The latest durable fixture job on 2026-09-04 recorded `item_count=12`; no duplicate pair appears in the current cache despite the user report.
- The remaining untested case is provider rows whose team aliases differ enough to evade exact-name matching.

## Date-Boundary Lead

- A direct TheSportsDB probe for `2026-09-05` returned nine events, but the set differs from the cached tomorrow list because the provider's event-day date and the app's China-local `fixture_date` can cross UTC midnight.
- Direct SQL inspection corrected the earlier interpretation: all nine rows selected by `fixture_date=2026-09-05` also contain payload `fixture_date=2026-09-05`; the apparent mismatch was only an omitted field in the first diagnostic printout.
- Date-column/payload drift is ruled out for the current tomorrow window.

## Implemented Fix

- Added `deduplicate_fixtures` at the schedule-sync boundary and applied it to public `/api/fixtures` results.
- Records merge only when they share a league, home/away direction, and kickoff within 15 minutes, or share a non-empty external fixture ID.
- Team-name normalization removes only whitespace and the suffixes `足球俱乐部` / `足球队`; reversed teams and matches more than 15 minutes apart remain separate.
- The richer record wins; external IDs from both records are retained for downstream provider linkage.
- The current live tomorrow response remains nine items with zero duplicate identity keys after the fix.

## Verification

- Focused schedule/API tests: 29 passed.
- Full API suite: 241 passed, one existing Starlette/httpx deprecation warning.
- Web ESLint: passed.
- `git diff --check`: passed.
- API process restarted on port 8000 with the fix loaded; direct tomorrow endpoint returned `200`, nine items, and league counts EPL 4 / La Liga 2 / CSL 3.
- In-app browser final refresh was not usable as a verification signal because its request remained pending and the browser kernel timed out; Next logs show the proxied request eventually returned `200` but can take 15+ seconds under current remote-MySQL/automation load.

## Dongqiudi Analysis Follow-up

- Before manual refresh, none of the nine current tomorrow fixtures carried a Dongqiudi external match ID, so the Dongqiudi analysis job had no candidates.
- The latest scheduled Dongqiudi schedule job had run at 2026-09-03 20:32 China time and is configured for a 1440-minute interval; its next due time was about 2026-09-04 20:32.
- The live Dongqiudi match-list endpoint currently exposes two supported tomorrow fixtures: Real Betis vs Real Madrid (`54493212`) and Ipswich Town vs Liverpool (`54483619`).
- Direct read-only probes confirmed both public analysis endpoints return complete `pre_analysis`, attack/defense contrast, and H2H payloads with no errors.
- A manual Dongqiudi schedule sync completed with `item_count=2`, `inserted_count=0`, `enriched_count=2`, and no errors. Both matches were matched to their existing `sportsdb-*` fixtures, so no duplicate rows were created.
- Both fixture-detail APIs now return `context.source=dongqiudi`, the corresponding Dongqiudi match ID, complete analysis payloads, and no analysis errors.
- The remaining seven tomorrow fixtures are not currently present in the provider's supported live window, so they still have no Dongqiudi match ID or analysis.
- The frontend `DongqiudiAnalysisSummary` component only renders availability chips such as `交锋历史`, `近期战绩`, and `攻防对比`; it does not render the actual analysis values or match lists. This is a display gap, not a fetch failure.
- No application code was changed for this diagnostic follow-up. The only state change was the requested-domain manual synchronization of the two currently discoverable fixtures.

## Loading Performance Follow-up

- The API reads a remote MySQL database from `.env` (`47.99.207.112:3306`), so every uncached process start pays network connection/setup latency before Uvicorn is ready.
- FastAPI startup creates the automation loop immediately; its first `run_due()` can perform synchronous database work and multiple external refreshes while the API shares the same event loop.
- The public `FixtureWorkspace` starts with an empty list and waits for `fetchFixtures()`; `fetch` uses `cache: "no-store"`, and there is no browser-side last-success cache.
- The recommended next phase is cache-first/stale-while-revalidate: serve recent fixture data immediately, delay nonessential automation, then refresh in the background. Detail/evidence payloads should remain on demand because they are substantially larger than the fixture list.

## Loading Performance Implementation

- `ScheduleSyncService` now warms persisted fixtures with `asyncio.to_thread`, serves the in-process snapshot immediately, and starts stale refreshes without making the public list await them.
- FastAPI startup now warms the schedule cache first and delays the automation loop by five seconds, reducing contention during the first page request.
- `PredictionRepository` exposes an in-process fixture revision; direct upserts/replacements/evidence writes invalidate the schedule cache before the next read.
- The browser stores only compact fixture-row fields in `localStorage` for 15 minutes, shows them immediately on reopen, and prefetches the opposite date range in the background.
- Live verification after restart: API today list first cached read 504 ms, repeat 185 ms; tomorrow 251 ms. Browser showed one today match (Real Sociedad vs Celta, 0:0) and nine tomorrow matches without a loading-only state after cache warmup.
