# Findings

## Current State

- P0 already stores immutable `odds_snapshots` as grouped quote rows with `snapshot_id`, `captured_at`, market, selection, line, price, bookmaker, source, and payload.
- Predictions store `odds_snapshot_id`; bets store frozen execution `odds` and optional `handicap_line` in their payload.
- `SettlementService.metrics()` currently reports model forecast scores plus market comparison, but uses legacy names such as `market_prediction_brier`, has no calibration, no CLV, and hardcodes `clv_samples=0`/`average_clv=None`.
- Quality gate currently emits `READY`, `INSUFFICIENT_SAMPLE`, or `QUALITY_FAILED` with `mode` `EXECUTABLE`/`SHADOW_ONLY`; it must gain structured checks and SHADOW/OBSERVATION/VALIDATED states without lowering thresholds.
- The Poisson baseline is nested under each AI prediction's `baseline` payload and can be evaluated as a pseudo-model on the same settlement rows.
- `fixture_settlements` persists one row per prediction and already copies pure `model_probabilities`, de-vig `market_probabilities`, prediction metadata, and bet-linked decision data.
- No frontend changes are required because the P1 output can be additive JSON fields and existing UI is not in scope.

## Design Decisions

- Closing odds are selected per fixture/market/selection/line/bookmaker from odds snapshots with `captured_at < kickoff`, choosing the latest valid capture.
- CLV is stored on settled bet payloads and settlement performance data as `bet_odds / closing_odds - 1`; missing close remains `null` and is excluded from CLV samples.
- Calibration uses 10 bins per outcome (home/draw/away), pure model probabilities only, and returns `ece=null` for zero samples plus `insufficient_sample` below 30 samples.
- Paired comparison is built by intersecting fixture IDs with actual result and required probabilities; absent model rows are excluded from that model's paired set.
- Market metrics use existing de-vig probabilities and are reported separately from model metrics; improvement is `market - model`.
- Poisson metrics are derived from `baseline.probabilities` without adding prediction rows.
