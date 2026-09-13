# P15 Codex Execution

1. Inventory runtime components and dependencies.
2. Add environment config contract.
3. Containerize without changing domain semantics.
4. Add CI quality gates.
5. Version DB migrations and dry-run them.
6. Add backup/restore verification.
7. Add deployment health/smoke checks.
8. Document rollback.

Codex must not embed secrets, modify production history manually, or combine destructive migration with application deployment. Every production-affecting change needs rollback notes.
