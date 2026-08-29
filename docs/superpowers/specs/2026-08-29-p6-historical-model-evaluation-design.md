# P6 Historical Model Evaluation Design

## Scope

P6 evaluates only already persisted P5/P4 historical records for CSL, EPL, and LAL. It never expands the fixture dataset, calls providers during evaluation, creates synthetic rows, or changes P0-P5 prediction/settlement/portfolio semantics.

## Data flow

`historical snapshots/settlements -> canonical league filter -> kickoff-ordered train/validation/test split -> frozen model inputs -> forecast metrics and leakage audit`.

P3's normalized probabilities and weighted ensemble are reused. Baseline and Poisson are compared directly when present. GPT/DeepSeek are reported as unavailable when frozen historical prediction records are absent. Calibration is fit from train/validation only and tagged with the fit boundary. Test rows are never used to choose weights, calibration, features, or thresholds.

## Persistence and APIs

Two small append-only result tables store deterministic experiment metadata and per-model/per-league metrics. A leakage audit is persisted with the experiment and exposed read-only. The API exposes experiment detail, model comparison, league-scoped evaluation, and the latest audit. Re-running the same experiment id returns the same frozen result.

## Metrics and confidence

Reports contain Brier, LogLoss, RPS, ECE, sample count, confidence and explicit unavailable states. Samples below 30 are `insufficient_sample`; samples below 100 are `low_confidence`. Forecast and betting metrics remain separate. Betting metrics are `unavailable` unless a complete injected virtual-bankroll chain exists.

## Error handling

Malformed timestamps, future captures, unsupported leagues, missing model probabilities, and absent odds are reported as exclusions/unavailable rather than imputed. No production bankroll, bet, execution, or settlement write occurs.

## Testing

Focused tests cover chronological and frozen splits, future-data rejection, calibration/weight boundaries, same test-set model comparison, CSL/EPL/LAL isolation, small samples, deterministic reruns, and virtual betting write isolation. Existing P0-P5 suites remain the regression gate.
