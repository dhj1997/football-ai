# Squad Coverage Production Audit

## Goal

Quantify production squad/player coverage for upcoming fixtures, identify the concrete missing teams, and attribute each gap to the provider/backfill pipeline.

## Phases

### Phase 1: Inspect current contracts
- Status: complete
- Confirm roster storage, fixture fallback fields, provider support, and backfill limits.

### Phase 2: Measure production coverage
- Status: complete
- Query production fixture/team snapshots and recent squad backfill job runs.

### Phase 3: Attribute missing teams
- Status: complete
- Classify gaps by missing Dongqiudi twin/team ID, empty provider roster, or unsupported route.

### Phase 4: Report
- Status: complete
- Give exact counts, affected teams, and the smallest recommended remediation.

### Phase 5: Implement approved optimization
- Status: complete
- Align Dongqiudi lookahead with seven-day fixtures, increase bounded backfill cadence, and retry empty squads after the existing cache TTL.

### Phase 6: Verify and deploy
- Status: complete
- Run risk-proportionate tests, deploy without committing, force bounded catch-up jobs, and remeasure production coverage.

## Constraints

- Diagnosis only; do not change application behavior without a follow-up request.
- Preserve the existing dirty worktree and the deployed odds optimization changes.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell loop piped directly after a block caused an empty-pipe parser error | 1 | Use an array-producing pipeline instead. |
| First unrestricted fixture payload read was too slow over remote MySQL | 1 | Stop only the diagnostic process and filter to the next 14 days in SQL. |
