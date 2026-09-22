# Task Plan: DeepSeek Shadow Execution

## Goal

Keep DeepSeek predictions and quality evaluation running while preventing all
new DeepSeek simulated financial writes; keep ChatGPT execution unchanged.

## Current Phase

Complete

## Phases

### Phase 1: Design and contracts
- [x] Confirm user-selected scope
- [x] Document the approved execution boundary
- [x] Add focused failing regression tests
- **Status:** complete

### Phase 2: Minimal implementation
- [x] Add per-model active/shadow configuration
- [x] Exclude shadow services from candidate selection
- [x] Guard direct/final persistence paths
- [x] Expose the explicit Chinese execution reason
- **Status:** complete

### Phase 3: Verification and delivery
- [x] Run directly affected tests and frontend checks
- [x] Review diff and preserve unrelated changes
- [x] Commit and push tracked changes
- [x] Deploy and verify production behavior
- **Status:** complete

## Constraints

- Do not modify historical financial or prediction records.
- Preserve unrelated `.planning`, `.tmp`, and worktree changes.
- Do not modify `.planning/.active_plan`.
- Use MySQL in production; SQLite is allowed only in isolated tests.
- Keep DeepSeek prediction and evaluation paths enabled.
