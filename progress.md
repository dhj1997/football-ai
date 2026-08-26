# Progress

## 2026-08-26

- Started the active long-running goal.
- Created persistent planning files so progress survives context compaction.
- Phase 1 current-state audit is in progress.
- Read project instructions, README, product/design docs, the existing schedule design, Git history, and current diffs.
- Identified the existing prediction/evidence foundation and the major missing persistence domains.
- Read the complete API entry point, repository, prediction model, evidence provider, schedule providers/services, web API/types, and UI component map.
- Probed API-Football current-season discovery and standings access without exposing credentials; season discovery works, current standings are plan-restricted.
- Probed TheSportsDB current seasons, standings, and season events; current-season discovery works but the default access returns truncated league data.
- Verified a complete no-key standings source for all three target leagues and current-season discovery.
- Wrote the approved whole-system design to `docs/superpowers/specs/2026-08-26-automated-analysis-simulation-design.md` and completed its placeholder self-review.
- Completed the current-state audit. Baseline API tests and web lint both pass.
- Added the ESPN standings provider/service, league snapshot table and repository methods, plus configuration defaults. A combined `main.py` patch failed without changing that file; retrying with smaller patches.
- Integrated the standings service into health, public `/api/standings`, and admin force-sync routes using smaller patches.
- Added focused provider mapping, cache fallback, refresh idempotence, and repository replacement tests.
- Verified the new standings backend: 8 focused tests pass and the full API suite now passes 35 tests.
- Added a dedicated `/standings` route with source/season/freshness states, three-league tabs, complete sortable-by-provider tables, team marks, and responsive horizontal table behavior.
- Extended navigation and image host configuration without changing the existing fixture/admin workflow.
- First standings-page lint run failed on `react-hooks/set-state-in-effect`; applying the established promise-in-effect pattern.
- Standings page now passes lint and production build. A port-listener probe had a PowerShell syntax error and will be retried with captured loop output.
- Started the current API on port 8001. Next.js refused a second dev process because the user's port-3000 process owns the project dev lock; switching the isolated UI check to a production server on port 3001.
- Rebuilt the production bundle with API port 8001. The first production-server launch shape was policy-rejected before execution; retrying without the redundant runtime environment assignment.
- Started the production web server on port 3001 and re-launched the isolated API on port 8001 with the QA origin permitted.
- Verified the standings page in a real browser: current-season data loads for EPL (20 teams), La Liga (20), and CSL (16); no browser console/page errors were reported.
- Visually checked desktop 1440x900 and mobile 390x844 layouts. The document does not overflow horizontally; the 660px table is intentionally scrollable inside its 364px mobile viewport.
- Verified table scrolling reaches the final points column and explicit league-tab switching shows La Liga (20, 2026-27) and CSL (16, 2026).
- Added an ESPN current-team provider with normalized roster, player appearances/statistics, injuries, and current-season match records.
- Added per-team cache persistence, freshness/stale fallback service, and a league-table-validated `/api/teams/{league_key}/{team_id}` endpoint.
- Added a responsive team dossier reached from the standings table, with current roster statistics and current-season match records.
- Browser-verified Arsenal's 30-player roster and one current-season record at desktop and mobile sizes, with only table-local horizontal scrolling and no console errors.
- Completed Phase 2 and started the DeepSeek prediction phase.
- Added immutable evidence snapshots with SHA-256 hashes and prediction linkage.
- Added a backend-only DeepSeek JSON client with bounded timeout/retry, permanent-error handling, strict schema validation, token/request metadata, and price-aware recommendation validation.
- Added the prediction orchestration service: Poisson remains an inspectable baseline; successful DeepSeek probabilities become the main prediction; failures persist an explicit no-bet degraded state.
- Verified a live `deepseek-v4-flash` request using the configured key without printing secrets: returned model matched, probabilities totaled 1.0, and missing odds correctly produced `no_bet` (1423 total tokens).
- Added an admin-protected immutable evidence snapshot inspection endpoint.
- Full API suite passes 47 tests after DeepSeek integration. Completed Phase 3 and started bankroll/settlement/metrics.
- Added simulated bet, append-only bankroll transaction, and prediction settlement persistence with atomic placement/return operations.
- Added deterministic stake caps, price matching, current cash/equity/exposure/realized P&L/ROI/hit rate/drawdown summary, bet history, and public endpoints.
- Added idempotent 1X2/Asian handicap settlement, correctness/Brier evaluation, season-aware metric filters, and admin settlement endpoints.
- A cap test caught cent rounding above the exact 2% threshold; stake sizing now floors to whole cents and the focused suite passes.
- Enforced one open bet per fixture across prediction versions while preserving same-prediction idempotency.
- Full API suite passes 55 tests and the live service reports initial cash/equity 1000, zero exposure/P&L, DeepSeek configured, and zero metric samples.
- Completed Phase 4 and started durable scheduling.
- Added `job_runs` persistence and configuration for recurring fixture, standings, analysis, and settlement jobs.
- Added a FastAPI lifespan-owned automation loop with durable due checks, failed/partial backoff, shared manual/background locking, and bounded run diagnostics.
- Added upcoming-match evidence refresh, preliminary/confirmed-lineup prediction rules, model retry delay, simulated bet placement, and finished-fixture settlement jobs.
- Live first run persisted fixture sync (4 items), standings sync (3 items), settlement success, and an analysis partial caused by API-Football's 10-request/minute plan limit.
- Adapted automation to refresh at most one API-Football fixture per five-minute analysis run while continuing to use cached evidence for other candidates.
- Added a true-data partial-evidence fallback using cached TheSportsDB team/squad data and recent results. It explicitly omits H2H, injuries, lineups, and odds; no bet can be placed from it.
- Live fallback produced two partial evidence snapshots and DeepSeek `no_bet` predictions. One empty model response was retained as a failed baseline, then succeeded after raising the configurable output cap to 3000 tokens.
- Added responsive performance and operations surfaces: cash/equity/exposure/P&L/ROI/accuracy/Brier/drawdown, bet and settlement ledgers, league/season/date/model filters, DeepSeek audit detail, and durable job status/actions.
- Browser-verified the performance page, operations cards, and DeepSeek fixture detail at desktop and mobile widths with no page-level horizontal overflow or console errors.
- Completed Phases 5 and 6; started final verification and requirement audit.
- Updated README for continuous automation, providers, DeepSeek-only backend configuration, simulated bankroll, routes, process supervision, and model boundaries.
- Security audit passed: no tracked or frontend secret patterns, no legacy model-key variables, `.env` ignored, and `git diff --check` exit 0.
- Final live audit: health ok, automation and DeepSeek enabled, current standings EPL 20 / La Liga 20 / CSL 16, cash/equity 1000, zero exposure, durable job history present.
- Closed the final contract gaps: evidence snapshots now include current standings, DeepSeek returns a separate Asian-handicap assessment, metrics aggregate Asian outcomes and data completeness, and the performance page renders an equity curve.
- Live schema verification passed: DeepSeek completed, Asian line unavailable/none, data completeness 0.4286, ESPN 2026-27 ranks 12/7 in the immutable snapshot, and snapshot hash matched.
- Added deterministic bet eligibility gates: at least 70% evidence completeness, 60% model confidence, 3% expected price edge, plus all existing price and exposure limits.
- Final live UI/API audit passed after the last build: 9 performance summaries, five Asian settlement categories, equity curve, 20/20/16 standings, DeepSeek/automation enabled, and no responsive overflow or browser errors.
- Final security audit passed again after removing the QA environment file: diff check 0, tracked secret files 0, legacy variable files 0, root `.env` ignored.
- Final API suite passes 64 tests and the final Next.js production build passes. All original goal requirements are now covered.
- Final API suite passes 62 tests; web lint and latest production build pass. A final objective reread found four remaining contract gaps: standings in evidence snapshots, an explicit DeepSeek Asian-handicap assessment, aggregate Asian/data-completeness metrics, and a visible bankroll curve. Phase 7 remains in progress until they are closed.
- Diagnosed the affected finished La Liga fixture: hourly schedule replacement erased mutable evidence while immutable prediction snapshots remained available.
- User approved the minimal preservation-and-recovery design; documented it in `docs/superpowers/specs/2026-08-26-fixture-evidence-preservation-design.md` and started Phase 8.
- Updated `PredictionRepository.replace_fixtures` to merge durable evidence fields from the existing same-ID fixture before replacing provider-owned schedule data.
- Added idempotent `restore_fixture_evidence_from_latest_snapshot` and focused tests for preservation plus latest-snapshot recovery.
- Focused repository and schedule-sync regression suite passes: 12 tests.
- First full API run: 65 passed, 1 failed because `test_real_fixture_requires_synced_evidence` reused a fixture whose evidence now correctly survives refresh; updating test isolation without weakening production behavior.
- Isolated the no-evidence API contract test with a distinct fixture ID so it no longer depends on destructive refresh semantics.
- Targeted failed test now passes; full API suite passes 66 tests with one external Starlette deprecation warning.
- Stopped the old API, restored the affected fixture from its latest immutable snapshot, then completed one controlled API-Football evidence refresh while background quota contention was absent.
- Full evidence now includes one recent result per side, five H2H matches, twelve unavailable players, and confirmed 23-player match squads per side.
- Restarted the updated API on port 8000 and ran a real nine-request fixture refresh; the evidence remained intact.
- Browser verification on port 3000 shows recent form 1/5, H2H 5, availability 12, and confirmed lineups with no page errors. Phase 8 is complete.
- ESPN current-scoreboard and event-summary feeds were verified for La Liga without an extra key.
- Added and self-reviewed the ESPN evidence design; Phase 9 now targets API-Football -> ESPN -> TheSportsDB.
- Removed the retired public fallback implementation and replaced it with `EspnEvidenceProvider` plus a standalone `EvidenceProviderChain`.
- Added ESPN tests for event matching, recent form, H2H, match lineups, rosters, injuries, odds conversion, and fallback ordering.
- Full API suite passes 72 tests; web lint/build and `git diff --check` pass.
- Live ESPN evidence mapping succeeded for Valencia vs Real Betis: 5 recent matches per side, 5 H2H matches, confirmed lineups, 31/28 squad players, and odds.
- Restarted API on port 8000. Health reports `api-football -> espn -> thesportsdb-partial`; automation remains enabled. Phase 9 is complete.
- Diagnosed the Real Madrid vs Real Sociedad form issue: the cached API-Football context had only one result per side while ESPN returned five.
- Added incomplete-form enrichment through ESPN/public evidence, field-aware evidence merging, and cache-read player-name localization; added reviewed Chinese aliases for the current Real Madrid and Real Sociedad squad data plus provider abbreviations.
- Recorded the mandatory Chinese player-name display rule in root `AGENTS.md` and removed original English player names from both roster UI surfaces.
- Live API verification confirms the target fixture now has five recent matches per side, Real Madrid form `D W W W W`, source `api-football-single-fixture+espn-evidence`, and zero untranslated squad-player names.
- Focused API suite passes 17 tests (one external deprecation warning); web lint passes; browser screenshot on port 3000 confirms the tomorrow view displays `近期战绩（5/5）` and Real Madrid `4胜 1平 0负`.
- User approved a score-center redesign: bright professional score-site visual system, fixture-first homepage, dedicated match details, and unified standings/team/performance screens. Phase 11 is in progress; no backend contract changes are planned.
- Added the `/matches/[fixtureId]` match-center route, fixture-first score-center home, match detail tabs, and the shared professional score-site visual system. Browser QA has covered the public desktop and 390px mobile score center plus match center; no document-level horizontal overflow was detected.
- Completed Phase 11. Web lint and Next production build pass. The final browser pass verified the 1440px score center and the 390px Real Madrid match center (five working tabs including odds) with no document-level horizontal overflow or page errors. The local API is healthy on port 8000 and the Web server runs on port 3000.
- Completed Phase 12. The match-center preliminary prediction panel now has a manual-generation control that uses the existing server-side admin proxy, shows a busy state, refreshes the current prediction on success, and reports errors inline. Browser verification confirmed the enabled control on the scheduled Real Madrid fixture without creating a prediction or a simulated bet; web lint and production build pass.
- Completed Phase 13. Fixed the Asian handicap display so an away selection at a home `-1.5` market renders as `皇家社会 +1.5`. The UI now labels the deterministic calculation as `Poisson 基线倾向`, identifies AI/baseline disagreement, and preserves the saved formal `不下注` recommendation. Web lint/build pass and browser verification confirmed all corrected labels for the Real Madrid fixture.

- Completed Phase 14. Increased DeepSeek assessment body text to 15px on desktop and 14px on mobile, with more line height; also raised match-data, table, and navigation typography without changing API contracts. Web lint and production build pass. Browser QA confirms desktop 15px/mobile 14px assessment text, no document-level overflow, and no page errors.
- Completed Phase 15. Raised the full interface baseline to 14px and increased normal controls, fixture rows, match details, evidence, tables, standings, team, and performance typography. Browser QA confirms desktop detail text (body 14px, navigation 14px, section headings 19px), mobile standings cells 12px/headers 11px, no document-level overflow, and no page errors.
- Completed Phase 16. Added an optional `api.quya.org/v1` ChatGPT Responses provider for `gpt-5.6-sol`, used only after a configured DeepSeek request fails. The shared model chain preserves strict football JSON and betting validation and avoids duplicate successful requests. Added one blank local `API_CHATGPT_KEY` entry plus tracked example configuration. Restored AI assessment padding to 24px/20px desktop and 20px/16px mobile. Full API suite passes 77 tests; Web lint/build and desktop/mobile browser QA pass.
- Live ChatGPT gateway verification completed after the local key was configured: authenticated model discovery included `gpt-5.6-sol`, and one non-persisted minimal Responses request returned the requested model, passed strict assessment validation, and correctly selected `no_bet` for empty evidence. No key value was logged or stored in project records.
- Started Phase 17 design for independent parallel DeepSeek and GPT-5.6 Sol predictions, bankrolls, bets, settlements, and comparison metrics. Restored planning context and verified the official model supports the required structured Responses contract; no Phase 17 application code has been changed yet.
- Phase 17 visual brainstorming selected layout A: two complete model prediction/investment cards shown side by side on desktop and stacked on mobile, with direct bankroll and accuracy comparison.
- Phase 17 bankroll choice recorded: each model may independently invest up to all currently available simulated cash, with no percentage or daily exposure cap; balances cannot go negative and no real-money execution is permitted.
- Phase 17 comparison start choice recorded: archive existing DeepSeek history without deletion and begin a new common dual-model competition with two independent 1000-unit accounts.
- Completed Phase 17. Added provider-keyed parallel prediction execution, active competition/account persistence, independent balance/bet/settlement/metrics scoping, and legacy-history isolation.
- The active `dual-model-v1` competition initialized DeepSeek and GPT-5.6 Sol at 1000 each. Recommendations can independently select 0%-100% of available simulated cash; matching real odds, non-negative cash, evidence completeness, confidence, and simulated-only execution remain enforced.
- Added side-by-side desktop and stacked-mobile prediction cards, one manual parallel-generation control, and a performance comparison strip with model-specific account, curve, ledger, accuracy, and profit views.
- Live Real Madrid vs Real Sociedad verification completed both models: DeepSeek selected a 20% simulated stake (200.0) and GPT-5.6 Sol selected a 4% stake (39.2 from its then-current 980 balance). Both model results and bets are stored independently.
- DeepSeek complex evidence required a 90-second timeout and 8000-token output budget. GPT no-bet responses that omit an Asian-handicap side are normalized to an unavailable handicap view; any actual bet still requires a valid selection and matching odds.
- Final verification: 79 API tests pass, Web ESLint and Next.js production build pass, API health is OK, both models are configured, fixture detail exposes two completed predictions, and match/performance routes return HTTP 200. Browser automation screenshot QA was unavailable because the local browser-control kernel could not create its runtime asset path.
- Fixed English model prose leaking into the Chinese UI. DeepSeek and GPT prompt contracts are now v2, every user-facing summary/reason/risk/missing-evidence field must contain Chinese or the provider retries, and degraded states use Chinese text. Regenerated the Real Madrid fixture successfully in Chinese while retaining immutable English history and its existing model positions. Full API suite now passes 80 tests.
- Fixed the stale single-model UI by rebuilding and restarting the port-3000 Next.js production server. Both DeepSeek and GPT predictions are present in the live fixture response and now render through the dual-card layout.
- Separated current recommendations from previously executed positions. A latest `no_bet` recommendation displays “本次模型建议：本场不下注”, while an earlier still-open bet displays as “历史版本持仓” with an explicit note that immutable prior execution is not retrospectively cancelled. Web lint/build pass and the updated match route returns HTTP 200.
- Replaced side-by-side dual prediction cards with the approved B layout: desktop uses a left model Tab rail and one complete right prediction panel; mobile uses compact horizontal Tabs above the panel. Tabs summarize outcome, current recommendation, and current/historical position without changing model data.
- Added accessible `tablist`/`tab`/`tabpanel` semantics, roving focus, arrow-key cycling, and Home/End navigation. Live QA verified DeepSeek/GPT switching, 390px mobile layout with no page overflow, no console/page errors, and corrected non-wrapping recommendation rows. Web lint and production build pass; port 3000 was restarted with the new build.

## Verification Log

| Command | Result |
|---|---|
| `apps/api/.venv/Scripts/python.exe -m pytest -q` | PASS: 30 tests, 1 dependency deprecation warning |
| `apps/web pnpm lint` | PASS |
| `apps/api/.venv/Scripts/python.exe -m pytest -q tests/test_league_provider.py tests/test_league_sync.py tests/test_database.py` | PASS: 8 tests |
| `apps/api/.venv/Scripts/python.exe -m pytest -q` after standings backend | PASS: 35 tests, 1 dependency deprecation warning |
| `apps/web pnpm lint` after standings page | PASS |
| `apps/web pnpm build` after standings page | PASS; `/standings` included |
| Browser QA on API 8001 / web 3001 | PASS: 3 leagues, complete table counts, desktop/mobile layout, no console errors |
| `pytest -q tests/test_team_provider.py tests/test_team_sync.py tests/test_database.py` | PASS: 9 tests |
| Team page browser QA on API 8001 / web 3001 | PASS: standings navigation, 30 roster rows, season record, desktop/mobile overflow, no console errors |
| `pytest -q tests/test_deepseek_provider.py tests/test_prediction_service.py tests/test_database.py tests/test_api.py` | PASS: 18 tests, 1 dependency deprecation warning |
| Full API suite after DeepSeek integration | PASS: 47 tests, 1 dependency deprecation warning |
| `pytest -q tests/test_bankroll.py tests/test_settlement.py tests/test_database.py tests/test_api.py` | PASS: 18 tests, 1 dependency deprecation warning |
| Full API suite after bankroll/settlement | PASS: 55 tests, 1 dependency deprecation warning |
| Live bankroll/metrics health on API 8001 | PASS: initial/cash/equity 1000, simulated true, DeepSeek configured, no samples yet |
| `pytest -q tests/test_automation.py tests/test_database.py tests/test_api.py` | PASS: 18 tests, 1 dependency deprecation warning |
| Live first automation cycle on API 8001 | Durable runs recorded: fixtures success 4, standings success 3, settlement success 0, analysis partial with bounded rate-limit errors |
| `pytest -q tests/test_automation.py tests/test_bankroll.py tests/test_settlement.py` after quota adaptation | PASS: 9 tests |
| Live quota fallback analysis | PARTIAL by design: 2 real partial evidence contexts, DeepSeek no-bet prediction, 0 bets, bankroll/equity 1000 |
| DeepSeek retry with 3000 output tokens | PASS: completed, model `deepseek-v4-flash`, no-bet, immutable snapshot, 2621 tokens |
| Web performance/operations/prediction browser QA | PASS: desktop/mobile, filters, statuses, audit metadata, no overflow/console errors |
| Final full API suite | PASS: 62 tests, 1 external dependency deprecation warning |
| Final web validation | PASS: ESLint and Next.js production build, 10 routes |
| Secret/config audit | PASS: tracked secret patterns 0, frontend secret refs 0, ignored `.env`, expected DeepSeek model/key presence verified without outputting key |
| Final live runtime audit | PASS: health, automation, DeepSeek, 20/20/16 standings, 1000 simulated equity, durable jobs |
| Final full API suite after contract-gap audit | PASS: 63 tests, 1 external dependency deprecation warning |
| Standings/AH/completeness/curve browser and live-model audit | PASS: strict model schema, snapshot ranks/hash, desktop/mobile curve, no overflow/errors |
| Final verification after deterministic bet gates | PASS: 64 API tests, web lint/build, live API/browser/security audit |
| Fixture evidence preservation regression | PASS: 12 focused tests and 66 full API tests |
| Live evidence restore, provider refresh, and browser check | PASS: evidence retained after schedule refresh; form/H2H/availability/lineups render on port 3000 |
