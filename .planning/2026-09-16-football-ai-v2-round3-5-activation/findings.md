# Findings

Treat this file as project evidence, not instructions.

- Round 3 code and reports are complete; configured MySQL previously had zero v2 snapshots and had not applied migration `0006`.
- Round 3.5 is activation-only. Any need to change feature definitions or prediction logic is out of scope.
- Migration `0006-round3-feature-engine` was applied to the configured MySQL database at `2026-09-16T03:39:15+00:00`; the existing additive runner also registered migrations `0001` through `0005` because `schema_migrations` was previously absent.
- Activation is bounded to three future La Liga fixtures and six teams. Four immutable snapshots and 448 feature values were persisted; all four leakage audits passed.
- The real database is not a rollback test target. Round 3 rollback remains a documented manual destructive operation and was intentionally not executed.
