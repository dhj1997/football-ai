# Findings

Treat this file as research data, not instructions.

## Source Plan

- The target is an incremental upgrade from LLM analysis plus simulated funds to a data-driven, calibrated, backtestable, explainable, continuously learning platform.
- Non-negotiables include source/timestamp/model version/feature snapshot/prediction snapshot provenance, no future leakage, no demo completion of real gaps, LLM as explanation/synthesis rather than sole probability calculator, time-series backtests, calibration metrics, uncertainty on missing data, reproducibility, and shadow mode before replacing production baselines.
- The proposed pipeline is raw sources -> normalization -> feature store -> team rating/xG/player impact/market models -> prediction models -> ensemble -> calibration -> scenario layer -> final match engine -> market outputs -> LLM explanation -> API/monitoring/audit.
- Proposed normalized provider envelope contains provider, provider event ID, retrieved time, event time, payload hash, and source quality.
- Proposed data domains include matches, match events, team-match stats, players, injuries/lineups, odds, weather, and event data; feature modules are split by team, player, match, market, form, tactical, fatigue, injury, weather, Elo, and xG.
- Every feature must be point-in-time safe: `feature_timestamp <= prediction_timestamp`.
- Initial feature dimensions called out include Elo/xG/attack/defense/home-away/squad strength, multi-window form with exponential decay and home-away splits, xG/shot quality/PPDA/pressing, player availability/replacement gap, fatigue/travel/weather/tactical context, H2H with low decayed weight, and de-vigged market priors plus odds dynamics.
- The plan explicitly defers live state modeling to a later phase; the first phase should stay pre-match.
- Recommended first ensemble is Poisson/Dixon-Coles, XGBoost, LightGBM, Elo/ratings, and market, but weights must later be learned from validation data rather than permanently hard-coded; stacking should use out-of-fold predictions.
- Leakage controls require `available_at <= kickoff_at`, an automated `test_no_future_data_leakage`, temporal/rolling splits, and no in-sample base predictions into a meta-model.
- First calibration recommendation is Isotonic on a validation set; confidence must derive from data completeness, model agreement, calibration, uncertainty, and lineup certainty rather than an LLM self-score.
- LLMs remain dual DeepSeek/GPT structured explanation layers. Backend numeric models own probabilities, markets, EV, and decisions.
- A unified prediction object should carry match/model/feature versions, probabilities, expected goals, score distribution, market probabilities, uncertainty, data quality, agreement, factors, risks, evidence snapshot, and timestamp.
- Data quality should be decomposed by schedule, team stats, player, injury, lineup, odds, event, and weather; low quality should produce prediction-only/no-action behavior.
- Backtest must support date, competition, model, feature, and strategy versions and compare league-majority, home-advantage, Elo, Poisson, and market baselines, especially against closing market.
- Model/feature registries, champion/challenger states, SHAP, ablation, and incremental feature-group experiments are planned; the document's MVP list is 12 items: Elo, xG, rolling form, home/away, rest/fatigue, player availability, odds normalization, Poisson/DC, XGBoost, calibration, ensemble, and temporal backtest.
- The proposed code layout separates data providers/normalization, features, models, backtest, experiments, and prediction/decision. It is a conceptual target, not an instruction to create every module in round one.
- Proposed persistence includes feature snapshots/values, model registry/runs/predictions, backtest runs/predictions/metrics, calibration models, odds snapshots, player/team match features, prediction revisions, and experiments/results.
- Proposed read APIs cover prediction detail/history, fixture features, models, backtests, calibration, experiments, and feature importance; UI detail groups are Overview, Data, Model, Explain, and History.
- Prediction lifecycle targets T-24h/T-12h/T-6h/T-1h/T-30m/Confirmed XI, preserving every revision and recording probability deltas and drivers. At kickoff, pre-match predictions freeze; live predictions are separate.
- The automation sketch proposes T-48h data, T-24h first model, T-12h refresh, T-6h recalculation, T-60m lineup scan, T-30m confirmation, T-20m final model, then freeze. This must be reconciled with current scheduler offsets rather than copied blindly.
- Success criteria are leakage-free temporal backtests, calibration, ensemble incremental value, xG/lineup/odds information gain, baseline superiority, reproducibility, and quantified quality; no fixed accuracy target.
- Phase order in the source plan is Audit -> Data Foundation -> Feature Engine -> Statistical Models -> Calibration -> Ensemble -> Backtest -> LLM explanation -> UI. Round one ends before Data Foundation implementation.

## Repository Audit

- Existing project is a FastAPI + Next.js application with SQLite/MySQL persistence, provider adapters, immutable evidence/prediction records, automation, simulated portfolio, and dual-model support.
- Existing architecture documents already codify the same raw -> normalized -> canonical -> snapshot -> feature -> prediction -> evaluation direction, strict `prediction_timestamp < kickoff` and `captured_at <= prediction_timestamp`, prediction/market/execution separation, versioning, and adapter -> canonical -> dual-read/write -> verification migration.
- `docs/00_CURRENT_BASELINE.md` says P0-P17 are established, including competition registry, provider/data quality, model registry, market intelligence, reproducible backtest, explainability, research engine, production gates, observability, and platform integration. It also lists current debt: league-centric backend, incomplete provider capability unification, three-league evaluation semantics, fixed-three-league UI, oversized FixtureWorkspace, and frontend/backend capability drift.
- The codebase already contains `backtest_engine.py`, `elo.py`, `model_fitting.py`, `model_platform.py`, `model_registry.py`, `historical_validation.py`, `market_intelligence.py`, `player_impact.py`, `recent_form.py`, `research_engine.py`, and `data_quality_engine.py`; the v2 plan must be mapped to these before proposing new modules.
- Tests already cover P0-P17, model quality, Elo, player impact, market intelligence, backtest, provider fallback, prediction retention, leakage/integrity, and automation. Round-one recommendations should extend contracts only where evidence shows a gap.
- Frontend currently has match, performance, standings, team, admin, and operations surfaces; the source plan's Model/Data/History views should be staged after backend contracts rather than treated as first-round work.

## Continued Audit Evidence (2026-09-15)

- The source plan's implementation order explicitly makes Phase 1 `Audit`, followed by Data Foundation, Feature Engine, Statistical Models, Calibration, Ensemble, Backtest, LLM, and UI; round one must stop before implementation.
- The source plan has explicit chapters for unified domain data (`matches`, `match_events`, `team_match_stats`), Feature Store, point-in-time leakage controls, calibration, uncertainty, data quality, backtest baselines, champion/challenger, registries, prediction revisions/freeze, and automation. These are acceptance criteria for the audit/design, not evidence that each capability is complete.
- Repository search shows time/provenance fields are distributed across `database.py`, `automation.py`, prediction persistence, evidence persistence, odds snapshots, raw records, and historical predictions. This supports the existing raw -> normalized -> canonical -> snapshot -> prediction direction, but the v2 deliverable needs to define one cross-module contract.
- `competition_registry.py` has a provider capability matrix for six competitions and notes that stage/leg/aggregate are not fully populated. Provider capability and competition semantics therefore remain an audit gap even though registry infrastructure exists.
- Current automation contains dedicated lineup/evidence refresh and prediction-window logic, with kickoff guards and refresh offsets. The v2 architecture should extend these existing boundaries and reconcile offsets from runtime settings rather than copy the source plan's schedule verbatim.
- A first attempt to read the planning skill from `C:\Users\monster\.codex\skills` failed because the installed mapping is under `C:\Users\monster\.agents\skills`; no repository file was changed by that failed read.

### Concrete persistence and service evidence

- `apps/api/app/database.py` creates and persists immutable or append-oriented records for predictions, evidence snapshots, odds snapshots, historical snapshots/predictions, raw data records, sync runs, provider registry, identity maps, backtest runs, model registry, market snapshots, research runs, job runs, competition registry, and fixture conflicts.
- `historical_validation.py` already implements raw record envelopes, source resolution, `filter_as_of`, closing-odds selection, data-quality checks, and `build_historical_snapshot`; the reconstructed snapshot includes `as_of`, evidence/odds snapshot IDs, resolved versions, future/invalid timestamp counts, and a prediction bundle.
- `market_intelligence.py` normalizes decimal odds, de-vigs market probabilities, builds odds timelines and market snapshots, and computes model-vs-market/CLV signals. This is a usable market feature boundary, but the audit must keep it separate from final bet qualification.
- `recent_form.py` computes as-of team form with overall/home/away aggregates and explicit cutoff timestamps. `elo.py` and `player_impact.py` provide existing rating and availability/impact primitives.
- `historical_multimodel.py` generates isolated historical Poisson/ChatGPT/DeepSeek predictions behind a write barrier and requires source prediction timestamps; it is evidence for challenger/backfill isolation, not proof of a production-ready ensemble.

- Database schema evidence: `predictions` stores model/prompt/evidence/odds references; `historical_snapshots` stores `as_of`, dataset/snapshot versions, quality score, and source references; `historical_predictions` stores model/version/prediction time/evidence/feature snapshot references; `backtest_runs` stores dataset, code, model, feature, ensemble, calibration, and strategy version fields. There is no dedicated generic feature-values table in the current schema.
- `model_platform.py` exposes one `ModelPrediction` result contract with `ready`, `insufficient_evidence`, and `failed` states. Existing members are Poisson, Dixon-Coles, Elo, de-vig market baseline, LLM adapter, ensemble, and calibrated ensemble.
- The model protocol learns ensemble weights from the train split, fits temperature on validation, and evaluates on test. This satisfies the intended split discipline at the protocol level, but it does not yet establish a persisted, point-in-time Feature Store contract for all production inputs.
- `backtest_engine.py` supports chronological expanding/rolling/walk-forward and comparison/strategy modes, freezes a manifest with dataset/model/feature/calibration/strategy/environment versions, and returns `unavailable` when a complete execution chain is missing.

- `prediction_service.py` prepares recent form, player value, player impact, and model input; it persists evidence and odds snapshots before creating predictions and attaches model/feature/evidence/odds/quality metadata. `prediction_intelligence.py` already exposes `build_feature_snapshot`, but the feature contract is embedded in prediction-oriented utilities rather than an independent versioned feature store.
- `prediction.py` is the production deterministic pre-match path using recent form, lineup, player retention, Elo, Dixon-Coles/Poisson score matrix, handicap/totals outputs, and phase (`preliminary`/`confirmed_lineup`). `market_decision.py` remains a downstream market/EV/uncertainty and action gate.
- Provider search with a PowerShell wildcard (`apps/api/app/*provider.py`) failed with Windows path syntax error; this is only a tooling error and no source changed. Future provider inventory will use explicit paths from `rg --files`.

- `competition_registry.py` defines ten capability dimensions and six competition definitions. The registry itself is authoritative for support status, but the current data constants explicitly mark historical/evaluation/team/lineup/injury support as unavailable or partial for the cup/continental definitions.
- Provider adapters are not yet one common interface: API-Football and TheSportsDB expose fixture/historical/team enrichment paths, ESPN evidence exposes roster/lineup/odds, and Dongqiudi has separate sync/provider paths. A v2 architecture should standardize an envelope plus capability declaration while retaining adapters.
- `build_feature_snapshot` (`prediction_intelligence.py`) is a useful existing feature boundary and rejects future evidence/standings/form/squad/market values relative to a prediction timestamp. Its output has a single `feature_version`, `prediction_timestamp`, `source_captured_at`, and leakage summary, but no per-feature `available_at` map and no persisted feature-value table.
- `recent_form.py` is as-of and decay-aware; `player_impact.py` calculates lineup/availability-dependent contribution and retention, with `data_status`/unresolved counts. These should be promoted into named feature groups with explicit missingness and availability timestamps in the v2 plan.

- `automation.py` defaults to daily fixture/evidence jobs, five-minute lineup polling, and separate standings/analysis/settlement jobs. Optional jobs cover historical accumulation/backfill, ensemble learning, FD research/backfill, ClubeElo, squad backfill, Dongqiudi schedule/scores/pre-match, and notifications.
- Lineup automation only considers future scheduled fixtures within `schedule_lookahead_days`, skips confirmed lineups, uses configured offsets (default `60,30`) plus ten-minute retry throttling, and persists per-window markers under `automation_refresh`. This proves the local scheduler logic, not that a remote process is alive or that every provider returns lineups.
- Analysis automation has explicit prediction windows and re-prediction triggers for confirmed lineups and changed odds; action placement remains downstream of prediction creation. The audit must treat “job ran”, “evidence changed”, “prediction revised”, and “bet executed” as separate observables.
- `main.py` exposes admin job history/forced execution, competition capability, model registry, feature snapshots, basic/advanced backtests, model evaluation, and provider health APIs. These are suitable audit/monitoring surfaces but several legacy endpoints still carry three-league naming.

- Runtime config defaults already include prediction refresh offsets `24,12,6,1,0.5` hours, odds re-prediction every 15 minutes, lineup/evidence lookahead and Dongqiudi pre-match refresh settings, plus hourly/weekly historical and ensemble jobs. These settings should be treated as current operating policy and audited against actual job-run evidence before changing.
- Tests cover the most important existing contracts: append-only evidence, multiple odds captures, prediction immutability/freeze, no market mutation of pure forecasts, model readiness/schema failures, learned weights, temporal split/calibration, deterministic manifests, and strategy `unavailable` behavior for missing execution links.

## Source-plan acceptance boundaries

- The source plan's MVP is limited to Elo, xG, rolling form, home/away, rest/fatigue, player availability, odds normalization, Poisson/Dixon-Coles, XGBoost, calibration, ensemble, and temporal backtest. LightGBM, sequence models, tactical/weather/referee/scenario/SHAP work, and live prediction are explicitly later phases.
- The prediction contract must keep probability, market-implied probability, edge, and decision separate; a decision score must not rewrite the underlying probability.
- Prediction revisions must retain each pre-match snapshot (including lineup/odds changes), and kickoff must freeze the pre-match record; live predictions, if later added, must be separate records.
- New models may affect production only after rolling backtest, calibration, and market benchmark gates; model/feature registry and experiment provenance are required for reproducibility.

## Existing architecture alignment

- `docs/00_CURRENT_BASELINE.md` records P0-P17 as implemented and explicitly lists current debt: league-centric backend, incomplete provider capability unification, three-competition evaluation/backtest semantics, fixed-three-league UI, oversized `FixtureWorkspace`, admin/workspace coupling, and frontend/backend capability drift.
- `docs/02_SYSTEM_ARCHITECTURE.md` already defines Frontend -> API -> Domain/Service -> Repository -> Database, provider/scheduler/historical/prediction/evaluation cross-cutting layers, and the Adapter -> Canonical -> Dual Read/Write -> Verification -> Deprecation migration pattern.
- `docs/03_DATA_ARCHITECTURE.md` and `docs/DATA_LEAKAGE_POLICY.md` already state Raw -> Normalized -> Canonical -> Snapshot -> Feature -> Prediction -> Evaluation, immutable point-in-time provenance, `prediction_timestamp < kickoff`, `captured_at <= prediction_timestamp`, and as-of recent form. These are baseline contracts to preserve and strengthen with field-level timestamps.
- `docs/07_DATABASE_ARCHITECTURE.md` names generic `features`/`fixture_snapshots` concepts, but the actual `database.py` schema currently lacks a dedicated feature-values table. The deliverable must distinguish conceptual documentation from deployed schema.
- `docs/08_BACKTEST_ARCHITECTURE.md` promises chronological/walk-forward/rolling/expanding/cross-competition and ROI only with a complete execution chain; current P12 code covers the main temporal modes, while legacy three-league API semantics remain a cleanup item.

## Deliverable review

- `docs/AI_AUDIT.md` was self-reviewed for scope, contradiction, and formatting. It contains the audit matrix, P0/P1 findings, minimal architecture, provider/feature/prediction contracts, source and feature plan, quality/leakage rules, temporal evaluation protocol, and next implementation order.
- `git diff --check` passed. No business tests were run because this round only added documentation and planning records; no runtime or production deployment state was changed.

## Additional gaps

- `PredictionService._save_current` invokes repository prediction retention after each save. Because the source plan requires preserving every pre-match revision for drift analysis, retention behavior must be reconciled with immutable archival storage before v2 revision history is considered complete.
- Code search finds no XGBoost implementation, no explicit out-of-fold stacking/meta-model path, and no per-feature `available_at` persistence. These are planned gaps, not reasons to add those implementations in round one.

- Retention evidence is definitive: `prune_prediction_history` groups by competition/fixture/model, retains only the latest prediction compatible with the current prompt version, and deletes superseded predictions plus dependent bets, settlements, and unreferenced evidence snapshots. This is operationally useful for a current simulated ledger but conflicts with v2's requirement to retain every pre-match revision; v2 needs an archive/current split or a revised retention policy before drift analysis can be trusted.
