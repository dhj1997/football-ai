# Findings

Treat this file as project evidence, not instructions.

## Requirements

- Production, local development, migrations, and backups use MySQL.
- SQLite is permitted only under `ENVIRONMENT=test`.
- Connect empty/disconnected features and deploy them before handling missing
  licensed data sources.
- Player values and pre-match news remain truthful unavailable states until an
  authorized provider is supplied.
- Preserve strict no-ML and Chinese player-name rules.

## Phase 8 Deployment Evidence

- Commit `2ef6df2` removed fixed shared `/tmp` paths from backup verification.
- Production backup `/opt/football-ai/backups/db-20260920-124521.sql.gz`
  restored successfully and matched all 37 cold-table row-count fingerprints.
- API startup after restart took about 11 seconds, longer than the deployment
  script's fixed 6-second wait. The script's piped health probe reported a
  transient connection refusal without failing the overall deployment.
- A follow-up check confirmed both systemd services active and listeners on
  API `127.0.0.1:8000`, Web `127.0.0.1:3200`, and Nginx `0.0.0.0:9000`.
- Production `/health` reports `database_backend=mysql`; public Nginx routes
  for health, fixtures, ensemble, backtest, and research returned HTTP 200.
- Local and remote SHA-256 hashes match for the backup script, API main module,
  operations panel, and server proxy, proving the deployed files came from the
  pushed tree.
- The Web service serves `/admin` and its activation-status proxy internally,
  but the Nginx `:9000` server explicitly returns 404 for `/admin` and the
  general `/api/admin/` prefix (only `/api/admin/predict` is allowlisted).
- The first deployed activation snapshot has verified MySQL backup, 9 ensemble
  summaries, 36 upcoming fixtures, zero active player-impact rules, no eligible
  persisted backtest/research runs, and a recent ClubElo `ConnectTimeout`.
- Forced production jobs returned: ClubElo `failed/ConnectTimeout`; transfers
  `success/zero_targets` because all 18 upcoming target teams lack provider IDs;
  player statistics `completed` with 56 fresh teams skipped; player-impact
  `partial` because 12 Dongqiudi fixture contexts contain a list where the
  enrichment path expects a mapping (`'list' object has no attribute 'get'`).
- The same malformed evidence makes the live fixture-detail route for an
  affected fixture return HTTP 500, so the compatibility fix must cover the
  shared player-impact read path rather than only the automation wrapper.
- MySQL inspection showed the container shapes are valid mappings; the actual
  legacy shape is each Dongqiudi squad player's `statistics`, stored as a list
  such as `[{"出场":"9"},{"进球":"5"},{"助攻":"0"}]`. `_team_impact`
  assumes a statistics mapping and calls `.get`, causing the exception.
- GitHub's Git Data API preserves the original `+0800` commit offset internally
  but its commit endpoint omits the conventional trailing message newline. This
  explains the API-created SHA difference and allows the exact API commit
  objects to be reconstructed locally before moving the branch reference.
- The second deployment restore completed but the fail-closed fingerprint gate
  caught three one-row drifts (`market_snapshots`, `prediction_revisions`, and
  `predictions`) caused by API automation writes during dump/restore. The
  archive was not extracted. Expanding a hot-table allowlist would weaken the
  gate; quiescing the sole API writer around the backup is the reliable fix.
- After quiescing the API writer, backup `db-20260920-131536.sql.gz` restored
  with exact fingerprints for all 41 tables. The API was restarted by the
  cleanup trap, then deployed HEAD `1eb2817` passed the readiness loop and Web
  returned HTTP 200.
- The formerly broken fixture `dongqiudi-54419032` now returns HTTP 200. The
  production player-impact job completes all 32 candidates with zero exceptions
  but reports all 32 as insufficient evidence, so code connectivity is fixed
  while rule coverage remains a truthful source-data gap.
- Production evaluation execution is truthful: ensemble learning registered a
  draft with 21 test samples and negative Brier improvement, so it was not
  promoted; Football-Data confirmatory research has 0/30 source-qualified
  samples; P12 has 103 rows and a passing leakage audit but zero chronological
  windows, so no run was persisted; manual research similarly skipped archive.
- The strict Round 6 evaluation is eligible: 11 fixtures, 230 evaluated
  observations, and status `ok`. It can be explicitly persisted as the real
  gate-passing backtest record instead of manufacturing a P12 success.
- Transfer activation still had a code-side gap: current fixtures lack embedded
  API-Football team IDs, but MySQL contains 56 resolved API-Football team
  identities and 12 of the 18 upcoming team appearances can be resolved from
  them. The transfer job and evidence attachment now share a conflict-free
  league/name identity fallback; genuinely unmapped promoted teams stay missing.
- ClubElo DNS resolves to `37.128.134.74`, but both the workstation and server
  time out connecting to `api.clubelo.com`; MySQL has no last-good ClubElo
  snapshot. This is an upstream connectivity/source gap, not an application-only
  error.
- Transfer identity fallback resolved 13/18 upcoming team appearances. Ten
  distinct teams were persisted in MySQL with 8,077 transfer records across the
  first two bounded runs; the next three mapped teams hit API-Football HTTP 429.
  Five current promoted/new-season teams remain absent from the stored identity
  map. Attached Manchester City evidence contained 5 recent arrivals and 20
  departures; unknown player aliases remained the Chinese `待核验球员` label.

## Licensed/External Source Handoff

- Player value still requires an explicitly redisplay-authorized provider that
  covers EPL, La Liga, and CSL. Required record fields are stable provider and
  canonical player identity, numeric EUR market value, provider/source name,
  and ISO source `as_of` time; operational details must include authentication,
  competition coverage, rate limits, historical access, and production terms.
- Pre-match news has no authorized producer. A suitable source must provide a
  stable article/event ID and source, fixture/team/player identity linkage,
  original publication and capture/availability timestamps, language/content
  or licensed summary, URL/provenance, corrections/deletions, competition
  coverage, authentication, limits, history, and redistribution rights.
- Player-impact rule coverage needs timestamped absence/injury records linked
  to canonical players and fixtures. The present public/Dongqiudi evidence has
  empty availability for all 32 evaluated candidates; statistics alone cannot
  truthfully create absence rules.
- Immediate Football-Data confirmatory research needs at least 30 paired,
  pre-kickoff frozen model predictions whose fixture provenance is
  Football-Data. Current qualified count is zero; this can accumulate over time
  or be supplied as licensed cutoff-safe history, but cannot be backfilled with
  fabricated prediction timestamps.
- ClubElo needs a reachable licensed/free ratings endpoint with team identity,
  numeric Elo, validity dates, and redistribution permission, or restored
  connectivity to `api.clubelo.com`. API-Football transfer completion needs a
  refreshed current-season identity map plus quota for the three rate-limited
  teams and the five missing promoted/new-season teams.

## Final Production Evidence

- GitHub/local `main` is `3a1a6418e311a82c7c64a0bb2207beddbb55944b`.
- Both systemd services are active; production readiness is `ready`, smoke is
  `pass`, database backend is MySQL, and there are no configuration violations.
- Backup `db-20260920-133210.sql.gz` has SHA-256
  `af5b4b9aeed78cbd76983ae907022b62ee68f64dab22018d7f6245ec0bae372a`
  and a verified 41-table restore marker.
- Public `:9000` returned 200 for root, health, fixtures, ensemble, backtest
  runs, and research runs. An unknown proxied backend route returned 404 rather
  than demo data. Intentional Nginx protection still blocks public admin paths.
- Local and server hashes match for both deploy scripts, API main,
  player-impact, transfer sync, operations panel, and server proxy.
- Final MySQL business counts: 1 eligible non-simulated Round 6 backtest, 10
  transfer snapshots, 0 research archives, 0 player-impact rules, and 0 player
  value snapshots. The zeroes are source/gate outcomes, not disconnected code.

## Baseline

- Branch `main`; specification commit `07b8004`; local branch was one commit
  ahead of `origin/main` when implementation started.
- Only unrelated untracked `.tmp/` existed outside the committed specification.
- Current configured MySQL held real fixtures, odds, evidence, features,
  predictions, and simulated bets during the pre-spec audit.
- Empty/disconnected areas: player-value snapshots, player-impact rules,
  research runs, backtest runs, global ensemble summary, news producer,
  ClubElo snapshot, transfer targets, champion registry state, and silent web
  mock fallback.
- Existing production layout: `/opt/football-ai/app`, API `:8000`, Web `:3200`,
  Nginx/public `:9000`, systemd services, shared MySQL `.env`.

## Existing Components to Reuse

- `apps/api/app/config.py`, `database.py`, `production.py`
- `deploy/backup-verify.sh`
- `player_impact.py`, `player_stats.py`, lineup/availability evidence paths
- `clubeelo_provider.py`, `transfers_sync.py`
- `backtest_engine.py`, `research_engine.py`, existing run repositories/routes
- `/api/ensemble/{fixture_id}` and `dual_prediction_service.py`
- `apps/web/src/app/admin/page.tsx`
- `apps/web/src/app/api/backend/[...path]/route.ts`

## Phase 1 Code Map

- `apps/api/app/main.py` calls `get_settings()`, constructs
  `PredictionRepository`, and immediately calls `initialize()` during module
  import. The non-test MySQL guard must run between settings load and repository
  construction to prevent schema work.
- `EnvironmentContract.validate()` currently validates an explicit database URL
  only for production and does not reject SQLite for local or staging.
- Repository-level SQLite construction is used throughout focused tests, so the
  guard belongs to application runtime configuration rather than
  `PredictionRepository` itself.
- The first planning catch-up run failed under GBK; the UTF-8 rerun found only
  unrelated historical session output and no current code to recover.
- `player_impact.py` already computes deterministic per-player contribution,
  availability, replacement, and absence impact inside evidence context, but it
  does not persist `player_impact_rules`.
- `FeatureEngine._player_impact()` already reads cutoff-safe rules and reports
  `player_impact_rule_or_evidence_unavailable` when none exist. The activation
  gap is a producer and bounded triggers, not another feature calculation.
- The repository requires each rule to provide ID, player, role, impact type,
  numeric impact/confidence, source, `available_at`, rule version, status, and
  creation time. Identical IDs are idempotent; content conflicts fail closed.
- The v2 feature reads rules only for players explicitly marked absent or
  unavailable in availability/lineup evidence. Rule generation should therefore
  persist absence impact from the already enriched context, not every squad
  member's generic contribution.
- Prediction context enrichment already localizes player names, enriches player
  statistics, then calls `apply_player_impact()`. The smallest reliable rule
  producer can run immediately after this calculation and after lineup refresh,
  reusing stored fixture evidence rather than inventing another job pipeline.
- Automation currently saves refreshed lineup evidence but does not rerun or
  persist impact rules. Player-stat backfill stores statistics independently;
  rules should be regenerated against upcoming fixture evidence after either
  input changes.
- ClubElo uses one 30-second `httpx` timeout with no retry and returns an
  `empty` result without overwriting the prior snapshot. Existing storage is
  already last-good by omission; activation needs bounded fetch behavior and
  observable failure/staleness, not a new table.
- Transfer sync scans all fixtures rather than upcoming supported fixtures,
  does not distinguish zero targets or missing provider IDs, and bounds only
  successful fetches. A run with repeated failures can therefore exceed the
  intended request budget. Target derivation and result states are the repair
  points.
- The P12 admin backtest route already avoids persistence when the engine has no
  manifest, but it will persist any manifested status. The explicit Round 6
  persistence path currently builds/saves a run without a route-level
  eligibility check.
- `research_engine.run_research()` owns persistence internally. Its comparison
  code can return `insufficient_sample`, so the persistence decision must be
  gated inside the engine or immediately before its repository call rather than
  only in the API wrapper.
- Research currently assigns `partial` for insufficient experiment windows or
  a confirmatory LLM-vs-Poisson sample below 30, then still archives the run.
  The minimal contract change is to return the fully computed partial result
  without `archive=ok` or a repository write; only `completed` with zero
  leakage violations is persisted.
- The P12 backtest engine creates a manifest even when no valid chronological
  windows exist. Persistence must require `status=ok`, positive window/sample
  counts, and an explicit passing leakage audit over its evaluation rows.
- Round 6 reports already expose `status=ok|insufficient_data`; its persist route
  can reject non-`ok` reports before building/saving an immutable run.
- A real global ensemble summary can reuse one bounded scheduled-fixture scan
  and `current_predictions_for_fixture()` plus the same helper used by the
  existing single-fixture endpoint. No new persistence path is needed.
- `/admin` currently renders the same large `FixtureWorkspace` in operator mode;
  that workspace already uses the local UI primitives and Lucide icons. The
  activation panel should be a focused component within this established admin
  experience, not a parallel dashboard framework.
- The web tree has no dedicated test suite files in the surfaced admin paths;
  validation will rely on focused pure helper tests where available plus
  TypeScript/build and browser verification for the actual page.
- `FixtureWorkspace` already appends `OperationsPanel` and `ModelConfigPanel`
  when `operatorMode` is true. Extending `OperationsPanel` with activation
  readiness and the missing bounded jobs is the smallest consistent UI change;
  `/admin/page.tsx` need not be replaced.
- Existing job controls already implement pending/success/error state and
  duplicate-click prevention, so the new status/actions should reuse that
  interaction model and established `SectionHeader`/`StatusBadge` primitives.
- `/api/production/readiness` already aggregates contract, migrations, and smoke
  checks, while `/api/admin/provider-health` and `/api/admin/jobs` expose most
  operational telemetry. One additive activation-status endpoint can compose
  counts/readiness without duplicating those stores.
- `/api/admin/production/backup` is SQLite-only and therefore misleading under
  the approved policy. The MySQL deployment script should write a non-secret
  verification marker after restore/fingerprint success; the API/UI can read
  that marker rather than allowing the web process to launch privileged dump or
  restore commands.
- Automation already registers ClubElo, transfers, player statistics, and
  confirmatory research jobs conditionally. Player-impact generation can be an
  explicit bounded job; the admin UI can expose existing job names instead of
  creating per-provider Next.js routes.
- `deploy/backup-verify.sh` restores and compares cold-table row counts, but a
  `RESTORE_MISMATCH` currently does not exit non-zero and `MISSING` is never
  incremented. The script therefore cannot yet enforce its claimed gate.
- `deploy/deploy.sh` backs up application files but does not run the MySQL
  backup/restore verification before extraction. Phase 2 must make the backup
  script fail closed, emit a verification marker, and invoke it before code
  replacement.
- Existing P15 tests explicitly treat local configuration as permissive and
  create SQLite repositories directly. Repository tests can remain unchanged,
  but application-import tests must declare `ENVIRONMENT=test`, and the
  environment-contract expectations must change for local/staging SQLite.
- Eleven API test modules import `app.main` with SQLite URLs but do not declare
  the test environment. A single `tests/conftest.py` setting
  `ENVIRONMENT=test` before collection is the narrow way to preserve these
  tests while enforcing the real runtime boundary.
- Availability and lineup containers already carry `checked_at`/`updated_at`,
  while player-stat snapshots carry `synced_at`. These timestamps can define a
  rule's source availability without inventing historical times.
- `localize_evidence_players()` is the established normalization boundary and
  is already called before impact calculation. The new persistence function
  will still call `to_chinese_player_name` on every stored display name as a
  final contract check.
- `PlayerStatsService.enrich()` currently attaches statistics/source/season but
  drops the stored snapshot ID and `synced_at`. Those two provenance fields must
  be carried onto the squad row before a persistent rule can be cutoff-safe.
- Availability rows inherit their authoritative timestamp from the enclosing
  availability object; the generator must bind that timestamp and the matched
  canonical/provider player identity into the rule payload.
- Rule values follow the existing feature convention: an absence is a negative
  team contribution. Each rule binds a fixture ID so a player's old injury rule
  cannot leak into a later fixture; multiple versions for the same fixture use
  only the latest cutoff-safe rule.
- `created_at` is the real generation time and participates in `available_at`,
  so running the producer now cannot make a derived rule appear available at a
  historical cutoff. Repeated identical source content reuses the first stored
  rule by deterministic ID.
- The automation runner maps returned `errors` to durable partial status and
  uses `item_count` for the run record; insufficient source evidence remains a
  separate count rather than a false job failure.
- `data_sync_runs` is the existing provider-health source and supports
  start/finalize records. ClubElo and transfer refreshes should write this
  contract directly so both automation and manual endpoints report the same
  upstream outcome.
- Backtest leakage can reuse `research_engine.leakage_audit()` over
  `build_backtest_rows()`; it requires at least one comparable prediction and
  settlement timestamp and rejects prediction-at/after-settlement rows.
- Existing confirmatory research tests use 300 paired samples, while the
  insufficient case uses 10. Returning the latter with `run_id=None` and
  `archive=skipped` preserves the report without writing a misleading run.
- `weighted_ensemble()` already returns normalized member probabilities,
  effective weights, and readiness status. The global endpoint only needs to
  add fixture metadata, member agreement, bounded scanning, and an honest empty
  reason; it must not write predictions.
- User-facing docs still instruct local SQLite use; `PRODUCT.md` even names
  PostgreSQL as production storage. README, product/database/rollback guidance,
  and `.env.example` must be aligned to MySQL for every non-test runtime.
- The existing admin surface is `OperationsPanel`; it lists seven automation
  jobs and already supports durable manual runs, so activation controls belong
  there rather than in a second admin application.
- ClubElo, transfer, player-stat, and player-impact jobs already exist in the
  automation runner, but the panel job catalog does not expose them.
- `/api/production/readiness` checks deployment configuration, migrations, and
  smoke tests only. It does not compose backup verification, provider health,
  player-impact coverage, ensemble availability, or evaluation readiness.
- The web backend proxy and several admin proxies currently substitute demo or
  success responses when the API is unreachable; production must preserve
  backend non-2xx responses and return explicit gateway failures unless
  `WEB_DEMO_MODE=true` is set server-side.
- The automation runner already exposes exact runnable keys `clubeelo`,
  `transfers_backfill`, `player_stats_backfill`, and `player_impact_rules`.
- API and Web services use the shared root environment file in the documented
  deployment layout, so adding `WEB_DEMO_MODE` to the backend settings view lets
  production readiness fail closed on an enabled web demo fallback.
- Activation status can remain read-only and schema-free by composing existing
  `player_impact_rules`, `data_sync_runs`, `list_fixtures`,
  `current_predictions_for_fixture`, `backtest_runs`, and `research_runs`
  repository methods.
- Provider reliability already exposes per provider/competition/capability
  completion counts, failures, freshness, and error rates; the activation view
  only needs a bounded window and an explicit empty state.
- Activation status will separate deployment blockers (database/config/demo,
  migration, smoke) from operational attention states (coverage, provider
  freshness, ensemble/evaluation data). Licensed source gaps stay explicit but
  do not block deployment of the other features.

## Source Gaps

- `NullPlayerValueProvider` is intentional until a licensed player-value source
  exists.
- News has an evidence slot but no approved producer.
- Do not infer either value from unrelated public statistics.

## Issues Encountered

| Issue | Resolution |
|---|---|
| Historical planning catch-up crashed on GBK output | Re-run with UTF-8; historical context was unrelated and no code was imported |
| PowerShell rejected an `rg` Windows wildcard path for test files | Use `rg -g 'test_*.py'` against the tests directory instead of a path glob |
| Documentation scan included a nonexistent `apps/api/.env.example` | Use the existing root `.env.example` only |
| Player-impact test search repeated the invalid Windows path-glob form | Use directory search with `-g` filters; do not pass wildcard paths |
| Combined findings/test patch missed an exact context line | Patch the planning log and test file separately with verified anchors |

## Resources

- `docs/superpowers/specs/2026-09-20-mysql-production-activation-design.md`
- Project `AGENTS.md` instructions supplied by the user in this thread.
