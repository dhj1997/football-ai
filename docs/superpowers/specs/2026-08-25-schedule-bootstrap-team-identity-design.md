# Schedule Bootstrap and Team Identity Design

## Problem

The public fixture page reads only the local SQLite cache. A fresh installation therefore shows no schedule until an administrator manually triggers sync. Its status is also derived from the optional API-Football key instead of the configured free schedule provider. Real fixtures contain team IDs and badges, but the mapper discards the badges and stable team information is gated behind paid evidence sync.

## Considered Approaches

1. **API-side on-demand freshness service (chosen).** The fixture read path refreshes an absent or stale cache under one async lock. It keeps credentials and provider behavior inside the API, reuses SQLite, and serves stale data when the upstream is temporarily unavailable.
2. **Startup-only sync.** Simple, but a long-running process becomes stale after the date changes and the first page can race startup work.
3. **Next.js bootstrap through the admin route.** Fast to add, but couples a public read to an admin secret and duplicates backend policy in the web layer.

## Backend Design

- Add a small `ScheduleSyncService` responsible for freshness checks, a process-local async lock, the existing date window, provider calls, persistence, and a compact result status.
- Add `SCHEDULE_CACHE_TTL_MINUTES` with a conservative default. A successful recent sync is reused; an absent or stale cache triggers one refresh.
- Convert the public fixture endpoint to async and call `ensure_fresh()` before reading rows.
- Preserve an existing cache if refresh fails. Report `fresh`, `updated`, `stale`, `failed`, or `unconfigured` without exposing raw upstream errors publicly.
- Keep the admin sync button as a force-refresh path through the same service.
- Calculate the real upstream request count from days times leagues.

## Team Identity Design

- Preserve original team names and home/away badge URLs from the Schedule Day payload.
- Extend the web `Team` type with optional `logo` and `original_name` fields.
- Reuse the current image allowlist and `TeamLogo` component in both fixture rows and the match summary.
- Build the unsynced detail context from fixture identity so both sides remain visible even without API-Football.
- Do not automatically fetch full squads for every fixture; the free API limits and rate budget make that expensive and incomplete.

## Fan Experience

- Status text says whether fixtures were automatically updated, are fresh, are stale, or could not be loaded.
- A successfully synced filter with no matches says there are no matches for that selection, rather than asking for an API key.
- Before evidence sync, show a clear evidence-pending message and suppress zero-derived form/injury conclusions.
- Retain the existing dense operations-desk layout and evidence rail. No visual overhaul is needed.

## Failure Handling

- Fresh cache: return immediately without upstream calls.
- Stale cache plus refresh failure: return cached fixtures with a stale status.
- No cache plus refresh failure: return an empty list with failed status and a retry-oriented UI message.
- Provider not configured: return an explicit unconfigured status.

## Proportional Verification

- Add focused provider mapping assertions for badges and original names.
- Add focused API/service tests for first refresh, fresh-cache reuse, stale fallback, and real request count.
- Run the affected API tests, web lint, and one browser workflow covering initial data, status, badges, and the unsynced evidence state.
- Do not add broad end-to-end matrices or unrelated regression suites.
