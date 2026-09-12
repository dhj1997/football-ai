# Deployment Findings

## Local

- Runtime requirements are Node.js 22+, pnpm, and Python 3.12+.
- The web app supports production `next build` / `next start`; server-side routes use `API_BASE_URL` and `ADMIN_API_KEY` to call FastAPI.
- FastAPI supports loopback binding and SQLite. Its automation runner must remain alive persistently.
- The API currently allows CORS only from localhost, but same-origin web proxying means no API port needs to be public.
- The working tree has extensive intentional uncommitted and untracked application work. A plain remote `git clone` would omit the current product state.
- Root `.env` is ignored and contains the runtime provider keys/configuration needed for equivalent behavior. It must be transferred without logging values.
- The local `.env` has all three provider keys configured and points at the target server's MySQL instance. Its admin key was still the documented development default and will be overridden remotely.
- Copying that MySQL URL verbatim causes the same server to connect through its public address. The API import probe did not complete in 30 seconds; production should use loopback while preserving the existing credentials/database.
- A local Ed25519 key exists at `C:\Users\monster\.ssh\codex_transfer_1007_20260803_ed25519`; no SSH config aliases are defined.

## Remote

- Target IP: `47.99.207.112`.
- Root SSH authentication succeeds with the existing dedicated Ed25519 key and the stored host key matches.
- OS is Ubuntu 22.04.5 LTS x86_64. Root filesystem has about 24 GiB free; memory has about 1.9 GiB available plus 2 GiB swap.
- Node.js `v22.23.2`, Nginx `1.18.0`, MySQL, systemd, and root PM2 are installed. Docker is absent.
- Only Python `3.10.12` was found in PATH; the project declares Python 3.12+ and uses APIs unavailable in 3.10, so a 3.12 runtime is required.
- UFW is inactive. Cloud security-group rules remain unknown and must be verified from an external request after binding the public port.
- Existing listeners include public ports 22, 80, 3000, 3001, 3306, 8080, 8021, and 8765, plus several loopback services. These existing services must not be changed.
- Nginx is already enabled and can host an additional isolated port configuration.
- Existing Nginx sites proxy ports 80, 3001, and 8765 to unrelated loopback applications.
- `npm 10.9.8` is present; pnpm and Corepack are not in PATH.
- pnpm `10.33.2` was installed under the server's custom Node prefix. The service account requires that absolute binary path or an explicit PATH entry.
- Ubuntu 22.04's configured APT repositories do not offer Python 3.12. Official uv documentation supports installing an isolated managed Python 3.12 without replacing system Python.
- Official uv `0.12.10` is now installed at `/usr/local/bin`; uv-managed CPython 3.12 is installed under the service account's home.
- The project virtual environment was created successfully with CPython `3.12.14`.
- Port 9000 was free locally and a temporary listener started, but the external connection timed out. The cloud security group blocks arbitrary custom ports.
- Dynamic DNS hostnames resolve to the server and Nginx routes them correctly on-server, but Alibaba Cloud injects a `403 Non-compliance ICP Filing` response for unfiled Host names on port 80. Host-based routing is not publicly usable.
- ECS metadata returns 404 for RAM-role credentials and no Alibaba Cloud CLI credentials exist locally. The instance cannot modify its own security group.
- Nginx now listens publicly on `0.0.0.0:9000` and `[::]:9000`. On-server requests to `/` and `/matches/sportsdb-2506199` return 200.
- Both application services and Nginx are active; the application services are enabled for reboot persistence.
- External port 9000 still times out, confirming the remaining block is solely the Alibaba Cloud security group. The original IP:80 site remains HTTP 200 with its original response size.
- The generic Next `/api/backend/health` path initially returned 500 because Nginx injected `Connection: upgrade` and Next forwarded that invalid hop-by-hop header to its backend fetch. Direct Next access returned 200. The production Nginx config should clear `Connection` instead of forcing WebSocket upgrade.
- After the Nginx header fix, root, match, standings, performance, generic API proxy, and admin proxy routes all return 200 internally through port 9000.
- A controlled web-service restart makes Next.js exit with status 130 after SIGINT. The systemd unit should classify 130 as a successful intentional exit to prevent false failure records.
- With `SuccessExitStatus=130`, a second controlled web restart is recorded as `Deactivated successfully`; the unit result is `success`, active/running, with zero automatic restarts.
- Public-admin audit found that Next server routes could otherwise inject the hidden admin key into public requests. The public Nginx site now blocks `/admin` and `/api/admin/*` with 404; FastAPI admin routes remain loopback-only and key-protected.

## Verification

- SSH port 22 is reachable and authenticated remote inspection succeeded.
- External port tests confirm 80/3000/3001/8080/8765 are allowed and occupied; 8888/9000 are blocked. A dedicated port therefore requires one Alibaba Cloud security-group ingress rule.
- Deployment archive exclusion scan passed: no `.env`, Git metadata, dependency trees, build cache, planning state, database files, or runtime artifacts were included.
- Local web ESLint passed immediately before transfer.
- Remote application `.env` is owned by `football-ai:football-ai`, mode `0600`; the upload copy was removed.
- Appending a rotated admin key left the old weak assignment in the file. Even though last-value parsing should win, the old assignment must be removed for an unambiguous production secret contract.
- Remote `.env` normalization succeeded: exactly one non-default admin key remains and the DB endpoint is loopback-only.
- FastAPI import plus repository/MySQL initialization succeeds as the unprivileged service account.
- Remote pnpm install completed with 341 packages. No install failure occurred; pnpm reported one intentionally ignored optional dependency build script.
- Remote Next.js production build completed successfully with 13 generated application/API routes.
- Both project systemd units parse successfully. `systemd-analyze verify` emitted only pre-existing warnings from unrelated snapd/cloudmonitor units.
- The complete Nginx configuration, including the new exact-host site, passes `nginx -t`.
- Python dependencies resolve successfully but the package downloads from the public index are slow. The uv process remains connected and its cache grew from 15 MiB to 18 MiB during observation.
- Switching the remaining Python package downloads to Alibaba Cloud's same-region PyPI mirror completed the full 27-package install in about five seconds, reusing prior uv cache.
- Controlled API and web restarts both recovered to HTTP 200, confirming the processes are independent of the SSH session.
- Final server-side proxy checks: public entry, generic API proxy, and admin proxy all return 200 through Nginx port 9000.
- Remaining external condition: add Alibaba Cloud security-group inbound allow rule for IPv4 TCP `9000/9000`. UFW requires no change.
- After the security-group rule was added, direct external requests to port 9000 returned 200 for the public entry, target match route, and generic API proxy. The original port-80 app remains 200.
- Final external regression: `/`, `/matches/sportsdb-2506199`, `/standings`, `/performance`, and `/api/backend/health` each return 200 from outside the server. `/admin` and `/api/admin/jobs` return 404 as the public-admin guard requires.
- Final service state: API, Web, and Nginx are enabled and active; both application units report `Result=success` and `NRestarts=0`; Nginx listens on IPv4 and IPv6 port 9000.
- Final PowerShell public request returns HTTP 200. `git diff --check` for the deployment records passes.

## 2026-09-07 Redeploy Diagnosis

- The production unit is active and uses `/opt/football-ai/app/.env`; the server clock is `2026-09-07` China time.
- Production has `AUTOMATION_ENABLED=true` but `AUTOMATION_ANALYSIS_ENABLED=false`. The analysis job has no run since 2026-08-28, so overnight fixtures received evidence/lineup/settlement work but no model predictions.
- The current `today` cache contains three fixtures with kickoff times on 2026-09-07 China time at 00:30/00:30/03:00 and no prediction. They are already past kickoff when checked at 10:18; the no-retroactive-prediction rule means they must not be backfilled.
- The scheduler's analysis path correctly limits automatic prediction to future `scheduled` fixtures inside `PREDICTION_LEAD_HOURS`; enabling analysis will affect future eligible fixtures only.
- Repeated `historical_accumulation` job failures report `KeyError: 'canonical_fixture_id'`; this is a separate existing historical-data issue and is not the cause of the missing overnight model predictions.
