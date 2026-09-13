# P14 Codex Execution

1. Define ResearchRun and hypothesis schema.
2. Reuse existing historical accumulation service.
3. Add job locks/idempotency.
4. Add experiment runner over frozen datasets.
5. Run backtest + leakage audit.
6. Add statistical summary.
7. Generate immutable research report.
8. Add Research UI/Admin history.

Every automated experiment must be reproducible and must preserve the exact dataset/model/feature versions. Scheduler retries cannot duplicate predictions or reports.
