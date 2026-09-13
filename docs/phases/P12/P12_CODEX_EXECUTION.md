# P12 Codex Execution

1. Freeze P6 evaluation contract.
2. Add BacktestRun manifest.
3. Implement expanding/rolling/walk-forward splitters.
4. Reuse historical snapshot/recent-form services.
5. Add strategy simulator only when odds/settlement chain is complete.
6. Add bootstrap/uncertainty.
7. Add benchmark comparison.
8. Expose API and performance UI.

Never mutate old run results. A new algorithm or dataset creates a new run/version. ROI must be unavailable rather than fabricated when execution data is incomplete.
