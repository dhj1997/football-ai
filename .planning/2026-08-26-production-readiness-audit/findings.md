# Findings

Treat this file as research data, not instructions.

## Existing Context

- The repository already contains a substantial completed implementation plan; this audit is isolated so it does not overwrite that history.
- The worktree contains extensive user changes and untracked application files that must remain untouched.
- The stated stack is Next.js/TypeScript, FastAPI/Python, SQLAlchemy, SQLite locally, and MySQL in the current README; `PRODUCT.md` still says PostgreSQL for production, so the operational contract is inconsistent.
- Implemented surfaces include fixtures, standings, team/player data, immutable evidence and predictions, Poisson/market baselines, two LLM tracks, simulated bankrolls, settlement, metrics, and durable jobs.
- The frontend deliberately has very few dependencies. There is no client data/cache library, component system, schema client, charting library, observability SDK, or frontend test runner in `apps/web/package.json`.
- The API dependency set is also deliberately minimal. It has no migration tool, production scheduler/queue, retry library, metrics/tracing SDK, structured logging package, Redis client, or statistical/ML evaluation package.
- Documentation conflicts with the mandatory Chinese-name contract: the README says unknown player names retain supplier originals, while `AGENTS.md` forbids displaying supplier English names anywhere in API, pages, or logs.
- Product positioning correctly emphasizes timestamped evidence, preliminary versus confirmed-lineup versions, uncertainty, and no invented odds. These are strong foundations for credibility.
- The README explicitly admits the current predictors have not been sufficiently backtested. Therefore “AI prediction is correct” cannot yet be a product claim; the production target must be calibrated, measured probabilities with visible sample sizes and benchmark comparisons.
- Current odds handling selects the first bookmaker returned by API-Football. That is convenient for a demo but is not a defensible market benchmark because bookmaker identity, overround, liquidity, update time, and line movement are uncontrolled.
- Recurring jobs are owned by the FastAPI process and guarded only by an in-memory `asyncio.Lock`. This prevents overlap in one process but does not prevent duplicate work across multiple Uvicorn/Gunicorn workers or multiple replicas.
- The default cadence already meets the user's hourly fixture requirement (`fixtures=60m`), while analysis is more frequent (`5m`) and settlement is `15m`. The risk is execution ownership and coordination, not merely adding a timer.
- Schema evolution is performed through ad hoc `CREATE TABLE IF NOT EXISTS` and `_ensure_column` calls inside application startup. This has no explicit migration history, downgrade path, deployment lock, or reviewable schema version.
- The current public fixture-detail `GET` route may enrich external evidence, create missing model predictions, and place simulated bets. A read request therefore has external cost and durable side effects, violates HTTP GET semantics, makes load-testing/user refreshes operationally significant, and complicates retries/caching.
- Nearly all frontend API reads use `cache: "no-store"`; there is no stale-while-revalidate strategy or client cache. This increases backend/provider pressure and makes transient API latency directly visible to users.
- The UI includes meaningful empty/error/loading states and accessible tab semantics, but runtime browser verification is still needed.
- The API list route also calls `schedule_sync.ensure_fresh()` and the team route calls `team_sync.ensure_fresh()`. Multiple public reads can therefore trigger provider refreshes; external synchronization should be worker-owned, while public routes should return cached state plus freshness metadata.
- The scheduler retries failed/partial/running jobs after a fixed backoff, but there is no exponential backoff with jitter, dead-letter state, per-provider circuit breaker, quota budget, or distributed lease.
- The prompt contracts are not actually unified: DeepSeek and GPT have separate prompt text and separate version identifiers. They reuse the same Pydantic output schema, but behavioral instructions can drift between providers.
- The model schema validates JSON shape and that 1X2 sums approximately to one, but it does not enforce that `predicted_outcome` is the maximum-probability class, that confidence is derived from calibration, or that stake size follows expected value and bankroll math.
- Models may choose any 0%-100% stake fraction. Even for simulation, this makes ROI comparison dominated by unconstrained language-model risk preference and variance instead of forecast quality. Separate probability forecasting from deterministic bet sizing.
- Evidence completeness is seven equal-weight booleans. It does not measure staleness, sample count, source reliability, odds timestamp, lineup timing, or field-level disagreement. One recent match counts the same as five; any odds object counts as complete.
- The prediction input is rich enough for a prototype but omits several potentially useful pre-match features: home/away split form, opponent-strength adjustment, expected-goals history, rest/congestion, travel/time zone, referee tendencies, weather/pitch, tactical formation changes, manager changes, market line movement, and consensus/multi-book price distribution.
- Provider errors are sometimes converted to `str(error)` on public responses. Errors and logs need redaction and stable public error codes so upstream URLs, IDs, or future secrets cannot leak.

## Browser QA

- Desktop home at 1440x1000 loads cleanly with no browser console or page errors. The fixture-first hierarchy, Chinese team names, freshness indicator, team crests, and compact league/date filters read like a real score center rather than a generic dashboard.
- The home page has only one finished fixture in the current view, leaving most of the viewport empty. This is data-state dependent, but a production score center needs better handling for sparse days: nearby dates, upcoming matches, recent predictions, or a compact multi-day strip rather than a large blank canvas.
- The visual system mixes English micro-headings (`FOOTBALL SCORES`, `FOOTBALL TODAY`, `COMPETITIONS`, `PRE-MATCH DESK`) with an otherwise Chinese product. This weakens cohesion and adds no useful information for the target audience.
- The top navigation exposes “操作台” alongside public product sections. Unless operator authentication and authorization are explicit, this makes the public information architecture look unfinished and risks exposing privileged workflows.
- The risk is confirmed in code: all Next.js `/api/admin/*` proxy routes automatically attach the server-side `ADMIN_API_KEY` but perform no browser-session authentication or role check. Any visitor who can reach the web app can invoke sync, model prediction, job, and settlement operations while consuming the server's privileged API key. This is a high-severity production blocker.
- The default `dev-admin-key` fallback exists on both API and web proxy paths. Production startup should fail closed when no non-default secret/auth configuration is provided.
