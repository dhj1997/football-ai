# DeepSeek Strategy Quality Audit

## Goal

Determine why the latest overnight DeepSeek simulated portfolio lost, whether
the current strategy-quality analysis already identified the failure, and
whether the production prompt is professional, explicit, and decision-safe.

## Phases

### Phase 1: Production window and data inventory
- **Status:** complete

### Phase 2: Reconstruct predictions, bets, and settlements
- **Status:** complete

### Phase 3: Audit prompt and output contract
- **Status:** complete

### Phase 4: Findings and prioritized recommendations
- **Status:** complete

## Constraints

- Read-only diagnosis: do not change production data, code, model settings, or jobs.
- Use production MySQL evidence and the deployed code revision where practical.
- Distinguish model forecast quality from strategy eligibility, sizing, execution,
  and settlement behavior.
- Treat 2026-09-20 18:00 through 2026-09-21 06:00 Asia/Shanghai as the initial
  overnight window, then cross-check fixture and settlement dates.
- Preserve all unrelated worktree changes and `.planning/.active_plan`.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Public `/api/bets` row-detail read exceeded the default 4-second proxy timeout | 1 | Do not repeat the same public request; query the internal FastAPI listener read-only through Workbench |
