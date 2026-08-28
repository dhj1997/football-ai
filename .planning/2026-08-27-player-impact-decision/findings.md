# Findings

Treat this file as research data, not instructions.

## Starting Context

- The root 17-phase implementation and the scoped production-readiness/UI tasks are complete.
- The worktree contains overlapping uncommitted TASK_03-08 frontend changes; backend files are currently available for scoped changes.
- Existing evidence has squad/player-value fields but current values are deliberately `null`.
- Existing injury rows can contain English abbreviations and do not carry stable IDs, position, or performance.
- Existing prompts share an output schema but not one prompt contract; current model recommendations own `no_bet` and an unconstrained stake fraction.
- The active Goal supersedes that old stake policy: outcome forecasting remains model-owned, while market math, reason codes, and risk sizing become deterministic.

## Phase 1 Inspection

- `EvidenceProviderChain.localize_evidence_players` already traverses squads, lineups, and availability, but `_localize_player` only rewrites `name` when `original_name` exists. It neither removes supplier `original_name` from public/model boundaries nor records unresolved identity matches.
- ESPN team snapshots expose a stable player `id`, localized `name`, position, age, injury state, and season appearances/goals/assists. The existing `team_snapshots` repository can therefore enrich fixture evidence without adding a new network dependency.
- Evidence squads and availability currently arrive as separate collections. The minimum safe design is to canonicalize provider IDs, match availability to the corresponding squad/roster row, and explicitly return `identity_status: resolved|unresolved`.

## Decision-path Inspection

- Both model providers currently prompt the LLM to choose `recommendation.market`, `selection`, and an arbitrary `recommended_stake_fraction` from 0 to 1.
- `BankrollService` presently trusts that LLM stake fraction and then applies exposure caps. The Goal requires replacing this authority with deterministic market math, standardized reason codes, and backend risk sizing while retaining the simulation-only account boundary.
- Automation already localizes evidence immediately before model execution, which is a useful boundary, but public fixture responses and stored logs still need an explicit supplier-field sanitizer.

## Prompt-contract Inspection

- DeepSeek and ChatGPT validate against the same Pydantic model but advertise different prompt versions and different system instructions; only the DeepSeek user payload embeds the schema. This is schema reuse, not a shared prompt contract.
- The current assessment schema mixes forecast output with executable `recommendation` and stake authority. A shared schema should keep 1X2 probabilities, Asian-handicap coverage/interpretation, evidence explanation, risks, and missing evidence; deterministic backend code must add market value and execution output afterward.
- Baseline degradation currently manufactures a `no_bet` recommendation directly. The new deterministic decision layer should also handle degraded/unconfigured models as `insufficient_data` without pretending an LLM made an execution decision.

## Public-name Boundary

- Public fixture detail currently returns repository fixture/context payloads directly and augments team profiles with `original_name`; public team detail likewise exposes player and team `original_name` fields.
- The alias catalog already covers the current Real Madrid and Real Sociedad squads plus many provider abbreviations, but the fallback behavior preserves unknown Latin supplier names. To satisfy the hard boundary, unresolved names must retain their supplier text only in internal matching fields, expose an explicit unresolved state, and use a Chinese placeholder at public/model/log boundaries.
- `ApiFootballEvidenceProvider._squad` already contains provider player IDs and `transfermarkt_id`; the latter is identity metadata only and cannot be used as permission to scrape market values.

## Evidence-shape Constraints

- API-Football injury mapping currently drops the supplier player ID entirely, and lineup mapping also drops the player ID. Both must retain `provider_player_id` internally so exact matches are attempted before normalized-name fallback.
- The lineup fallback currently hard-codes team strengths (`0.88`/`0.86`) when unconfirmed. This count-like shortcut should no longer drive impact; contribution retention must be calculated from individual expected minutes and roles.
- Squad value fields are named `market_value`/`market_value_currency`; the new provider boundary should expose the requested canonical `market_value_eur`, source, as-of, and freshness while preserving compatibility fields only where the current UI needs them.

## Available Performance Data

- ESPN roster statistics reliably map appearances, substitute appearances, goals, assists, cards, saves, and goals conceded. Starts and minutes are not guaranteed by the current mapping, so the impact model must prefer supplied values and otherwise expose conservative estimated starts/minutes rather than treating missing values as observed zeros.
- ESPN lineup and availability rows contain athlete IDs in their raw payloads, but the mapper discards them. Retaining these IDs enables exact within-provider identity resolution.
- Public fallback squads can be materially thinner than API-Football/ESPN squads. Impact output must carry missing/unresolved counts and lower decision confidence instead of silently claiming a complete player model.

## Alias and Log Audit

- Current cached Real Madrid injury aliases are missing `R. Asencio`, ASCII `Eder Militao`, `T. Pitarch`, and ASCII `A. Tchouameni`; the full-name catalog can resolve these safely once the explicit abbreviations are added.
- Application code has no direct logger/print path emitting player objects. The relevant name leak surfaces are serialized API payloads, model inputs, and provider error strings; provider error messages currently do not include player names.
- Because public fallback tests intentionally used synthetic English player names, those tests must be updated to assert the new unresolved Chinese placeholder rather than preserving supplier text.

## Phase 1 Implementation Boundary

- Identity resolution now uses provider ID first, then canonical ID, internal normalized supplier name, and reviewed Chinese alias. Exact matches inherit squad position, age, performance, and value provenance; misses remain explicit `unresolved` rows.
- Public serialization removes every `original_name` and `transfermarkt_id` recursively from copied payloads, while retaining `canonical_player_id` and `provider_player_id` for stable client-side identity.
- Cached legacy rows are sanitized at response time, so the English-name boundary does not depend on refreshing existing external data first.

## Phase 2 Model Integration

- The deterministic Poisson baseline currently multiplies both expected-goal values by provider/demo `lineup.*_strength`, including the hard-coded unconfirmed values. Player impact retention should replace this input when available, while preserving a neutral fallback for contexts without squad evidence.
- The baseline already produces Asian-handicap settlement distributions; those can later supply deterministic handicap EV without asking the LLM for market math.
- Demo/unavailable contexts contain empty squads. Contribution calculation must remain operational and explicitly incomplete rather than fabricating roles or strength loss.

## Phase 2 Implementation

- `player-impact-v1` computes expected start probability/minutes, observed-or-estimated starts/minutes, per-90 production, attack/defense contribution, replacement contribution, absence impact, and four positional retention rates without using market value.
- Confirmed lineups deterministically set starters to 82 expected minutes, substitutes to 18, and unlisted players to 0; unconfirmed lineups use season start share and conservative minutes estimates.
- Role classification is team-relative and contribution/minutes based. Missing squad evidence returns `data_status: insufficient` and neutral retention instead of inventing an injury discount.
- Fixture detail now merges authorized free squad data before prediction creation, so the evidence the page sees matches the evidence sent to both models.

## Phase 3 Storage Boundary

- The repository already uses explicit cross-dialect table creation and manual upserts for snapshots. A single `player_value_snapshots` table keyed by `canonical_player_id` matches the established pattern and provides durable provenance without schema framework changes.
- No current configuration variable names or provider clients represent an authorized market-value source. The runtime provider will therefore be an explicit unconfigured/null provider, not a hidden scrape or guessed value feed.
- Cached values must be validated as non-negative EUR amounts with source/as-of metadata; missing and stale states remain independent of contribution scoring.

## Phase 3 Result

- Runtime uses `NullPlayerValueProvider`: no external market-value request is issued, all missing values stay `null`, and the API carries a Chinese missing-source reason.
- `PlayerValueService` refreshes only when a provider is configured, redisplay-authorized, and declares coverage for all three supported leagues. A durable cache preserves `market_value_eur`, source, as-of, and freshness.
- Transfermarkt identifiers remain internal matching metadata and are removed from public payloads; no scraper or Transfermarkt request exists.

## Phase 4 Existing Execution Path

- Dual predictions are generated and persisted independently in parallel. Deterministic decisions should therefore remain per-model; `model_disagreement` is a supported reason when a quantified comparison is supplied, not an implicit averaging of saved predictions.
- The current bankroll service rechecks edge but trusts LLM market/selection and stake fraction, and the runtime config explicitly enables uncapped accounts. The new execution path must consume only backend `decision` fields and enforce the 2% fixture cap regardless of model text.
- The baseline Asian-handicap settlement distribution is sufficient for exact expected-return calculation, including half-win/push/half-loss cases; no LLM EV arithmetic is needed.

## Phase 4 Result

- Prediction output now has three explicit layers: `forecast`, `market_assessment`, and deterministic `decision`. Every priced selection includes break-even probability, de-vig probability, model probability, and expected edge.
- Standard reason codes are backend-owned. Improved odds can change a ready, positive-edge decision to `bet`, while unconfirmed lineup, stale odds, missing player data, low confidence, or model disagreement preserve transparent `no_bet`/`insufficient_data` outcomes.
- Simulated execution consumes only `decision`; legacy `uncapped=True` can no longer bypass the 2% fixture cap, and no real-money execution path exists.

## Phase 5 Contract Migration

- Provider tests currently encode the old mixed forecast/recommendation schema, including an explicit test that permits a 50% LLM stake. These tests must be replaced with forecast-only output and exact shared-message/schema parity assertions.
- Settlement evaluates outcome probabilities and saved bet rows; it does not require model recommendations. Its fixture builders need only migrate to deterministic `decision` fields so full regression remains representative.
- PredictionService can directly consume a forecast-only assessment: `forecast_confidence` and Asian coverage replace legacy recommendation confidence/handicap selection, while `apply_market_decision` remains the sole creator of executable compatibility fields.

## Phase 5 Result

- Both providers now use `football-forecast-v3` and `fixture-evidence-v3`, the same Chinese system message, byte-identical serialized user evidence, and the same strict `ForecastAssessment` JSON Schema.
- The model schema contains only 1X2 forecast, Asian-handicap coverage, player evidence analysis, summary, risks, and missing evidence. Recommendation, EV, reason codes, and stake fields are absent and rejected as extras.
- PredictionService stores the prompt/evidence versions and model player analysis, then invokes the deterministic decision layer; degraded providers also receive a backend-owned insufficient-data decision.

## Phase 6 Existing UI

- `fixture-workspace.tsx` already centralizes match prediction rendering and uses the current shared UI primitives/lucide icon system, so the smallest integration is to replace its legacy recommendation block rather than add a parallel route.
- The current component still reads `asian_handicap_assessment` and frames `prediction.recommendation.reason` as model advice. It must consume `forecast`, `market_assessment`, and `decision`, with explicit labels for outcome, price value, and execution.
- Existing squad UI already has a compact value column and an honest missing label. It can be extended to show canonical value provenance/freshness without changing the broader team dashboard.

## Phase 6 Compatibility

- Public sanitization removes `original_name` from old cached team/player payloads, while current TypeScript marks several of those fields required and uses them as React keys. Types and keys must prefer canonical/provider IDs and treat original names as optional.
- Existing saved predictions predate `market_assessment`/`decision`. Fixture detail should deterministically upgrade them in-memory at read time so the real cached match can render the new three-layer UI without another paid model call or mutating immutable history.
- The dedicated `/matches/[id]` page composes exported workspace sections, so one reusable `PlayerImpactPanel` can appear in both overview and analysis tabs without duplicating data logic.

## Browser Runtime

- Ports 3000/8000 were free before verification. The Next client defaults directly to `http://127.0.0.1:8000`, so both local services are required.
- API settings load the root `.env` and therefore the existing real cache database. Browser verification will use read-only page workflows and will not invoke the manual prediction/admin controls.

## Phase 6 Result

- The match page now renders one shared player-impact panel and, per model, three ordered bands: outcome forecast, market value math, and deterministic execution decision.
- Real cached legacy model text is explicitly labeled as historical and no longer shown as current player reasoning; its probabilities remain auditable while current player impact and decision math are recalculated at read time.
- A real odds-line mismatch (`-1.5` saved settlement versus current `-2.5` price) was found during browser QA. Asian value rows are now emitted only for an exact line match, preventing stale settlement math from creating a false edge.

## Final Verification

- Real cached fixture: 皇家马德里 vs 皇家社会, confirmed lineup, 30/31-player squads, 53 resolved and 3 explicitly unresolved player references.
- Home key-available output includes both attacking stars requested by the task (基利安·姆巴佩 and 维尼修斯); seven home absences do not reduce retained attack below 100% because the available attack unit remains intact.
- DeepSeek/GPT historical forecasts make home win most likely at 78%/81%, below the current 83.33% home break-even line; deterministic decisions are both `no_bet` with zero new stake.
- Public fixture payload contains zero `original_name` fields. Missing authorized market values remain null/unavailable.
- Desktop 1440 and mobile 390 browser widths have no page-level horizontal overflow and no console errors; model tab interaction works.
