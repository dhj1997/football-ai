# P1 Evaluation Integrity

## Scope

This phase adds CLV, calibration, fair model-versus-market evaluation, and data-backed quality gates on top of the merged P0 architecture. Forecast generation, provider prompts, frontend UI, prediction freeze rules, and core settlement outcomes are unchanged.

## CLV

Closing odds are selected independently for each fixture, market, selection, line, and bookmaker. Only odds snapshots captured before kickoff are eligible, and the latest valid `captured_at` is selected. For decimal odds, `CLV = bet_odds / closing_odds - 1`. CLV is attached to bet/settlement performance data, never to forecast probabilities. Missing closing odds produce `null` and do not count toward `clv_samples`. Asian handicap lines are matched exactly and preserve `line_at_bet`, `line_at_close`, and `line_changed`.

## Calibration and Metrics

Calibration uses pure model probabilities and ten probability bins independently for home, draw, and away. Each bin reports sample count, mean predicted probability, actual frequency, and `actual - predicted` gap. ECE is the weighted absolute gap and is `null` for zero samples; fewer than 30 samples are marked insufficient. Model metrics use pure probabilities, while market metrics use the existing de-vig probabilities. Improvements are `market_metric - model_metric` for Brier, LogLoss, and RPS.

DeepSeek, GPT, and the nested Poisson `baseline` are evaluated on settlement rows. Paired comparisons intersect fixture IDs with actual results and required probabilities, so models are compared only on the same fixtures. Poisson is a reporting pseudo-model and does not create new Prediction rows.

## Quality Gate

The existing thresholds remain authoritative. The gate returns `SHADOW`, `OBSERVATION`, or `VALIDATED` plus structured checks for sample counts, forecast improvement, average CLV, ROI, and drawdown. Sample failures remain observation-only; no automatic model promotion or threshold relaxation is introduced.

## Persistence and Compatibility

Bet and settlement JSON payloads gain additive CLV/closing-odds fields. Existing aliases remain readable, but internal names use `model_brier`, `market_brier`, and `brier_improvement`. Database initialization adds only nullable columns or indexes needed for queryability and remains idempotent on SQLite/MySQL.
