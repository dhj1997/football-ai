# P17 Codex Execution

P17 is platform consolidation, not a rewrite.

1. Audit P8-P16 domain contracts.
2. Stabilize Competition/Provider/Prediction/Market/Provenance interfaces.
3. Introduce shared SDK-style interfaces only where duplication exists.
4. Build platform navigation and module boundaries.
5. Add season-aware domain model.
6. Add extension test kit for new competition/provider/model.
7. Add platform-level API documentation.
8. Freeze architecture through ADRs and release checklist.

A new competition should require only registry + provider + tests unless it truly has new domain semantics. New semantics require an ADR before implementation.
