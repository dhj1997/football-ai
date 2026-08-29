# Findings

- `ApiFootballProvider` and `TheSportsDbProvider` already cover the three desired leagues using lowercase internal keys; P5 should add a canonical uppercase registry/adapter without changing existing public API keys.
- `ScheduleSyncService` is current-window oriented and replaces fixtures; P5 needs a separate bounded historical sync service so historical data is never pruned by current refreshes.
- P4 already provides `raw_data_records`, `historical_snapshots`, `HistoricalBackfillService`, and `RollingBacktestService`; P5 should extend these contracts rather than create duplicate snapshot/backtest tables.
- Existing `PredictionRepository` stores raw payloads but raw records do not yet have a payload hash column or sync-run/identity mapping tables.
- Current production database has no odds snapshots and no P5 historical snapshots; P5 must report unavailable data rather than infer it.
