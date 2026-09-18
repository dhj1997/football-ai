# Football AI v2 Round 1 Plan

## Goal

Using `docs/football-ai-v2-codex-plan.md`, complete only the first round: current-state Audit, target Architecture, and Data/Feature Plan. Do not implement application behavior, deploy, commit, or push.

## Phases

### Phase 1: Read source plan and repository context
- Status: complete
- Read the full v2 plan, project instructions, existing architecture docs, and current Git/runtime state.

### Phase 2: Current-state Audit
- Status: complete
- Map the plan's required data, feature, model, provenance, leakage, backtest, and production controls to existing implementation evidence and gaps.

### Phase 3: Architecture proposal
- Status: complete
- Produce a minimal architecture that extends the current system without a rewrite, with ownership boundaries and migration order.

### Phase 4: Data/Feature Plan
- Status: complete
- Define source contracts, point-in-time data rules, feature groups, snapshots, quality states, and first implementation slices.

### Phase 5: Round 1 deliverable
- Status: complete
- Write an audit/architecture/data-feature plan artifact, self-review it, and report findings. No code changes beyond planning artifacts.

## Constraints

- Follow the user's explicit scope: Audit + Architecture + Data/Feature Plan only.
- Preserve all existing dirty changes, including the untracked v2 source plan and previous squad/odds changes.
- No production writes, no deployment, no Git commit/push.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell wildcard path syntax for provider inventory | 1 | Switched to an explicit file list from `rg --files`; no repository change. |
| Initial planning skill path mapping was wrong | 1 | Read the installed skill from `C:\Users\monster\.agents\skills\planning-with-files-zh\SKILL.md`. |
