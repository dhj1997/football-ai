# Dongqiudi Player Values

## Goal

Activate Dongqiudi player market values through the existing MySQL-backed
evidence path, preserve cutoff safety, then push and deploy the verified change.

## Phases

1. **Contracts and data flow** - complete
   - Trace identities, provider calls, repository shape, automation, status API,
     prediction cutoff, and web copy.
2. **Backend implementation** - complete
   - Add parsing/provider, merged MySQL history, cutoff-safe selection, and
     bounded sync telemetry.
3. **API and web integration** - complete
   - Wire runtime provider/job/status and update existing source copy.
4. **Focused verification** - complete
   - Run directly relevant API tests, compile check, web lint/type/build as
     required by changed contracts.
5. **Git delivery** - complete
   - Review diff, commit only intended files, and push `main`.
6. **Production delivery** - complete
   - Back up MySQL/app, deploy tracked HEAD, run bounded sync, and verify SHA,
     services, routes, MySQL samples, Chinese names, provenance, and cutoff.

## Decisions

- Use the public Dongqiudi JSON endpoint, not HTML parsing.
- Keep values as contextual evidence; do not add a prediction coefficient.
- Store merged history in the existing MySQL `player_value_snapshots` payload.
- Never select a record newer than the effective prediction cutoff.
- Preserve unrelated worktree changes.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| `apply_patch` rejected delete+add for the same path | 1 | Replace the file with separate delete and add patches |
| `npm exec eslint` produced no output for 90 seconds | 1 | Stop it and invoke the checked-in local ESLint binary directly |
| Automation test patch landed inside the preceding test | 1 | Restore the preceding assertions and move the new test below it |
| Quality-config search included nonexistent paths | 1 | Treat as a read-only probe issue and use explicit existing paths |
| GitHub push connection reset on port 443 | 1 | Retry with Git HTTP/1.1, then use the known proxy without changing origin if needed |
| Proxy push hung and Git DNS override inherited unsupported OpenSSL backend | 2 | Stop the hung proxy push; use a reachable official GitHub IP with command-scoped `schannel` and curl DNS override |
| Production backup script failed on CRLF `pipefail` line | 1 | Execute an LF-normalized temporary copy without modifying the deployed script |
| Workbench parsed nested trap quoting as its own `-f` flag | 2 | Remove nested single-quote escaping and use a simple remote command |
