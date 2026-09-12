# Scheduled Evidence Refresh Progress

## 2026-09-06

- User requested daily next-seven-day schedule/evidence acquisition and a final-hour lineup refresh.
- Audited current automation, schedule window, evidence providers, and deployed settings.
- Confirmed the deployed analysis flag is false and that current analysis is too coupled to prediction generation for this requirement.
- Created this isolated plan; waiting for the final-hour lineup retry choice before proposing the implementation design.
- User selected two lineup windows: 60 minutes and 30 minutes before kickoff.
- User approved the dedicated evidence/lineup scheduler design.
- Wrote and committed `docs/superpowers/specs/2026-09-06-scheduled-evidence-refresh-design.md` (commit `4da66b7`).
- Spec self-review passed with no placeholders or contradictions.
- Waiting for written-spec review before creating the implementation plan.
- User approved the written specification.
- Implementation plan recorded: configuration/schedule window, daily evidence job, lineup-only provider/markers, focused tests, then production deployment.
- Added independent daily fixture/evidence jobs, a five-minute lineup scanner with durable 60/30-minute markers, and lineup-only provider methods.
- Added China-date daily due semantics, a seven-day schedule lookahead, completeness checks, and 429 retry handling for TheSportsDB's free request window.
- Verification: API full suite passed (248 tests), focused scheduler/evidence tests passed, frontend lint and production build passed.
- Deployed to `47.99.207.112:9000`; production config now disables model analysis by default, refreshes fixtures/evidence daily, and scans lineup windows every five minutes.
- Controlled production run: 36 schedule requests wrote 33 fixtures; evidence refreshed 23 future fixtures; lineup scan completed successfully with no due windows.
- Public tomorrow fixtures now expose API-Football H2H, recent form, availability, and team profiles when the provider returns them.
- Final verification rerun: API full suite passed 248 tests with one existing Starlette/httpx deprecation warning.
- Manually backfilled the originally opened finished fixture once for visibility; it now shows 5 H2H rows, 7 availability entries, and both team profiles while keeping prediction empty.
