# P0 Prediction Integrity Architecture

## Goal

Implement the approved P0 architecture changes from `football-ai P0 架构改造任务.md` with minimal backend-only changes, preserving existing APIs and frontend behavior.

## Phases

### Phase 1: Model forecast separation
- Status: complete
- Remove market blending from deterministic prediction generation.
- Preserve `probabilities` as pure model probabilities and expose explicit forecast aliases.

### Phase 2: Immutable evidence and odds snapshots
- Status: complete
- Add immutable odds snapshot persistence and prediction linkage.
- Ensure evidence snapshots are content-addressed and never overwritten.

### Phase 3: Prediction freeze and layer boundaries
- Status: complete
- Make prediction persistence insert-only for forecast/evidence/timestamps.
- Keep market, risk, portfolio, execution, and settlement as derived/lifecycle data.

### Phase 4: Settlement and metrics integrity
- Status: complete
- Ensure settlement reads frozen prediction data and forecast metrics use pure model probabilities.

### Phase 5: Regression tests and full verification
- Status: complete
- Add P0 tests, run API/web/migration/lint/build checks, and record results.

## Constraints

- No frontend UI changes.
- No prompt changes, extra models, calibration, full CLV, Kelly, or unrelated refactors.
- Preserve existing data and SQLite/MySQL compatibility.
- All player names shown through existing Chinese-name localization rules.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `apps/api/.venv/Scripts/python.exe` not found from `apps/api` cwd | 1 | Re-run with `.venv/Scripts/python.exe` from the API directory |
| Temporary SQLite migration probe left an open Windows file handle during cleanup | 1 | Migration itself passed; dispose the SQLAlchemy engine before cleaning a temp directory |
