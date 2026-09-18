# Football AI v2 Round 1 Historical Audit

## Audit, Architecture and Data/Feature Plan

**Date:** 2026-09-15
**Scope:** Audit + Architecture + Data/Feature Plan only
**Implementation status:** This document is design output. No business code, schema migration, deployment, commit, or push is included in this round.

> **Historical status:** This report preserves the Round 1 audit as a point-in-time record. From Round 3 onward, `docs/Football_AI_v2_no_ML_architecture_plan.md` is the only authoritative roadmap. Earlier recommendations in this report to add XGBoost, OOF/stacking/meta-models, learned ensemble weights, Platt/Isotonic/temperature fitting, or any other trainable ML component are superseded and must not be implemented. Football AI v2 is limited to transparent statistical models, deterministic rules, market information, and evidence-based LLM explanation.

## 1. Executive Decision

The repository already has the product and evidence foundation required by the v2 plan. The correct next move is an incremental convergence around explicit contracts, not a second parallel prediction platform.

The existing FastAPI/Web application, provider adapters, immutable evidence and prediction records, model registry, market intelligence, backtest engine, automation, and simulated portfolio remain the system of record. The next implementation phase should add a durable feature snapshot/value boundary and field-level point-in-time metadata, then connect existing model services to that boundary through adapter and dual-read/dual-write steps.

The four decisions for the next phase are:

1. Keep the current pipeline and ownership boundaries: `Raw -> Normalized -> Canonical -> Snapshot -> Feature -> Prediction -> Evaluation`.
2. Treat `available_at <= prediction_timestamp < kickoff_at` as a required contract for every feature and model input. A source capture after the prediction timestamp is rejected, not silently corrected.
3. Separate prediction, market prior, edge, decision, and execution. LLM output remains structured explanation/risk/scenario input; numeric models and the decision layer own probabilities, EV, and action eligibility.
4. Split current-serving prediction reads from immutable revision history before enabling v2 drift analysis. Current retention deletes superseded revisions and therefore cannot be treated as the v2 history store.

## 2. Evidence and Method

This audit used the source plan (`docs/football-ai-v2-codex-plan.md`), existing architecture documents, repository code, schema definitions, and focused tests. Statements marked “implemented” are backed by code or tests; source-plan statements are requirements, not proof of implementation.

Primary evidence locations:

- `apps/api/app/database.py`: schema and repository persistence.
- `apps/api/app/evidence_chain.py`, `provider.py`, `espn_evidence_provider.py`, `schedule_provider.py`, and `dongqiudi_provider.py`: provider/fallback behavior.
- `apps/api/app/data_quality_engine.py` and `historical_validation.py`: canonicalization, quality, as-of reconstruction, and leakage checks.
- `apps/api/app/prediction_intelligence.py`, `recent_form.py`, `elo.py`, `player_impact.py`, and `market_intelligence.py`: current feature and market primitives.
- `apps/api/app/model_platform.py`, `model_registry.py`, `model_fitting.py`, and `backtest_engine.py`: model, lifecycle, calibration, and temporal evaluation.
- `apps/api/app/prediction_service.py`, `dual_prediction_service.py`, `market_decision.py`, and `automation.py`: production prediction, decision, and refresh flow.
- `apps/api/tests/test_p0_integrity.py`, `test_p10_model_platform.py`, `test_p12_backtest_engine.py`, `test_model_evaluation.py`, and automation/provider tests: existing contracts.

## 3. Current-State Audit

### 3.1 Capability matrix

| Area | Current evidence | Status | v2 gap / risk | Priority |
|---|---|---:|---|---:|
| Provider adapters | API-Football, ESPN, TheSportsDB, Dongqiudi and Football-Data adapters exist; `EvidenceProviderChain` orders API-Football -> ESPN -> public TheSportsDB, with Dongqiudi lineup fallback | Partial | No single capability/envelope contract across all providers; source quality and event time are not uniform | P1 |
| Raw provenance | `raw_data_records` stores source, source record ID, payload hash, captured and ingested times; sync runs are persisted | Implemented locally | Envelope does not consistently expose `retrieved_at`, `event_time`, quality, and normalization status to every caller | P1 |
| Canonical identity | Competition registry, canonical fixture/team IDs, identity maps, stage normalization, conflict records | Partial/strong | Main fixture storage still carries legacy `league_key`/provider-centric semantics; stage leg/aggregate remains partial | P1 |
| Six-competition domain | Registry defines CSL, EPL, La Liga, CFA Cup, UCL, ACL and ten capability dimensions | Partial | Historical, evaluation, team, lineup, and injury capabilities are unavailable/partial for fixture-only competitions; frontend/backend capability drift remains | P1 |
| Evidence snapshots | Append-only `evidence_snapshots`, hashes, source timestamps, merge/fallback metadata, immutable tests | Implemented | Evidence is broad JSON; field-level availability is not a first-class contract | P1 |
| Odds snapshots | Append-only multiple captures, decimal normalization, de-vig consensus, timelines, CLV | Implemented/partial | Provider capability and quote schema are not uniform; current odds can be confused with the closing-market benchmark if callers skip the as-of boundary | P1 |
| Feature snapshot | `build_feature_snapshot` covers form, standings, squad, schedule, and market context with a leakage summary | Partial | Snapshot is embedded in prediction payloads; no generic `feature_values` table and no per-feature `available_at` map | **P0** |
| Team features | Recent form is as-of and decayed; Elo and standings strength exist; deterministic Poisson/DC path exists | Partial | Event-derived xG, xGA, shot quality, PPDA, and robust rest/fatigue features are not consistently available | P1 |
| Player features | Squad, injury/availability, lineup, player identity and impact/retention logic exist; Chinese localization is enforced | Partial | Coverage depends on provider and identity resolution; missing players must remain explicit instead of becoming zero-confidence claims | P1 |
| Rest/fatigue/travel | Schedule context and kickoff timestamps exist | Missing/partial | No durable, versioned rest/travel/fatigue feature group with source and cutoff evidence | P1 |
| Numeric models | Unified `ModelPrediction` supports Poisson, Dixon-Coles, Elo, market baseline, ensemble, and calibrated ensemble with explicit readiness/failure | Implemented/partial | The source plan's XGBoost target is superseded; transparent statistical engines still need a common feature contract | P1 |
| LLM integration | DeepSeek/GPT structured provider responses, prompt/evidence versions, dual service, schema failures | Partial | Disable LLM probability/weight/goal/stake inputs in v2 production with a fail-closed gate; retain only evidence structuring and read-only explanation | P0 |
| Legacy learned ensemble | Train-only inverse-Brier weights, registry artifacts, candidate/champion gates, learned-vs-default weights | Legacy compatibility only | Disable existing v2 production selection/execution, fail closed on learned paths, and retain artifacts only for read-only historical revision audit | P1 |
| Calibration | Temperature scaling is validation-only in the legacy model protocol and evaluation; Brier/Log Loss/RPS/ECE-related reports exist | Legacy compatibility only | Fitted calibration is outside v2; keep only a versioned rule-based framework, evaluation, probability audit, and historical reliability analysis | P1 |
| Uncertainty/agreement | Market decision has uncertainty and lineup warnings; ensemble exposes member weights | Partial | No unified interval/credible-band and model-agreement object carried through every prediction | P1 |
| Prediction lifecycle | Prediction timestamps, model/feature/evidence/odds references, immutable updates and kickoff guards are tested | Partial | Retention keeps only the latest compatible record and deletes older dependencies; this conflicts with required revision history | **P0** |
| Decision/execution | Market, EV, edge, stake, quality, freshness, and risk gates are downstream; incomplete strategy chains return unavailable | Implemented/partial | Need a stable v2 object that prevents decision fields from being mistaken for probability fields | P1 |
| Backtest | P12 chronological expanding/rolling/walk-forward, cross-competition/model comparison/strategy modes, manifests, market benchmark, complete-chain ROI gate | Implemented/partial | Legacy API and reports retain three-league naming; point-in-time deterministic rule/statistical replay still needs a stable acceptance contract | P1 |
| Registries | Model registry lifecycle and promotion gates; competition/provider registries; experiment/research runs | Implemented/partial | Feature registry and feature ownership/availability rules are not persisted as a first-class registry | P1 |
| Automation | Durable job runs, 5-minute lineup polling, 60/30 lineup windows, prediction offsets, odds re-prediction, history/backfill/ensemble jobs | Implemented locally | Code proves scheduler behavior only; remote process health, job-run freshness, provider response, prediction revision, and execution remain separate observables | P1 |
| UI/API | Models, features, ensembles, backtests, calibration, provider health, and admin job routes exist | Partial | Some endpoint names and UI surfaces remain three-league or workspace-centric; v2 Data/Model/History views should follow backend contracts | P2 |

### 3.2 Critical findings

#### P0-A: Feature time semantics are not durable enough

The project already rejects future evidence in several paths, but `build_feature_snapshot` exposes one snapshot-level timestamp and a rejected-field list. It does not persist an `available_at` value for each feature/value. A future correction to one nested field can therefore be difficult to detect after serialization.

Required disposition: add a feature snapshot/value contract in the next implementation phase. Until then, no new model may claim complete point-in-time safety merely because its parent evidence snapshot is timestamped.

#### P0-B: Current retention conflicts with revision research

`PredictionService._save_current` invokes `prune_prediction_history`. The repository groups records by competition, fixture, and model, retains the latest prediction compatible with the active prompt version, and deletes superseded predictions plus unreferenced evidence, bets, and settlements. That is appropriate for a current simulated ledger, but it destroys the T-24h/T-12h/T-6h/T-1h/T-30m revision chain required by v2.

Required disposition: define immutable `prediction_revisions` (or an equivalent archival namespace) and make current-serving reads a projection over it. Do not disable retention blindly because historical simulated bets and ledgers must remain coherent.

#### P1-A: Provider capability is distributed

The fallback chain and competition registry are useful, but each adapter has different methods and timestamps. A provider can be configured for schedules while unavailable for lineups, odds, or historical data. Capability must be checked per entity type and competition before a feature is marked available.

#### P1-B: Legacy ML targets are superseded

The Round 1 source plan included XGBoost, fitted calibration comparison, and OOF predictions. Those targets are now invalid under the strict no-ML architecture and are not implementation gaps. Continue with the existing Poisson/Dixon-Coles/Elo primitives, explicit feature values, deterministic probability fusion, and rule-based calibration according to `docs/Football_AI_v2_no_ML_architecture_plan.md`.

#### P1-C: Three-competition assumptions remain

The registry is six-competition aware, but historical/evaluation/backtest APIs and some UI paths still use three-league terminology. This can produce false coverage claims unless capability status is returned beside every result.

## 4. Target Architecture (minimal increment)

### 4.1 Ownership boundaries

```text
Provider adapters
  -> Provider envelope + raw immutable record
  -> Normalizer / identity resolver / capability gate
  -> Canonical competition, season, team, player, fixture, event, odds
  -> Point-in-time evidence and market snapshots
  -> Feature builder + feature registry + feature snapshot/value store
  -> Transparent statistical adapters (Elo/Poisson/DC/source-backed xG)
  -> Deterministic probability fusion + rule-based calibration + agreement/uncertainty
  -> Prediction revision archive + current prediction projection
  -> Market/EV/No-Action decision
  -> Portfolio execution (simulation or later production integration)
  -> Settlement / evaluation / research
```

Existing modules remain the owners where possible:

| Boundary | Keep/reuse | v2 responsibility |
|---|---|---|
| Provider and raw ingestion | Provider classes, `raw_data_records`, `data_sync_runs` | Return one envelope, preserve payload/hash, declare capability and quality per entity |
| Canonical domain | `competition_registry.py`, `historical_validation.py`, identity maps, `data_quality_engine.py` | Stop leaking provider/league vocabulary into downstream feature/model contracts |
| Evidence/market snapshot | `evidence_chain.py`, `prediction_service.py`, `market_intelligence.py`, snapshot tables | Make capture/source-updated/event-time semantics explicit and queryable as-of |
| Feature engine | `prediction_intelligence.py`, `recent_form.py`, `elo.py`, `player_impact.py` | Split feature groups, persist values and `available_at`, expose missing/rejected states |
| Model platform | `model_platform.py`, `model_fitting.py`, `model_registry.py` | Consume only a versioned feature snapshot; version formulas, statistical state, and explicit configuration; freeze legacy learned paths |
| Prediction and decision | `prediction_service.py`, `dual_prediction_service.py`, `market_decision.py` | Persist revision archive, keep probability/market/edge/decision separate |
| Evaluation | `historical_validation.py`, `model_evaluation.py`, `backtest_engine.py`, research runs | Consume frozen feature/model manifests; compare all baselines and closing market |
| Automation/observability | `automation.py`, `job_runs`, provider health/admin routes | Report job -> snapshot -> prediction -> decision -> execution as separate statuses |

### 4.2 Canonical provider envelope

Every provider method that contributes data to the prediction path should converge on:

```json
{
  "provider": "api-football",
  "entity_type": "lineup",
  "provider_event_id": "provider-match-123",
  "provider_record_id": "provider-record-456",
  "retrieved_at": "2026-09-15T10:00:00Z",
  "event_time": "2026-09-15T09:58:00Z",
  "payload_hash": "sha256:...",
  "source_quality": "complete",
  "capability_status": "supported",
  "payload": {}
}
```

`retrieved_at` describes our observation, `event_time` describes when the source says the fact occurred or became effective, and `available_at` is derived by the normalization layer as the earliest time the fact could have been used. A missing event time must not be silently treated as current truth.

### 4.3 Feature Snapshot contract

The next feature boundary should be a deterministic, immutable object. The exact storage implementation is a Phase 2 task; this is the contract to implement against:

```json
{
  "feature_snapshot_id": "feature:canonical-fixture:as-of:version",
  "canonical_fixture_id": "fixture:...",
  "prediction_timestamp": "2026-09-15T10:00:00Z",
  "kickoff_at": "2026-09-15T12:00:00Z",
  "feature_version": "features-v1",
  "dataset_version": "dataset-v1",
  "values": {
    "home.form.points_5": 2.1,
    "away.rest_days": 6,
    "home.player_availability.retention": 0.91
  },
  "feature_meta": {
    "home.form.points_5": {
      "available_at": "2026-09-14T20:00:00Z",
      "source_record_ids": ["raw:..."],
      "status": "available"
    }
  },
  "quality": {
    "schedule": "complete",
    "team_stats": "partial",
    "player": "partial",
    "lineup": "unconfirmed",
    "odds": "complete",
    "overall_score": 0.78
  },
  "leakage_check": {
    "passed": true,
    "rejected_features": []
  }
}
```

The snapshot ID must be deterministic from canonical fixture, prediction timestamp, feature version, and source snapshot IDs. Rebuilding the same inputs must produce the same ID and values.

### 4.4 Unified model and prediction objects

Every transparent statistical engine returns the existing readiness states and adds explicit provenance:

```text
ModelOutput =
  model_key, model_version, readiness,
  probabilities, expected_goals, score_distribution,
  feature_snapshot_id, calibration_version,
  statistical_state_cutoff, failure_reason, provenance
```

The persisted `PredictionRevision` carries:

```text
prediction_id
canonical_fixture_id
prediction_version / revision_number
prediction_timestamp
phase (preliminary | confirmed_lineup | frozen_pre_match)
feature_snapshot_id + evidence_snapshot_id + odds_snapshot_id
  model_version + fusion_rule_version + calibration_version + prompt_version
  raw_statistical_outputs / rule-adjusted probabilities
expected_goals / score_distribution / market probabilities
uncertainty / model_agreement / data_quality
key_factors / risk_factors
```

The decision object is derived, never fed back into the forecast:

```text
Decision = market + selection + market_probability + model_probability
         + edge + expected_value + reason_codes + action_status
         + stake_fraction + decision_policy_version
```

`action_status` may be `BET`, `NO_BET`, `NO_ACTION`, or `UNAVAILABLE`; it must not overwrite the stored model probability.

### 4.5 Lifecycle and freeze

Use current configuration as the starting schedule: prediction offsets `24, 12, 6, 1, 0.5` hours, lineup polling every five minutes with `60,30` windows and retry throttling, and odds re-prediction no more often than the configured 15-minute interval. The source plan's T-48h/T-20m labels are a target workflow, not a reason to bypass current scheduler evidence.

Each trigger creates a revision only when evidence, lineup, odds, or model output changes. At `kickoff_at`, the latest valid pre-match revision is frozen. Any future live model must use a separate record type and never mutate the pre-match archive.

Automation monitoring must expose four independent facts:

```text
job_run -> provider response -> snapshot changed -> prediction revision -> decision/execution
```

A successful scheduler tick does not prove that a lineup was returned or that a prediction was recomputed.

## 5. Data and Feature Plan

### 5.1 First source set

| Domain | First source order | Point-in-time rule | Missing behavior |
|---|---|---|---|
| Fixtures/results | TheSportsDB schedule, API-Football/ESPN supplements, Football-Data historical archive | Use source capture/event time; finished result is evaluation-only after kickoff | `missing`/`conflict`; never invent IDs or scores |
| Competition/standings | Competition registry + configured standings provider (ESPN/API-Football where supported) | Standings update must be `available_at <= prediction_timestamp` | `partial` or `unavailable`; capability returned with data |
| Team identity/profile | Provider team endpoints + identity maps | Stable identity may be reused; changing profile fields retain capture time | Preserve canonical ID; unresolved names are not model-ready |
| Team/player historical stats | API-Football, ESPN roster/stat feeds, existing team snapshots | Only completed matches and records known by cutoff | Per-feature `missing_reason`; no zero-as-observed substitution |
| Injuries/availability/lineup | API-Football -> ESPN -> Dongqiudi lineup fallback; roster enrichment from available provider | Use the provider's announced/observed time, not request time alone | `unconfirmed`, `partial`, or `unresolved_identity`; trigger no-action gates as configured |
| Odds | Existing API-Football/Dongqiudi captures plus Football-Data closing archive for research | Prediction features use only quotes captured by prediction time; closing market is an evaluation benchmark | `missing_odds`/`stale_odds`; strategy result is unavailable when required |
| Match events/team-match stats | Only providers that actually return the event/stat fields | Event time and source availability must precede the prediction cutoff | Keep domain absent; do not pretend xG/PPDA exists |
| Weather/referee/tactical | Deferred from the first implementation slice | No feature until a licensed/reliable source and timestamp contract exists | Not applicable, not a guessed default |

Provider capability is evaluated per `competition_key + entity_type + operation`, not just by whether an API key exists. All player names pass through `to_chinese_player_name` before API, page, or log exposure, and new provider aliases must be registered before the provider is considered complete.

### 5.2 MVP feature groups

The following groups are the first data-science slice from the source plan. They are definitions for implementation after this round, not code changes now.

| Group | Initial features | Construction and cutoff |
|---|---|---|
| Team strength | Elo, attack/defense rate, xG/xGA when observed | Compute from completed matches strictly before cutoff; version the statistical formula, state, explicit configuration, cutoff, and input fingerprint |
| Rolling form | 5/10/15 match points, goals for/against, weighted form, home/away splits | Use existing as-of recent-form service; retain sample size and decay lambda; no future rows |
| Home/away | Home team home split, away team away split, venue indicator | Use only historical matches with completed scores before cutoff |
| Rest/fatigue | Rest days, matches in previous 7/14 days, congestion flag | Derive from prior fixture kickoffs known by cutoff; travel remains deferred unless source-backed |
| Player availability | Squad count, confirmed starters, absence count, attack/defense retention, replacement gap | Use identity-resolved availability and lineup snapshots; distinguish estimated from observed minutes |
| Odds normalization | Decimal odds, overround, de-vig 1X2 probabilities, bookmaker count, movement | Use latest quote captured by cutoff; preserve opening/current/closing roles and source timestamp |
| xG | Expected home/away goals, xGA, npxG if source-backed | Start with observed event/stat data; deterministic Poisson/DC may consume xG, but missing xG remains missing |
| Market prior | De-vig market probability and market agreement | Market is a separate prior/benchmark; it must not mutate the raw model forecast |

Later phases may add deterministic fusion, rule-based calibration, probability audit, historical reliability analysis, and uncertainty reporting. XGBoost, LightGBM, Random Forest, Transformer/LSTM/GNN, OOF/stacking/meta-models, SHAP/Optuna, learned or adaptive weights, and fitted calibration such as Platt, Isotonic, or temperature scaling are permanently outside Football AI v2. Any future reconsideration of fitted calibration requires a separate architecture assessment and does not reopen the v2 roadmap.

### 5.3 Feature value requirements

Every persisted feature value must carry:

```text
feature_name
feature_version
value / typed value
canonical_fixture_id or canonical_team_id / canonical_player_id
prediction_timestamp
available_at
source_record_ids
calculation_version
status (available | partial | missing | stale | conflict | rejected_future)
missing_reason
```

Rules:

1. `available_at <= prediction_timestamp < kickoff_at` for pre-match prediction.
2. `captured_at <= prediction_timestamp`; `source_updated_at` is retained separately and never treated as capture time without an explicit policy.
3. A feature built from multiple records uses the latest permitted record for each component and records all source IDs.
4. `rejected_future` is observable and excluded from the model vector; it is never converted to a neutral numeric default.
5. Estimated player minutes, inferred lineup probabilities, and provider partial responses are marked as estimated/partial in metadata.
6. Feature formulas and constants live in versioned code/registry entries, not team-name or “star player” branches.

### 5.4 Quality and action gates

Quality is reported by component, then aggregated without hiding failures:

```text
schedule, team_stats, player, injury, lineup, odds, event, weather
```

Each component uses `complete`, `partial`, `stale`, `missing`, `conflict`, or `not_applicable`. The aggregate score remains comparable with the current data-quality engine, but action eligibility must also inspect critical component statuses.

Minimum behavior:

- Missing or conflicting identity, kickoff, or source timestamps: no model-ready prediction.
- Missing form/team history: prediction may be marked `limited`; no automatic action when the configured quality gate fails.
- Unconfirmed lineup: preliminary prediction is allowed if policy permits, but action carries `UNCONFIRMED_LINEUP` and is re-evaluated after confirmation.
- Missing/stale odds: forecast may exist; market/EV/strategy is `unavailable` or `STALE_ODDS`.
- Low-sample reliability or weak statistical/rule agreement: expose uncertainty and use `NO_ACTION`, never an LLM confidence score.

### 5.5 Persistence plan after round one

Reuse existing tables first. The smallest next schema increment is:

```text
feature_snapshots
- feature_snapshot_id, canonical_fixture_id, prediction_timestamp, kickoff_at
- feature_version, dataset_version, quality_payload, leakage_payload, created_at

feature_values
- feature_snapshot_id, feature_name, value_json, available_at
- status, missing_reason, calculation_version, source_record_ids
```

Then add an archival `prediction_revisions` projection or equivalent append-only namespace. Existing `predictions`, `evidence_snapshots`, `odds_snapshots`, `historical_snapshots`, `historical_predictions`, `model_registry`, `backtest_runs`, `research_runs`, and `job_runs` remain authoritative until a verified dual-read/write migration is complete.

Required version links in every prediction/backtest manifest:

```text
dataset_version
feature_version
model_version
fusion_rule_version
calibration_version
strategy/decision_policy_version
code_version
```

### 5.6 Point-in-time evaluation protocol

Use chronological or rolling-origin evaluation only. The statistical formula, deterministic fusion rule, and rule-based calibration version must be fixed before each evaluation window:

```text
history window    -> reconstruct cutoff-safe statistical state and features
evaluation window -> replay the predeclared formulas and rules unchanged
report            -> compare forecasts, reliability, market benchmark, and decisions
```

No run may fit a generic feature-to-outcome learner, meta-model, fusion weight, or calibration parameter. The closing market is a benchmark unless the quote was genuinely available at the prediction timestamp. Every run stores an input fingerprint, cutoff range, statistical formula/state version, feature version, fusion/calibration rule versions, environment, and exclusion counts.

Minimum comparison set:

```text
league majority
home-advantage baseline
Elo
Poisson / Dixon-Coles
market implied probability
candidate deterministic fusion rule
```

Metrics: sample size, coverage/abstention, Brier, Log Loss, RPS, ECE/reliability, calibration status, ROI/CLV only with a complete execution chain, yield, drawdown, and stability by window/competition. No fixed accuracy target is accepted as proof of quality.

## 6. Superseded Implementation Order

The Round 1 sequence is no longer operative. Continue only under `docs/Football_AI_v2_no_ML_architecture_plan.md`:

1. Extend the existing Round 2 feature snapshot/value layer and feature registry; do not create a parallel Feature Store.
2. Promote cutoff-safe form, Elo, player availability, rest, odds, and source-backed xG inputs into named, versioned feature groups.
3. Add a fail-closed v2 production deny gate for legacy learned engines, weights, training artifacts, fitted calibrators, and LLM-generated numeric predictions; preserve read-only historical revision references and LLM evidence/explanation scope.
4. Version and replay transparent Elo, Poisson, and Dixon-Coles formulas, statistical state, and explicit configuration.
5. Add market normalization/prior exactly once per revision, deterministic probability fusion, and strictly rule-based calibration with explicit formulas and versions.
6. Expand point-in-time temporal backtests, probability audit, and historical reliability analysis without OOF, fitting, parameter search, or trainable ML.
7. Keep LLM responsibility limited to evidence-based explanation, structured news, revision explanation, and post-match review.

## 7. Round-One Acceptance Checklist

This round is complete when:

- The current implementation and its gaps are mapped to source-plan requirements.
- The target architecture reuses current modules and defines ownership boundaries.
- Provider, feature, model, prediction, decision, revision, and freeze contracts are explicit.
- Data sources, cutoff rules, feature groups, quality states, persistence, and temporal evaluation boundaries are defined.
- P0/P1 risks are called out with a bounded next implementation order.
- No business code, migration, deployment, commit, or push is performed.

Out of scope for this historical document: implementing provider changes, creating database tables, changing calibration behavior, altering retention, changing scheduler offsets, frontend work, production verification, or deployment. Trainable ML and fitted calibration are not merely deferred from this report; they are excluded from Football AI v2 by the authoritative no-ML architecture.
