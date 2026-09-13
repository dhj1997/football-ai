# Database Architecture

## 核心实体
competitions、seasons、stages、teams、players、fixtures、fixture_snapshots、odds_snapshots、raw_data_records、historical_snapshots、features、predictions、historical_predictions、model_registry、model_evaluations、backtest_runs、evidence、provider_health、data_quality_reports。

## Migration
Add → Migrate → Backfill → Verify → Deprecate → Remove。

禁止 destructive migration 直接破坏历史数据。