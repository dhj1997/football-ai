# Tomorrow Fixture Duplicate Repair

## Goal

Ensure the tomorrow fixture view contains one canonical entry per real match without hiding genuinely distinct matches.

## Phases

### Phase 1: Reproduce and locate the duplicate

- Status: complete
- Inspect the live tomorrow view, fixture API response, and persisted fixture identities.
- Determine whether duplication originates in storage, API assembly, or rendering.

### Phase 2: Implement the minimal fix

- Status: complete
- Correct the narrowest responsible boundary.
- Preserve evidence and provider identity behavior.

### Phase 3: Verify the contract

- Status: complete
- Add or update one focused regression test for the duplicate path.
- Run directly related tests and verify the live tomorrow view.

### Phase 4: Follow-up audit of Dongqiudi analysis availability

- Status: complete
- Confirm whether current tomorrow fixtures have Dongqiudi identities and analysis payloads.
- Verify the detail API/UI display path and report any separate synchronization gap.

### Phase 5: Cache-first startup and page loading

- Status: complete
- Measure the cold-start and repeat-open latency on the current remote-MySQL setup.
- Add a small in-process fixture cache and delayed background refresh so cached today/tomorrow data is served first.
- Add a browser-side last-success cache for the public fixture list, then verify stale-while-revalidate behavior and API contracts.

## Constraints

- Preserve all existing user changes.
- Do not deduplicate genuinely different fixtures.
- Keep tests proportional to the defect.
- Preserve the Chinese player-name display boundary.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `agent-browser` executable is unavailable | 1 | Use the installed Codex in-app browser control plugin for local UI inspection. |
| Two PowerShell probes piped directly after `foreach`, causing parser errors | 1 | Assign loop results to a variable before piping. |
| Direct tomorrow API request timed out after 20 seconds | 1 | Read the persistent cache directly and inspect refresh locking before retrying the live route. |
| Inline Python probe placed `async def` after semicolons | 1 | No network request was sent; retry with `asyncio.run(...)` around a coroutine expression. |
| SQL probe had invalid PowerShell/Python quote nesting | 1 | No database query ran; use a PowerShell single-quoted Python command containing Python double-quoted SQL. |
| Final browser wait exceeded the browser kernel deadline | 1 | API and test verification completed independently; browser snapshot was not used as a pass criterion. |
| Restart probe used PowerShell's read-only `$PID` variable name | 1 | No process was stopped; retry with `$ownerIds`. |
| Inline `asyncio.gather` probe passed a Future directly to `asyncio.run` | 1 | No network request was sent; retry each analysis request as a direct coroutine. |
