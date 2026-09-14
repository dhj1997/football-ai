# Task Plan: Four Betting Quality Optimizations

## Goal

Implement and verify the four requested controls: live ensemble learning, point-in-time LLM probability shrinkage, a 30-settlement confirmatory research run, and a 0.5-2% short-term stake discipline.

## Scope Guardrails

- Preserve frozen prediction payload probabilities; shrink only portfolio candidate scoring inputs.
- Use the odds snapshot bound to each prediction; missing or stale market data must fail closed for shrinkage, not invent a prior.
- Keep ensemble promotion behind existing sample and improvement gates.
- Keep confirmatory research read-only and explicitly label sample insufficiency.
- Centralize live simulated stake limits; do not weaken bankroll exposure gates.
- Preserve existing Chinese player-name normalization paths.

## Phases

### Phase 1: Discovery and design
- [x] Map current ensemble, portfolio, research, settlement, and stake contracts
- [x] Confirm success criteria and choose the minimum compatible design
- **Status:** complete

### Phase 2: Implementation
- [x] Wire learned ensemble artifact into runtime model selection
- [x] Add LLM-to-market shrinkage and explainability metadata
- [x] Add confirmatory LLM-vs-Poisson research comparison at 30 settled samples
- [x] Enforce the short-term 0.5-2% stake policy
- **Status:** complete

### Phase 3: Tests and verification
- [x] Add focused tests for success and failure gates
- [x] Run available API checks and static validation
- [ ] Verify remote/local git state after delivery
- **Status:** in_progress

## Decisions Made

| Decision | Rationale |
|---|---|
| Default live stake is 1%, hard maximum is 2% | Matches the requested short-term discipline while retaining a configurable safe range |

## Errors Encountered

| Error | Resolution |
|---|---|
| pytest is not installed in the current Python runtime | Use available compile/static checks until a project test runtime is identified |
