# Scheduled Evidence Refresh Plan

## Goal

Make the default scheduler acquire future fixtures and their evidence on the requested cadence: daily around China midnight for the next seven days plus historical-form, H2H, availability, and team information; and a final-hour lineup refresh before kickoff. Keep model prediction generation separate from evidence acquisition.

## Phases

### Phase 1: Context and requirements
- Status: complete
- Audit current provider fields, scheduler jobs, persistence markers, configuration, tests, and deployed runtime.

### Phase 2: Design approval
- Status: complete
- Resolve final-hour lineup retry behavior, propose approaches, and obtain user approval.

### Phase 3: Implementation plan and code
- Status: complete
- Add `schedule_lookahead_days` and seven-day schedule window.
- Add China-date daily due semantics for fixtures/evidence jobs.
- Add independent daily evidence job with completeness/freshness checks and provider fallback.
- Add lineup-only provider methods and a 5-minute task with durable 60/30-minute markers.
- Keep analysis/prediction and bankroll execution independent.
- Update `.env.example`, README defaults, focused tests, and deployment configuration.

### Phase 4: Verification and deployment
- Status: complete
- Run focused tests, update production config/build, restart services, run one controlled sync, and verify job history/evidence output.

## Known Findings

- Current automation analysis is disabled in the deployed `.env`.
- Current schedule refresh covers `today - lookback_days` through `today + 1` only.
- Current analysis refresh/prediction loop is limited to upcoming scheduled fixtures within `prediction_lead_hours` and only refreshes one evidence fixture per run.
- Current `evidence_needs_enrichment` only detects fewer than three recent matches; it does not detect missing H2H, availability, or team data.
- The target finished fixture has no evidence snapshot, so its empty H2H is expected under the current lifecycle; new daily jobs should target scheduled future fixtures.

## Decision

- Final-hour lineup refresh uses two attempts at 60 and 30 minutes before kickoff; the 30-minute attempt is skipped after an earlier confirmed lineup.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
