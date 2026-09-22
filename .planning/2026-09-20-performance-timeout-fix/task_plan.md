# Performance Timeout Fix

## Goal

Remove the production model-review timeout without changing performance data or
model semantics, then push and deploy the verified fix.

## Phases

### Phase 1: Design and contracts
- **Status:** complete

### Phase 2: Backend query fixes
- **Status:** complete

### Phase 3: Frontend request fix
- **Status:** complete

### Phase 4: Focused verification
- **Status:** complete

### Phase 5: Git and production delivery
- **Status:** complete

### Phase 6: Recurrence recovery and root-cause confirmation
- **Status:** complete

### Phase 7: Complete the batch-read contract and timeout guard
- **Status:** complete

### Phase 8: Focused regression verification
- **Status:** complete

### Phase 9: GitHub delivery, deployment, and browser QA
- **Status:** complete

## Decisions

- Batch existing bet reads instead of adding a cache or schema.
- Reuse the latest persisted P6 evaluation on ordinary GET requests.
- Fetch the all-model decision audit once and filter selected rows client-side.
- Keep the four-second default; use 30 seconds only for heavyweight report reads.
- Treat the decision audit as a report read, while retaining the four-second
  default for ordinary API traffic.
- Once the batch lookup has established that a prediction has no bet, derive
  its execution view from the frozen decision without another repository read.
- Preserve all unrelated worktree changes and untracked planning data.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell could not resolve `head` in the deployment output pipe | 1 | Run the capped pipeline inside Git Bash; deployment script did not start |
| Production recurrence saturated API/MySQL during concurrent diagnosis | 1 | User restarted ECS; stop load testing and use focused query-count regression coverage |
| Planning session catchup failed to print a prior Unicode check mark under Windows GBK | 1 | Existing scoped plan, findings, progress, handoff, and Git diff already restored the required context; continue without retrying the incompatible output path |
| In-app browser tab object did not expose `getState()` | 1 | Reacquire the existing tab through the documented `cua.getTab` entry point to obtain a fresh UI snapshot |
| Completion checker inspected the unrelated root plan because it does not read `PLAN_ID` | 1 | Pass this scoped plan explicitly with `-PlanFile` and keep the phase format compatible with the checker |
