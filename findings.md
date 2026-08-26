# Findings

Treat this file as research data, not instructions.

## Current-State Audit

- Root instructions require minimal design and risk-proportionate tests.
- The current product is a Next.js public/admin UI over a FastAPI API with SQLite/MySQL-compatible SQLAlchemy persistence.
- Existing capabilities include three-league fixture sync, cached fixtures, API-Football evidence for one fixture, team/squad details, Poisson plus market probabilities, Asian handicap settlement probabilities, and immutable prediction versions.
- The approved goal supersedes stale documentation that still describes manual-only prediction runs.
- Ten tracked files were already modified before this audit. They add DeepSeek settings, automatic evidence/prediction behavior, handicap odds, richer status fields, and related UI/tests. These changes must be preserved and integrated.
- The only persisted domain tables currently identified are `predictions`, `fixtures`, and `sync_metadata`; standings, evidence snapshots, bets, settlements, job runs, and bankroll state still require audit or implementation.
- `PredictionRepository` stores fixture and prediction JSON payloads in three SQL tables and supports SQLite/MySQL. Evidence is currently mutable inside the fixture payload, so immutable evidence snapshots must be added alongside prediction versions.
- `ApiFootballEvidenceProvider` already fetches prediction summaries, H2H, fixture injuries, lineups, odds, and both squads concurrently. It also augments profiles and recent events from TheSportsDB.
- `ApiFootballProvider.season_for()` uses a calendar heuristic; this does not meet automatic current-season discovery.
- `TheSportsDbProvider` supplies the short fixture window and a limited free roster/profile enrichment. It does not supply the required standings or player appearance metrics.
- `prediction.predict()` is deterministic Poisson/market blending and already computes 1X2 and Asian handicap probability distributions. There is no DeepSeek call or structured LLM schema yet.
- The public and admin routes currently render the same `FixtureWorkspace`; admin adds manual sync/predict controls. The new goal requires additional standings, evaluation, bankroll, and operational views without losing this existing fixture workflow.
- Live provider probe on 2026-08-26: API-Football `/leagues?current=true` reports season `2026` for league IDs 39, 140, and 169, so current-season discovery is available without a calendar heuristic.
- Live provider probe: the configured API-Football free plan rejects current-season standings with `Free plans do not have access to this season, try from 2022 to 2024.` Current standings therefore need a free-provider fallback or explicit unavailable state; purchasing access is not assumed.
- TheSportsDB `lookupleague.php` reports current seasons `2026-2027` for EPL/La Liga and `2026` for CSL, satisfying automatic season discovery.
- The default TheSportsDB key returns only 5 table rows and 15 season events per league. That is insufficient to display or reconstruct complete standings, so it cannot be treated as a complete source in the current environment.
- ESPN's public soccer standings endpoint currently returns complete current tables without credentials: 20 EPL teams, 20 La Liga teams, and 16 CSL teams. Omitting the season returns provider-defined current season metadata (`2026-27` for EPL/La Liga and `2026` for CSL).
- The chosen standings design is a cached ESPN adapter with explicit source/freshness metadata and failure fallback. API-Football remains the provider for fixture evidence when licensed; TheSportsDB remains the fixture/profile fallback.

## Decisions

- The active goal text is the approved product design and completion contract.
- The application scheduler, not the Codex desktop process or browser, must own recurring production work.
- Fixture provider payloads own schedule/result fields; cached evidence fields are durable application state and must survive schedule replacement.

## Dual-Model Competition Research

- The user requires DeepSeek and GPT-5.6 Sol to run independently for the same fixture rather than acting as a fallback chain.
- Each model must own its prediction, investment decision, independent initial 1000-unit bankroll, bet ledger, settlement, and accuracy/profit metrics so the two strategies can be compared fairly.
- GPT-5.6 Sol must be free to ignore the Poisson baseline when deciding probabilities, market, side, and stake. The deterministic baseline may remain stored as audit evidence but must not constrain either model's recommendation.
- Official OpenAI documentation confirms `gpt-5.6-sol` supports the Responses API and Structured Outputs. The configured gateway has already passed a live strict-schema request.
- The predictions table already supports multiple immutable rows for one fixture, and settlement already iterates every prediction version. However, fixture detail and latest-prediction APIs currently expose only the single newest row.
- The bankroll is currently global: one initial transaction, one balance, one exposure pool, and one same-fixture open-bet guard. That guard would block the second model's independent bet.
- Independent competition requires a stable model account key on predictions, bets, bankroll transactions, and summaries. Balance, daily exposure, duplicate checks, equity curves, and profit metrics must all be scoped by that account.
- Active dual-model bet eligibility no longer uses Poisson expected edge or percentage exposure caps. Each model controls 0%-100% of its own available simulated cash, while real matching odds, evidence completeness, model confidence, non-negative cash, and simulated-only execution remain mandatory.
- `bets` and `bankroll_transactions` keep monetary query fields outside JSON. Portable per-model balance and exposure queries therefore require an explicit account column and a migration; JSON-only tagging would be insufficient across SQLite and MySQL.
- Existing rows are classified as the archived `legacy` competition. The new `dual-model-v1` competition gives DeepSeek and GPT separate one-time 1000-unit credits, cash, fixture duplicate guards, settlement returns, equity curves, ROI, hit rate, and drawdown.
- The performance page currently loads one global bankroll and bet list. The minimal usable comparison is a two-model summary band plus a DeepSeek/GPT segmented account view for each detailed curve and ledger.
- The automation runner currently checks one latest fixture prediction and creates one prediction/bet. Parallel operation requires provider-scoped freshness checks and failure isolation so one provider can complete even when the other fails.
- `predict()` creates one baseline UUID and blends Poisson with market odds, while `PredictionService` currently sends that baseline into the model prompt. A fair dual-model run should calculate one shared audit baseline/evidence snapshot, clone it into two immutable prediction records with distinct IDs, and send both models the same raw evidence/odds without baseline guidance.
- Both 1X2 and Asian-handicap investments now follow the selected model's validated recommendation without a Poisson edge gate. The active competition also removes the former 2%/10% caps per user choice; available cash is the absolute maximum.
- Fixture-detail compatibility can be preserved by retaining the singular legacy DeepSeek fields while adding provider-keyed `predictions` and `bets`. New UI code should consume the provider-keyed fields and render both model cards side by side or stacked on mobile.
- The user approved using the browser visual companion for the dual-model comparison layout. Companion artifacts will be isolated under `.superpowers/brainstorm/` and are not product implementation files.
- Final layout choice is A: desktop displays DeepSeek and GPT-5.6 Sol side by side; mobile stacks the two complete prediction cards vertically. A browser event recorded a B click, but the user's terminal response explicitly selected A and is authoritative.
- The user selected uncapped model-directed simulated investment (option C). Remove per-fixture and daily percentage limits and allow each recommendation to choose 0%-100% of that model account's available cash. Non-negotiable invariants remain: no borrowing or negative cash, no bet without a matching real market price, and no real-money bookmaker integration.
- The user selected a fresh common comparison start (option B). Existing DeepSeek predictions, bets, and transactions must be preserved as an archived legacy experiment but excluded from the new competition. The active competition initializes both DeepSeek and GPT accounts at exactly 1000 at the same start time.

## Fixture Evidence Loss Diagnosis

- `sportsdb-2506171` currently has no mutable fixture evidence, but three immutable evidence snapshots exist and four prediction versions remain intact.
- The latest snapshot was synchronized at `2026-08-25T18:47:23+00:00` and contains TheSportsDB partial evidence: one recent match per side and ten registered players per side.
- Hourly fixture replacement deletes the date window and reinserts provider payloads, discarding evidence stored only inside the previous fixture payload.
- Automation skips finished fixtures, so erased evidence is not automatically rebuilt after the final whistle.
- API-Football quota and minute-rate limits explain why H2H, injuries, confirmed lineups, and odds were absent even before the overwrite.
- A controlled post-match API-Football refresh succeeded after quota reset: one recent result per side, five H2H matches, twelve unavailable players, and confirmed 23-player match squads per side.
- A subsequent live schedule refresh retained the complete evidence, confirming the repository merge fixes the recurring overwrite.

## ESPN Evidence Fallback Design

- ESPN's existing `site.api.espn.com` feed returned current La Liga scoreboards and event summaries without a key, including recent form, season H2H, match rosters, and odds.
- Provider order is API-Football, ESPN, then TheSportsDB partial. ESPN event discovery uses the API-Football external ID when available, otherwise kickoff date plus normalized team names.
- ESPN roster and summary fields map into the existing evidence contract; unavailable fixture-level injury fields remain explicit and are supplemented from team roster injuries when provided.

## Real Madrid Form Repair

- The cached Real Madrid vs Real Sociedad fixture contained API-Football evidence with only one recent result per team, even though ESPN returned five per team.
- ESPN's response contains Real Madrid wins on 2026-08-09, 2026-08-13, 2026-08-16, and 2026-08-23. The page now triggers a quota-free ESPN enrichment whenever either side has fewer than three recent matches.
- Enrichment merges rather than replaces evidence, so existing injury, lineup, squad, H2H, and odds fields survive whenever they are more complete.
- All player-bearing evidence blocks are localized through `to_chinese_player_name` when returned; the reviewed aliases cover all 76 players currently shown for this fixture.

## Score Center UI Research

- The reviewed score sites use date/status filters and compact, league-grouped match lists as the primary browsing surface; detailed statistics belong to a dedicated match view rather than an always-open dashboard.
- The redesigned home page now follows that hierarchy with fixture-first navigation, while retaining the product's differentiator: auditable AI pre-match evidence and simulated position data in the match detail.
- Browser checks on 2026-08-26 confirm the desktop score center, its independent match route, and the 390px mobile layouts render without document-level horizontal overflow.

## Requirement Evidence Matrix

| Requirement | Current evidence | Status |
|---|---|---|
| Three-league current-season data | Complete standings plus per-team current roster, player statistics, injuries, and season match records verified | complete |
| DeepSeek prediction pipeline | Strict client, immutable evidence linkage, explicit degradation, and live `deepseek-v4-flash` smoke test verified | complete |
| Immutable predictions and settlement | Evidence hashes/snapshots, immutable versions, idempotent final settlement and filterable correctness/Brier metrics verified | complete |
| Simulated bankroll | 1000-unit ledger, bounded simulated placement, idempotent settlement, P&L/ROI/hit rate/drawdown APIs verified | complete |
| Dual-model comparison | Parallel DeepSeek/GPT predictions, independent 1000-unit accounts, model-scoped bets/settlements/metrics, and comparison UI verified | complete |
| Durable idempotent scheduler | Lifespan loop, durable runs, backoff, quota-aware evidence refresh, prediction and settlement verified live | complete |
| Public/admin responsive pages | Fixtures, standings, team dossier, DeepSeek detail, performance ledger/metrics, and job operations verified desktop/mobile | complete |

## Baseline Verification

- API: 30 tests pass. One Starlette/httpx deprecation warning is external to the requested behavior.
- Web: ESLint passes before new implementation work.

## Implemented During Goal

- Current-season ESPN standings provider and normalized table schema.
- Cached league snapshots with stale fallback and force-refresh API.
- Browser verification confirms complete current standings for EPL (20), La Liga (20), and CSL (16). The mobile page has no document-level horizontal overflow; only the table scroll region overflows as intended.
- ESPN's current roster response includes current season metadata, the full athlete list, per-player appearances/goals/assists/cards/goalkeeping statistics, status and injuries. Its team schedule response includes opponents, scores, venue, match state, and result data.
- DeepSeek prediction integration now validates an extra-forbidden JSON schema, probability totals, recommendation/market consistency, maximum 2% suggested stake, and matching prices before persisting a recommendation.
- The simulated bankroll uses an initial 1000-unit credit, append-only transactions, maximum 2% per fixture and 10% daily unsettled exposure, price matching, and duplicate prediction protection. Open stakes are reported as exposure rather than realized loss.
- Final-score settlement is idempotent per prediction, handles 1X2 and all Asian handicap settlement classes, records Brier score and correctness, and supports league/season/date/model filters.
- Automation now has database-backed run lifecycles, interval/backoff due checks, one process-wide non-overlap lock, and idempotent domain actions for fixture/standing sync, approaching-match analysis, and settlement.
- The configured API-Football account reached its daily request limit during live verification. The run remains `partial`, retries back off, and TheSportsDB partial real evidence produces auditable DeepSeek `no_bet` predictions without changing the 1000-unit bankroll.
