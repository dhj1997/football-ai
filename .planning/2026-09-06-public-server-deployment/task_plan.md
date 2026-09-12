# Public Server Deployment Plan

## Goal

Deploy the current Football AI application to `47.99.207.112`, expose a public HTTP endpoint, keep the API and web processes running after logout/reboot, and verify the endpoint from outside the server.

## Constraints

- Preserve all existing local and remote user data and unrelated changes.
- Do not expose application secrets, the FastAPI admin API, or database files directly.
- Use the smallest deployment mechanism compatible with the server's existing OS and software.
- Keep command output bounded and record failures before trying a different approach.

## Phases

### Phase 1: Local deployment audit
- Status: complete
- Inspect runtime configuration, build contracts, secret handling, and repository state.

### Phase 2: SSH and remote host audit
- Status: complete
- Confirm authenticated SSH access, OS, architecture, available runtimes, firewall, and occupied ports.

### Phase 3: Install and configure application
- Status: complete
- Transfer the current working tree without secrets/artifacts, install production dependencies, configure environment, and build.

### Phase 4: Process supervision and public routing
- Status: complete
- Configure persistent API/web services and expose one public web port while keeping the API private.

### Phase 5: Verification and handoff
- Status: complete
- Verify service health locally and publicly, validate restart behavior, and document URL, paths, controls, and any remaining infrastructure action.
- Server-side, restart, security-group, external route, and public-admin-surface verification are complete.

### Phase 6: Redeploy and automatic-analysis recovery
- Status: complete
- Diagnose why the server did not create overnight predictions.
- Back up the current remote application, transfer the current working tree without local secrets/databases, and restart the supervised services.
- Enable automatic model analysis on the server, run a controlled fixture refresh and analysis pass, and verify future eligible fixtures receive predictions while finished fixtures remain protected.

## Decisions

- Public entry should be the Next.js web application; it will proxy API traffic to a loopback-only FastAPI service.
- Deploy the current working tree, including intentional uncommitted/untracked application changes, rather than deploying only Git `HEAD`.
- Transfer `.env` separately over SSH and protect it with mode `0600`; never place it in the public web bundle.
- Keep existing services and occupied ports untouched. Internal listeners are FastAPI `127.0.0.1:8000` and Next.js `127.0.0.1:3200`.
- Use systemd for both application processes because it is already enabled and provides reboot persistence and bounded logs.
- Expose Nginx on dedicated TCP port 9000 and keep existing port-80/default traffic untouched. Alibaba Cloud security-group ingress for TCP 9000 must be added by an account with cloud permissions.
- Use the server-local MySQL endpoint (`127.0.0.1:3306`) while preserving the existing database name and credentials.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Remote user-list `awk` expression was mangled by PowerShell quoting | 1 | The user list is nonessential; use a simpler `getent`/`cut` command only if account inspection remains necessary. |
| Remote free-port loop was mangled by nested PowerShell/SSH variable expansion | 1 | Do not repeat nested interpolated loops; test candidate ports with direct `ss` filters. |
| Temporary listener on port 9000 was unreachable externally | 1 | Alibaba Cloud security-group rules block the custom port; reuse allowed port 80 with an isolated Host-based Nginx virtual host. |
| Service-account `uv python install` tried to read `/root/uv.toml` | 1 | Run uv from `/opt/football-ai` with `HOME` set to the service home and `--no-config`. |
| Service-account dependency install could not find `pnpm` | 1 | npm installed pnpm under the custom Node prefix; use its absolute path and set that prefix explicitly in the web systemd unit. |
| Secret audit still found the development admin-key line | 1 | The rotated key was appended, so remove every prior `ADMIN_API_KEY` assignment and write only the generated production value. |
| API import/database smoke check did not finish within 30 seconds | 1 | The copied database URL loops back through the server's public address; change only its host to `127.0.0.1` and rerun after terminating the probe. |
| Initial FastAPI health probe requested `/api/health` and received 404 | 1 | Source contract is `/health`; use the correct path for service verification. |
| First public hostname probes returned 403 while direct IP remained 200 | 1 | Distinguish Nginx routing from the local system proxy by testing Host routing on-server and an external `curl --noproxy --resolve` request. |
| Dynamic DNS host routing is blocked by Alibaba Cloud ICP enforcement | 1 | Error page explicitly reports non-compliant ICP filing. Abandon hostname routing and use direct IP with dedicated port 9000. |
| RAM-role metadata was initially classified as present because any nonempty response was accepted | 1 | Response was a 404 HTML document, not a role name. Correct finding: no RAM role or CLI credentials are available to edit the security group. |
| Server-side generic Next API proxy check returned 500 | 1 | Nginx injected `Connection: upgrade` into every request and Next forwarded it; clear the hop-by-hop header because production has no HMR WebSocket requirement. |
| Public Next admin proxy exposed server-held admin credentials | 1 | Add Nginx 404 guards for `/admin` and `/api/admin/*`; keep administrative operations available only through loopback/SSH until an explicit user-authenticated admin boundary is added. |
