# Performance Dashboard Timeout Fix

## Problem

The production performance dashboard fails when its data requests pass through
the Web proxy's four-second deadline. The page currently requests the complete
decision audit twice. Each API response then performs one additional bet lookup
per prediction. The model-evaluation read route also recomputes the complete P6
experiment before checking persisted results.

## Selected Design

1. Add a repository batch read for bets keyed by prediction ID and use it in the
   decision API. Preserve the response contract and audit fields.
2. Fetch the all-model decision list once in the dashboard and derive the
   selected-model rows in the browser. Keep selected-model bets and metrics as
   separate requests because their contracts differ.
3. Make the default model-evaluation GET return the newest persisted experiment.
   Run a new deterministic evaluation only when no persisted experiment exists;
   explicit experiment-ID reads remain unchanged.
4. Keep the normal proxy deadline at four seconds. Give only the existing
   heavyweight backtest and model-evaluation read routes a bounded 30-second
   deadline as a cold-start fallback.

## Alternatives Rejected

- Raising every proxy timeout would hide the N+1 query and increase failure
  latency across unrelated pages.
- Adding a new cache or summary table would be unnecessary for the current data
  volume and would introduce invalidation and migration work.

## Verification

- Focused repository/API tests cover batch bet lookup and persisted-evaluation
  reuse.
- Web lint and TypeScript checks cover the request deduplication and timeout map.
- Production verification measures each affected route, renders `/performance`
  in a browser, and confirms no `upstream_timeout` response.

