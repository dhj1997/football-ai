# Progress

## 2026-08-27

- Created the active Codex Goal with measurable completion evidence.
- Read `AGENTS.md`, root long-running planning context, and the current dirty worktree context.
- Created an isolated seven-phase implementation plan.
- Phase 1 is in progress.
- Verified the existing localization traversal and ESPN roster snapshot fields for Phase 1.
- Traced the prediction-to-bankroll path and confirmed that LLM-owned market selection and stake sizing must be replaced by deterministic backend output.
- Compared both model providers and identified the exact shared-contract boundary and transport-only differences.
- Audited public response boundaries and confirmed that recursive supplier-field sanitization is required in addition to local name conversion.
- Confirmed the concrete ID fields that injury and lineup mapping currently discard and the hard-coded lineup-strength shortcut to replace.
- Verified which player statistics are actually available and defined the observed-versus-estimated boundary for contribution inputs.
- Audited current aliases and log call sites; identified four concrete cached-injury aliases to add and no direct player-name logging path.
- Implemented the player identity module, provider-ID retention, reviewed-name fallback, and four missing cached-injury aliases.
- Python compilation passed. Focused provider/identity-adjacent tests: 14 passed, 1 expected contract failure pending test update.
- Updated the legacy name expectation, added identity-link/unresolved/public-sanitization tests, and wired public payload sanitization into fixture, standings, team, prediction, and evidence responses.
- Phase 1 focused API/provider suite: 27 passed.
- Added an HTTP contract fixture containing a legacy unknown English player name to prove response-time sanitization and stable ID exposure.
- Phase 1 complete: HTTP/provider/identity suite passed 29 tests with zero known supplier-English player names in the tested public payload.
- Phase 2 started.
- Located the baseline integration point: replace hard-coded lineup-strength multipliers with player-impact attack retention when valid, with a neutral incomplete-data fallback.
- Implemented `player-impact-v1`, wired it into prediction creation and fixture detail, and added its fields to model input.
- Phase 2 focused contribution/prediction/API suite: 25 passed.
- Phase 2 complete: all five required player-impact behaviors have focused passing tests.
- Phase 3 started with the documented no-authorized-source outcome; implementation will remain provider-only and null-safe.
- Chose the existing manual snapshot/upsert repository pattern for durable player-value cache and provenance.
- Implemented the provider protocol, Null Provider, authorization/coverage gate, durable cache, provenance/freshness, and null-safe enrichment.
- Phase 3 focused repository/provider/API suite: 31 passed.
- Phase 3 complete; Phase 4 started.
- Traced dual-model persistence and bankroll execution; fixed the Phase 4 boundary at per-model deterministic decisions with backend-only bounded sizing.
- Implemented deterministic market assessment/decision output and switched bankroll execution to backend `decision` fields with a hard 2% cap.

## Errors

- Two initial planning-note patches used heading text that did not match the generated files. Reread the exact files and reapplied a scoped patch without changing application code.
- A read-only PowerShell `foreach` aggregation contained an empty pipeline element and failed before reading files; switched to capped per-file reads.
- A read-only `rg` call used Unix-style wildcard path arguments that PowerShell passed literally; switched to explicit paths and `Get-ChildItem`.
- The first focused test run failed one legacy assertion that expected an unknown supplier player name (`Home Player`) to remain public. The new hard boundary correctly returned the Chinese unresolved placeholder; the test contract will be updated.
- Phase 4's first focused run compiled successfully and failed only three legacy bankroll assertions that still supplied LLM recommendations or expected 25%-50% uncapped stakes. Those contracts are intentionally superseded by deterministic bounded execution.
- One Asian-handicap test initially expected 10.25% edge, but exact half-win/push/half-loss settlement sums to a 27.75% edge. Corrected the test arithmetic; implementation output was correct.
- Phase 4 focused decision/bankroll/API suite: 25 passed.
- Phase 4 complete; Phase 5 started.
- Audited both provider and settlement tests for the forecast-only PromptContract migration; no settlement architecture change is required.
- Implemented `football-forecast-v3`, migrated both providers and PredictionService, and removed LLM recommendation/stake authority from the schema.
- Phase 5 focused provider/prompt/prediction/settlement suite: 25 passed.
- Full API suite after Phase 5: 101 passed, one existing Starlette/httpx deprecation warning.
- Phase 5 complete; Phase 6 started.
- Applied the approved UI direction from the user task: preserve the professional score-center language and replace only the legacy prediction surface with a controlled-density three-layer analysis.
- Audited public-name compatibility and the real cached prediction migration path before frontend edits.
- Implemented the player-impact panel and the outcome/value/execution prediction bands while preserving TASK_03-08 structure and tokens.
- Frontend lint passed, TypeScript `--noEmit` passed, and the Next.js production build completed successfully (10 static/dynamic routes generated).
- Prepared browser verification with free ports 3000/8000 and the existing real cache connection.
- Started API on 8000 and Next dev server on 3000; both health checks returned HTTP 200.
- Completed Phase 6 UI, including player impact/value provenance and forecast/value/execution bands.
- Desktop 1440px and mobile 390px browser checks found no page-level horizontal overflow or console errors; real fixture data and both model tabs rendered.
- Browser QA exposed and fixed stale Asian-line reuse; added a focused regression test.
- Phase 6 complete; Phase 7 started.
- Final API suite: 105 passed with one existing Starlette/httpx deprecation warning.
- Final frontend lint, TypeScript check, and production build passed.
- Final desktop/mobile screenshots and browser report saved under `.artifacts/player-impact-decision/browser/`.
- Phase 7 complete; all Goal completion criteria have verification evidence.

## Errors

- A single `apply_patch` attempted delete-and-readd operations for the same provider paths, which the patch tool rejects. The patch was atomic and made no changes; split the contract and provider replacements into separate patches.
- The first Web `Start-Process` used a nonexistent fixed npm path; resolved `npm.cmd` via `Get-Command` and started successfully.
- A combined background-start/health-loop PowerShell command was rejected by local execution policy; split it into two scoped commands and both services became healthy.
- A PowerShell summary accidentally used reserved `$HOME`, and a later `foreach` result was piped without first assigning it. Both were read-only diagnostics; renamed the variable and used an explicit result collection.
- Initial 3000/8000 checks reached pre-existing old processes. Left them untouched and moved this task to isolated 3002/8001 services.
- Next dev refused a second server from the same directory because of its lock. Created an artifact-only source copy with a shared `node_modules` junction for isolated 3002 verification.
- An unquoted agent-browser `@e22` ref was consumed by PowerShell; quoted the ref. The off-screen tab required `scrollIntoView`/DOM click for the interaction check.
