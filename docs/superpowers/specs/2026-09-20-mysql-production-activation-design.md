# MySQL Production Activation and Feature Completion

## Status

The design was approved in conversation on 2026-09-20. This document is the
written specification for final review before implementation planning begins.

## Context

The deployed application already uses MySQL and contains real fixture, odds,
evidence, feature, prediction, and simulated-bet records. The repository still
defaults to SQLite, however, and several operational paths are either empty,
silently replaced with frontend mock data, or connected to a provider without
producing usable records.

The implementation will activate the existing architecture incrementally. It
will not rewrite the platform or introduce a second data layer. Every durable
runtime write, migration, backup, restore check, and deployment verification
outside automated tests will use MySQL.

## Decisions

1. `ENVIRONMENT=test` is the only environment allowed to use SQLite. Direct
   repository-level SQLite compatibility remains available for isolated tests.
2. `local`, `staging`, and `production` application startup fail before schema
   initialization unless `DATABASE_URL` resolves to MySQL.
3. Existing tables, repositories, services, and routes remain authoritative.
   Changes add producers, readiness reporting, and operator controls instead of
   parallel replacements.
4. Player impact is deterministic and source-timestamped. It uses existing
   player statistics, lineups, and availability evidence; it does not estimate
   missing inputs with ML or LLM output.
5. Backtest and research runs are persisted only after their existing evidence,
   provenance, leakage, and minimum-sample gates pass.
6. Player market values and pre-match news remain explicitly `unavailable`
   until the user supplies authorized providers and credentials. They are the
   final activation stage and do not block the rest of this rollout.

## Goals

- Enforce MySQL as the sole non-test database and prove backup restorability
  before production deployment.
- Populate deterministic player-impact rules from existing evidence and expose
  their coverage without inventing absent source data.
- Turn existing backtest, research, ensemble, ClubElo, and transfer components
  into observable, usable workflows.
- Give operators one restrained admin surface for readiness, recent runs, and
  existing sync/run actions.
- Stop masking backend failures with mock responses unless demo mode is
  explicitly enabled.
- Deploy the completed non-blocked scope and verify public routes, service
  processes, and resulting MySQL records.

## Non-goals

- No real-money betting or external betting-platform integration.
- No learned model, fitted calibration, or LLM-generated numeric feature is
  introduced into the strict no-ML v2 production path.
- No fabricated player values, news, timestamps, provider success, backtest
  conclusions, or research conclusions.
- No broad repository refactor, schema redesign, new admin framework, or
  replacement of existing providers that already satisfy the contract.
- No activation of licensed player-value or news ingestion before a provider
  contract and credentials are supplied.

## Design

### 1. MySQL-Only Runtime Boundary

Configuration validation will normalize the database URL and reject a
non-MySQL URL whenever `ENVIRONMENT != test`. The check runs during application
composition, before `PredictionRepository.initialize()` can create or mutate a
schema. The failure names the environment and required URL scheme without
printing credentials.

Tests that start the application must set `ENVIRONMENT=test`. Tests may continue
to instantiate `PredictionRepository` with SQLite directly, including in-memory
databases, so repository contract coverage remains fast and isolated. Runtime
documentation and examples will stop presenting SQLite as a valid local or
production application database.

Migration execution continues through the existing migration ledger and MySQL
repository. Before deployment, `deploy/backup-verify.sh backup` must create a
single-transaction MySQL dump, restore it to a temporary verification database,
compare table fingerprints, and report `RESTORE_VERIFIED`. A dump that was not
restored and compared is not an acceptable backup. Credentials must be read
from the server `.env` and must not be logged.

### 2. Deterministic Player-Impact Rules

Add one idempotent rule-generation service around the existing
`player_impact_rules` repository contract. Its eligible inputs are stored player
statistics, confirmed or predicted lineups, and timestamped availability or
absence evidence that was available by the prediction cutoff.

Each generated rule records the canonical player ID, localized Chinese display
name, team and competition identity, source record IDs, source timestamps,
`available_at`, deterministic rule version, input values, output contribution,
and status. Every displayed or logged player name passes through
`to_chinese_player_name`; a new provider alias must be added when the canonical
name cannot otherwise be localized.

The service is rerunnable: identical inputs reuse the same content-addressed
rule, while a changed source snapshot creates a new version instead of mutating
historical evidence. Missing or cutoff-unsafe inputs produce an explicit
coverage reason and no numeric contribution. Feature snapshots consume only
active, cutoff-safe rules and retain an explicit missing value when no rule is
eligible.

The existing player-statistics and lineup/availability jobs trigger bounded
rule generation after successful writes. An admin action can run the same
bounded generation manually. Readiness reports total active rules, covered
players/fixtures, last source timestamp, last successful generation, and
reason counts for uncovered fixtures.

### 3. Backtest and Research Activation

The existing run engines, immutable tables, and public read routes remain in
place. Operator actions will invoke the existing admin run routes with fixed,
documented defaults rather than introduce another execution system.

Before persistence, a backtest must have a non-empty eligible evaluation set,
chronological separation, accepted provenance, and a passing leakage audit. A
research run must additionally satisfy its registered hypothesis, selection
rule, and minimum paired-sample requirement. Failed gates return a structured
`insufficient_data` or `rejected` result with counts and reasons and do not
create a success-looking row in `backtest_runs` or `research_runs`.

Successful content-identical runs reuse the existing immutable run ID. The
admin view shows readiness before enabling a run, recent persisted runs, sample
counts, source scope, timestamps, and failure reasons. It never labels an empty
or insufficient result as completed research.

### 4. Global Ensemble Summary

`GET /api/ensemble/{fixture_id}` remains the detailed single-fixture contract.
`GET /api/ensemble` will become a real summary over current eligible fixtures
instead of returning a hard-coded empty simulated response. It returns bounded,
newest-first items containing fixture identity, kickoff, competition, available
members, effective deterministic weights, weight source, probabilities,
agreement/disagreement, and readiness reasons.

The summary reuses current predictions and the existing strict no-ML read path.
Legacy learned-ensemble registry records may be displayed for audit but are not
promoted into v2 production selection. If no allowed champion exists, the API
reports the deterministic default weight source truthfully. It does not persist
or mutate frozen predictions while building the summary.

### 5. ClubElo and Transfer Repair

ClubElo remains the preferred external Elo snapshot when a valid stored rating
exists. The sync path will use bounded connect/read timeouts, limited retry with
backoff, response validation, and provider-health recording. A failed fetch
keeps the last valid snapshot, marks it stale with the upstream error category,
and never writes an empty success snapshot. If ClubElo remains unreachable in
production, readiness shows the failure and the existing local deterministic
Elo fallback continues with explicit provenance.

Transfer targeting will derive teams from upcoming supported fixtures, resolve
their real provider team IDs from stored fixture/team evidence, exclude fresh
team-season rows, and sync only the bounded stale set. Player names stored,
logged, or displayed by this path pass through `to_chinese_player_name`.
`zero_targets`, `provider_id_missing`, upstream failure, and a successful
zero-record provider response are distinct outcomes. Prediction evidence binds
only records within the configured pre-match window and retains source and sync
timestamps.

### 6. Admin Operations Surface

Extend the existing `/admin` page rather than create a second administration
application. Add compact sections for:

- database backend, migration state, backup verification result, and service
  readiness;
- provider freshness and latest errors for ClubElo, transfers, player stats,
  lineups, player value, and news;
- player-impact rule coverage;
- ensemble availability and weight source;
- backtest and research eligibility plus recent persisted runs;
- bounded actions for existing sync, rule-generation, backtest, and research
  endpoints.

Actions require the existing admin authentication, show pending/success/error
states, prevent duplicate clicks while running, and refresh their affected
status. The UI does not expose secrets or render an unavailable source as zero.
Player value and news are visibly marked `unavailable: provider_required` until
their final activation stage.

### 7. Explicit Demo Mode

The Next.js backend proxy will return the backend's actual non-2xx status and
body. Connection errors and timeouts return an explicit gateway error with the
target path and a non-secret diagnostic category. Mock fallback is allowed only
when the server-side environment variable `WEB_DEMO_MODE=true`.

Demo responses retain `mode: demo`; production responses must not be relabeled
or replaced. Deployment readiness fails when demo mode is enabled in production.

### 8. Deferred Licensed Sources

Player value and pre-match news use separate provider interfaces and readiness
states. Until suitable sources are supplied, the current player-value null
provider remains active and the news producer remains disabled. Both return a
stable `unavailable` status and never reuse unrelated statistics as a proxy.

When the user supplies providers, each integration requires documented license
scope, authentication, supported competitions, stable IDs, rate limits,
historical availability, source timestamps, and production access. That work
will receive its own reviewed specification amendment and focused rollout; it
does not delay deployment of Sections 1-7.

## Failure Handling

- Invalid non-test database URL: abort startup before any schema operation.
- Migration or backup-restore verification failure: stop deployment and keep
  the current production release running.
- Missing player-impact inputs: persist no value; report the exact coverage
  reason and continue other fixtures.
- Insufficient backtest/research evidence: return gate details without
  persisting a conclusive run.
- ClubElo outage: preserve the last valid snapshot, record health failure, and
  use the labeled deterministic fallback where permitted.
- Missing transfer provider identity: report the affected team and skip it;
  never guess an ID.
- Backend proxy failure: return a gateway error unless explicit demo mode is
  enabled.
- Missing licensed source: return `unavailable: provider_required`.

## Implementation Order

1. Enforce the MySQL runtime boundary and align database documentation/tests.
2. Verify the production MySQL backup/restore workflow before migrations.
3. Generate and consume deterministic player-impact rules.
4. Repair ClubElo health handling and transfer target selection.
5. Activate gated backtest/research persistence and the real ensemble summary.
6. Add the admin operational view and explicit demo-mode behavior.
7. Deploy completed Sections 1-7, then verify services, public routes, and
   MySQL results.
8. Integrate player value and news only after authorized sources are supplied.

Each step is independently deployable and must preserve the prior verified
state. The implementation plan may split these steps into small commits, but it
must not reorder the MySQL backup gate after database-affecting deployment.

## Testing

Use focused tests proportional to each change:

- configuration tests for test-only SQLite and fail-fast non-test startup;
- MySQL URL normalization plus migration/backup script contract checks;
- deterministic player-impact generation, idempotency, cutoff safety, missing
  evidence, and Chinese-name conversion;
- backtest/research pass and fail gates, immutable reuse, and no-row-on-failure;
- populated global ensemble summary and frozen-prediction preservation;
- ClubElo stale-last-good behavior and transfer target/outcome distinctions;
- proxy non-2xx passthrough, connection failure, and explicit demo fallback;
- admin action state and readiness rendering for available/unavailable sources.

Run only the directly affected API and web tests, Python compilation, frontend
type/build checks required by changed shared contracts, and `git diff --check`.
A wider suite is required only if a shared repository or response contract
changes beyond these paths.

## Deployment and Verification

Deployment packages tracked `HEAD` and preserves the server `.env`, Python
virtual environment, frontend dependencies/build output as appropriate, and
existing MySQL data. Before extraction or migration, the verified MySQL backup
must complete. Build/compile failures, migration failures, or readiness failures
stop the rollout before service replacement.

After restart, verify all of the following on the server and through the public
Nginx route:

- `football-ai-api.service` and `football-ai-web.service` are active;
- API health reports `database_backend: mysql` and production readiness passes;
- public fixture, admin readiness, ensemble, backtest-run, and research-run
  routes return their real contracts without demo substitution;
- focused provider actions record truthful job/provider health;
- MySQL contains the expected new player-impact rows and only gate-passing
  backtest/research rows;
- unchanged source gaps remain `provider_required`, not empty success states;
- deployed commit and selected file hashes match tracked `HEAD`.

Rollback restores the previous application release. Database rollback uses the
verified pre-deployment dump only when a forward fix is unsafe; it is not
automatic, because restoring MySQL can discard valid writes made after the
backup. The rollback record must state which code release and database snapshot
were restored.

## Acceptance Criteria

- No non-test application process can start with SQLite.
- A verified restorable MySQL backup exists before production changes.
- Eligible existing evidence produces versioned player-impact rules and v2
  feature snapshots consume them cutoff-safely.
- Global ensemble responses contain real eligible fixtures or an evidence-based
  empty reason, never a hard-coded simulated placeholder.
- Backtest and research tables contain only runs that passed their declared
  gates; operators can see why a run is not yet eligible.
- ClubElo and transfer jobs distinguish freshness, failure, missing identity,
  and legitimate empty upstream results.
- Backend outages are visible outside explicit demo mode.
- Operators can inspect and trigger the scoped workflows from `/admin` without
  exposing credentials.
- The public deployment, system services, and resulting MySQL state are all
  verified independently.
- Player value and news remain truthful unavailable states until licensed
  provider work is separately approved.
