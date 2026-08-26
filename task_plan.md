# Football AI Long-Running Goal Plan

## Goal

Complete the approved three-league pre-match analysis and simulated betting system described by the active Codex goal. Preserve the full scope and existing user changes.

## Phases

### Phase 1: Current-state audit

- Status: complete
- Read project instructions, docs, designs, Git state, code, tests, and current runtime contracts.
- Map every explicit goal requirement to current evidence and missing work.

### Phase 2: League and squad data

- Status: complete
- Implement current-season discovery and real data for standings, fixtures, teams, players, appearances, lineups, and injuries for CSL, La Liga, and Premier League.
- Expose source, season, freshness, empty, stale, and failure states.

### Phase 3: DeepSeek predictions

- Status: complete
- Persist immutable evidence snapshots and structured DeepSeek predictions while retaining the Poisson baseline.
- Enforce backend-only secrets, timeouts, bounded retries, schema validation, and explicit degradation.

### Phase 4: Settlement, metrics, and bankroll

- Status: complete
- Settle finished fixtures, calculate 1X2 and Asian handicap results, Brier score, and filterable metrics.
- Implement a 1000-unit simulated bankroll with exposure limits, immutable bets, settlement, ROI, hit rate, and drawdown.

### Phase 5: Durable scheduling

- Status: complete
- Add idempotent persistent jobs for synchronization, prediction, settlement, aggregation, bounded retry, and run history.

### Phase 6: Product surfaces

- Status: complete
- Complete public and admin desktop/mobile workflows for standings, team data, predictions, metrics, bankroll, and operational states.

### Phase 7: Verification and completion audit

- Status: complete
- Run the full API test suite, web lint and build, then launch both services for browser verification on desktop and mobile.
- Audit every goal requirement against authoritative evidence before marking complete.

### Phase 8: Fixture evidence preservation repair

- Status: complete
- Preserve durable evidence fields during hourly fixture replacement.
- Restore the affected finished fixture from its latest immutable evidence snapshot.
- Add focused repository regression tests and verify the live page after refresh.

### Phase 9: ESPN evidence fallback

- Status: complete
- Add an ESPN public-data adapter and provider chain.
- Preserve explicit source, failure, and completeness metadata across fallbacks.
- Add focused provider/chain tests, update configuration docs, and verify the running service.

### Phase 10: Incomplete evidence and Chinese player names

- Status: complete
- Detect scheduled-fixture evidence with fewer than three recent matches for either team and enrich it through ESPN/public data without consuming API-Football quota.
- Merge enriched fields without losing existing richer evidence, localize cached player records at read time, and record the mandatory Chinese-name rule in `AGENTS.md`.

### Phase 11: Professional score-center UI

- Status: complete
- Replace the dashboard-style presentation with a professional football score center across fixtures, match detail, standings, team, and performance pages.
- Preserve API/data behavior, create a dedicated match-detail route, and verify responsive desktop/mobile workflows.

### Phase 12: Manual preliminary prediction

- Status: complete
- Add a public match-center control for manually regenerating a scheduled fixture's preliminary prediction through the existing server-side admin proxy.

### Phase 13: Asian handicap direction clarity

- Status: complete
- Correct away-handicap display polarity and distinguish DeepSeek's directional view from the Poisson baseline when they disagree.

### Phase 14: Typography legibility

- Status: complete
- Increase the DeepSeek assessment, match-data, table, and navigation typography while retaining the compact score-center layout on desktop and mobile.

### Phase 15: Global typography scale

- Status: complete
- Raise the whole application's reading baseline across score center, match detail, standings, team, and performance pages instead of limiting the change to the DeepSeek assessment.

### Phase 16: Optional ChatGPT model fallback

- Status: complete
- Add an optional `gpt-5.6-sol` Responses API fallback through `api.quya.org`, keep secrets server-side, preserve strict prediction validation, and restore assessment padding on desktop and mobile.

### Phase 17: Independent dual-model competition

- Status: complete
- Design two parallel DeepSeek and GPT-5.6 Sol prediction tracks, independent 1000-unit simulated bankrolls, model-owned investment decisions, settlement, metrics, and side-by-side product views.

## Constraints

- Do not revert or overwrite user changes.
- Do not expose secrets or use demo data as real data.
- Do not connect to a bookmaker or execute real-money transactions.
- Prefer the smallest reliable design compatible with the current architecture.
- Add only risk-proportionate tests.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| API-Football current standings rejected by configured free plan | 1 | Keep current-season discovery, investigate the existing free provider for standings, and preserve an explicit unavailable state if no licensed source exists. |
| Combined `main.py` standings patch did not match current line context | 1 | Re-read tight line ranges and apply smaller import, initialization, health, and route patches. |
| Frontend lint rejected synchronous state updates through an effect-invoked callback | 1 | Use the existing project pattern: start the initial promise directly inside the effect with an active flag; keep the stateful callback only for manual refresh. |
| PowerShell listener probe used an invalid pipeline directly after `foreach` | 1 | Assign loop output to a task-specific variable before formatting. |
| Next.js refused a second dev server for the same project directory | 1 | Keep the user's port-3000 dev process intact; build with the test API URL and run the production server on port 3001. |
| PTY launch combining an environment assignment with `pnpm start` was rejected by execution policy | 1 | The public API URL is already embedded by the successful build; launch `pnpm start` without the redundant assignment. |
| Browser screenshot command stored relative paths in the agent-browser temporary directory | 1 | Use the returned absolute screenshot paths for visual QA; source and product files were unaffected. |
| First browser league-switch probe matched repeated text and reused a global JavaScript identifier | 1 | Re-run with explicit `.league-filter button:nth-child(...)` selectors and isolated evaluation expressions. |
| PowerShell `Invoke-RestMethod` probe to ESPN was denied by the edge node | 1 | Probe with the application's `httpx` client and browser-like headers; this does not affect the already verified cached provider call. |
| A combined inspection command referenced a nonexistent `apps/api/requirements.txt` | 1 | Use the authoritative dependency list in `apps/api/pyproject.toml`; no application file was affected. |
| First DeepSeek smoke-test one-liner placed `async def` after a semicolon | 1 | No request was sent; retry with a direct `asyncio.run(provider.assess(...))` expression. |
| Bankroll cap test found cent rounding could exceed 2% by a fraction of a cent | 1 | Floor stake amounts to whole cents after applying all exposure caps. |
| Same-fixture exposure guard initially masked same-prediction idempotency | 1 | Return an existing prediction-linked bet first, then reject new prediction versions for an already-exposed fixture. |
| First automation `main.py` patch used mojibake text as context | 1 | Re-read the file explicitly as UTF-8 and patch against stable import/assignment anchors. |
| Follow-up PowerShell inspection had an unterminated quoted `rg` pattern | 1 | Split the UTF-8 file read and use a single-quoted search pattern. |
| First live analysis run exceeded API-Football's 10 requests/minute plan limit | 1 | Persisted as a partial run; cap evidence refresh to one fixture per run and run analysis every five minutes. |
| PTY policy again rejected setting `API_BASE_URL` inline while starting Next.js | 1 | Use ignored `.env.production.local` for the isolated port-8001 QA proxy, then start the server separately. |
| First sanitized prediction-state probe used literal `\n` in a Python one-liner | 1 | Re-run with a list comprehension that requires no multiline statement. |
| One live DeepSeek prediction returned empty content with a 1200-token output cap | 1 | Persisted an explicit failed baseline and raised the configurable output budget to 3000 before retrying. |
| Stake-edge patch temporarily split `_matching_price` before its key mapping | 1 | Detected before tests; restored the complete price function and kept edge calculation separate. |
| Full API suite exposed a test that reused `api-123` and relied on fixture refresh clearing prior evidence | 1 | Keep the new preservation contract and isolate the no-evidence API test with a distinct fixture ID. |
| Planning session catch-up helper was not installed at the skill's expected path | 1 | Existing root planning files were read directly; no unsynchronized context was reported or assumed. |
| Visual companion start script was invoked with Windows paths under WSL bash | 1 | No files were changed; retry with `/mnt/c` and `/mnt/d` paths expected by the active bash runtime. |
| Visual companion background server was reaped after the launcher exited | 1 | The mockup file remains intact; restart the server explicitly with `--foreground` in a persistent execution session. |
