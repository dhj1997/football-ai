# Bet Sizing Policy Adjustment

## Goal

Determine why tomorrow's dual-model predictions mostly produce no bets, then define and implement the smallest approved change to eligibility and simulated stake sizing.

## Phases

### Phase 1: Current-rule and tomorrow-data audit

- Status: completed
- Trace model recommendation, deterministic market gates, bankroll placement, and current tomorrow predictions.

### Phase 2: Policy design and approval

- Status: completed
- Compare minimal rule options and obtain user approval for exact no-bet and stake behavior.

### Phase 3: Implementation

- Status: completed
- Apply only the approved policy changes without unrelated refactoring.

### Phase 4: Focused verification

- Status: completed
- Cover stake lower bound/scaling, retained hard failure paths, and tomorrow prediction behavior.

### Phase 5: Model handicap probability authority repair

- Status: completed
- Use each model's Asian-handicap forecast as the directional EV authority while retaining only Poisson settlement shape where the prompt lacks full/half/push detail.
- Recalculate current immutable predictions at execution time and remove the model/Poisson display mismatch.

### Phase 6: Regression and live reconciliation

- Status: completed
- Cover half, integer/quarter, and fallback paths; run the full API suite and reconcile the incorrect pre-kickoff Barcelona bet.

## Constraints

- Preserve all existing dirty-worktree changes.
- Keep the simulated-betting boundary; do not connect real-money execution.
- Keep tests proportional to the policy change.
- Preserve the Chinese player-name boundary.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| System Python has no `pytest` module | 1 | Locate and use the repository's configured Python environment before rerunning tests. |
| PowerShell passed Unix wildcard path arguments literally to `rg` | 1 | Use explicit paths or repository-wide globs supported by `rg`. |
| Full API suite used an API-relative interpreter path from the repository root | 1 | Rerun with the explicit `apps/api/.venv` interpreter path. |
| `agent-browser` CLI is not installed globally | 1 | Use the skill-supported `npx agent-browser` entry point. |
| `npx agent-browser` opened and snapshotted once, then repeated session commands hung | 2 | Terminated both hanging calls and switched to the available in-app browser control skill. |
| In-app browser could not attach a controllable webview or enable visibility | 2 | Completed HTTP, live API, build, lint, and type verification; left isolated services running for user review. |
| Tests with a fixed kickoff on the current date became time-dependent after kickoff | 1 | Moved pure bankroll/settlement fixtures to 2099 and set API fixtures two hours ahead of the test clock. |
| Bankroll tests omitted odds timestamps after current-market reconstruction was enabled | 1 | Add fresh timestamps to the test odds fixture; retain the production stale-odds gate. |
| Dual-account and settlement fixtures also omitted odds timestamps | 1 | Add fresh timestamps to those execution fixtures and keep stale odds non-executable. |
| Cross-fixture league ranking reused other fixtures' persisted Poisson market tables | 1 | Rebuild every candidate market table from that fixture's saved odds before ranking. |
| Final stale-path scan used a PowerShell-sensitive combined regular expression | 1 | Replace it with separate literal `rg -e` patterns; confirmed no duplicate EV helper remains. |
