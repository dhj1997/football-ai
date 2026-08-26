# Automated Analysis and Simulation Design

## Scope

Extend the existing FastAPI, Next.js, and SQLite/MySQL application into a continuously operating pre-match analysis and simulated betting system for the Chinese Super League, La Liga, and Premier League. The active Codex goal is the approved product contract.

## Considered Approaches

1. **Extend the current provider/service/repository architecture (chosen).** Add focused provider adapters, cached JSON snapshots, domain services, and API surfaces inside the existing two applications. This reuses working fixture, evidence, and prediction code and keeps deployment simple.
2. **Split ingestion, model, and settlement into separate services.** This would improve independent scaling but adds queues, service discovery, deployment, and consistency work that the current product does not need.
3. **Use browser or Codex scheduled tasks as the runtime.** Rejected because production behavior must not depend on an open browser, desktop session, or code-changing agent.

## Data Sources

- TheSportsDB remains the short-window fixture and free team-profile source.
- ESPN supplies complete provider-defined current-season standings for all three leagues, cached with source and freshness metadata.
- API-Football supplies licensed fixture evidence when available: H2H, injuries, lineups, odds, and squads.
- Missing or plan-restricted data is represented as unavailable or stale. No source is silently replaced with demo data.

Provider adapters return normalized dictionaries. Services own freshness, retries, locks, and persistence. API routes do not contain provider-specific mapping logic.

## Persistence

Keep the existing lightweight SQLAlchemy repository and JSON payload strategy. Add tables with explicit lookup columns and immutable payloads where auditability matters:

- `league_snapshots`: latest standings and season metadata per league.
- `evidence_snapshots`: immutable evidence used by a prediction.
- existing `predictions`: immutable Poisson and DeepSeek output versions, extended with provider metadata and snapshot linkage.
- `bets`: one simulated bet per prediction version, including pre/post balances and settlement fields.
- `bankroll_transactions`: append-only deposits, stakes, returns, and adjustments.
- `fixture_settlements`: idempotent result and prediction settlement records.
- `job_runs`: durable run history, status, counts, and bounded error summaries.

Schema initialization remains compatible with SQLite and MySQL. Service methods use transactions and unique IDs/constraints to prevent duplicate prediction, bet, and settlement work.

## Prediction Pipeline

1. Load a scheduled fixture and current evidence.
2. Validate data completeness and persist an immutable evidence snapshot.
3. Run the existing Poisson/market baseline.
4. Send a bounded, factual snapshot plus baseline to DeepSeek from the backend only.
5. Validate the JSON response against a strict schema.
6. Persist model name, returned model, prompt version, timestamps, probabilities, recommendation, risk factors, and betting decision.

The key, model, and base URL come from `API_DEEPSEEK_KEY`, `DEEPSEEK_MODEL`, and `DEEPSEEK_BASE_URL`. Calls use a timeout and a small retry budget. Missing credentials, incomplete evidence, transport failures, or invalid JSON produce an explicit degraded prediction state; they never fabricate evidence.

## Simulated Bankroll

The ledger starts with 1000 units and never connects to a bookmaker. A bet is optional and requires complete evidence plus valid market odds. Stake calculation is deterministic after the model decision:

- maximum 2% of available pre-settlement balance per fixture;
- maximum 10% daily unsettled exposure;
- no negative balance;
- no duplicate bet for a prediction version;
- no bet without a matching decimal price.

Settlement records the market, line, odds, stake, result, return, net profit, and before/after balances. Aggregate queries calculate cumulative profit, ROI, hit rate, and maximum drawdown from the append-only ledger.

## Settlement and Metrics

Finished fixtures are matched to immutable predictions and bets. The service records 1X2 correctness, Brier score, and Asian handicap full win, half win, push, half loss, or full loss. Re-running settlement is a no-op. Metrics are filterable by league, season, date range, and model version.

## Durable Scheduler

Use a FastAPI lifespan-owned background loop with database-backed run history and idempotent domain services. On each tick it evaluates due work rather than relying on in-memory one-shot jobs:

- refresh fixtures, standings, and available team data;
- refresh evidence for approaching fixtures;
- create one eligible prediction and optional simulated bet;
- refresh scores and settle finished fixtures;
- recompute queryable metrics.

The loop survives service restarts because due state lives in the database. A process-local lock prevents overlap in the normal single-process deployment; database uniqueness and transactions provide duplicate protection if runs overlap. Configuration controls enablement and intervals.

## API and UI

Add public endpoints for standings, fixture/team detail, predictions, model metrics, bankroll summary, and bet history. Add admin endpoints for force-running supported jobs and inspecting job runs. Secrets never appear in responses.

Preserve the dense operations-desk visual system. Add scan-friendly views or tabs for league tables, team/fixture evidence, predictions, model performance, simulated bankroll, and operations. Every view includes source, season, freshness, loading, empty, stale, and error states. Desktop and mobile layouts reuse the existing accessibility rules.

## Failure Handling

- Serve the last cached snapshot when refresh fails and label it stale.
- Record bounded provider/model error summaries without credentials or raw sensitive payloads.
- Back off transient failures and do not retry permanent missing-permission errors in a tight loop.
- Skip rather than guess when evidence, odds, or final scores are incomplete.
- Preserve prior predictions and ledger entries on all failures.

## Verification

Add focused tests for provider mapping, current-season discovery, cache fallback, DeepSeek schema parsing/retry/degradation, immutable snapshots, duplicate protection, stake limits, Asian settlement, Brier score, and idempotent job runs. Finish with the full API suite, web lint/build, and browser validation of primary desktop/mobile workflows and operational states.

