# Single-Match Research Workspace Plan

## Goal

Implement the approved single-match research report locally: a compact fixture index plus a report-first match detail that makes model consensus, evidence quality, key factors, source freshness, and prediction eligibility immediately clear on desktop and mobile.

## Scope Guardrails

- Preserve existing fixture, evidence, prediction, bankroll, settlement, and admin behavior.
- Add no news, community, live commentary, authentication, or third-party provider.
- Use only existing structured data for summary text; do not generate or invent evidence.
- Keep API list payloads compact.
- Keep all player display paths behind the existing Chinese-name normalization contract.
- Do not deploy or modify the remote server.

## Phases

### Phase 1: Implementation baseline
- Status: complete
- Read the relevant API routes, types, prediction authorization, detail components, CSS, and tests.
- Establish the smallest compatible API and component changes.

### Phase 2: API and derived contracts
- Status: complete
- Add yesterday and upcoming date filters.
- Add lightweight fixture evidence/prediction summaries.
- Align prediction eligibility for scheduled/live versus terminal states.
- Add focused API tests.

### Phase 3: Match report interface
- Status: complete
- Add pure report derivation helpers.
- Implement report header, decision summary, consensus, key factors, evidence status, and report tabs.
- Preserve detailed evidence, model, betting, and team views.

### Phase 4: Fixture index and responsive polish
- Status: complete
- Add the approved date navigation and compact readiness-rich rows.
- Polish desktop and mobile separately, including focus and reduced-motion behavior.

### Phase 5: Verification and local handoff
- Status: complete
- Run focused and full proportional tests, lint, and production build.
- Start local API and Web services.
- Verify representative scheduled, live/finished, missing-data, desktop, and mobile states in the browser.
- Leave the local application running and provide its URL.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `agent-browser` CLI was not installed | 1 | Used the already available in-app browser for read-only benchmark inspection; installed nothing. |
| Initial visual companion process exited on Windows/WSL boundary | 1 | Restarted the companion with the native Node server and persistent process session. |
