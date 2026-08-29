# P1 Evaluation Integrity

## Goal

Implement CLV, calibration, fair model-vs-market evaluation, and data-backed quality gates on top of the merged P0 architecture without changing forecast generation, prompts, UI, or freeze/settlement semantics.

## Phases

### Phase 1: Evaluation primitives
- Status: complete
- Add closing-odds selection, decimal CLV, calibration bins/ECE, and pure model/market metric helpers.

### Phase 2: Persistence and settlement integration
- Status: complete
- Persist bet/closing odds and CLV fields; calculate CLV at settlement from historical odds snapshots.

### Phase 3: Paired performance and quality gate
- Status: complete
- Add same-fixture paired model/market reporting, Poisson baseline evaluation, and SHADOW/OBSERVATION/VALIDATED checks.

### Phase 4: Regression tests and verification
- Status: complete
- Run focused P1 tests, affected P0 regressions, migration/lint/build/diff checks, and record results.

## Constraints

- No frontend changes, provider/prompt changes, Kelly, portfolio optimization, or unrelated refactors.
- Do not relax existing quality thresholds or alter core settlement outcomes.
- Use pure model probabilities for forecast metrics and de-vig probabilities for market metrics.
- Use risk-proportionate tests only.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `.venv/Scripts/python.exe` not found from repository root | 1 | Re-run with `apps/api/.venv/Scripts/python.exe` |
| Initial P1 test fixtures omitted `provider_id` and targeted an existing Asian line | 1 | Corrected fixtures; production logic unchanged |
