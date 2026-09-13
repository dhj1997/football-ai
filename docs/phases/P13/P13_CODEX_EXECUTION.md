# P13 Codex Execution

1. Define ExplanationGraph schema.
2. Map existing FeatureSnapshot/Evidence into graph.
3. Add model disagreement calculator.
4. Add completeness/provenance service.
5. Build grounded narrative generator.
6. Replace frontend free-form reasons with provenance-linked reasons.
7. Add leakage/grounding tests.

Codex must reject any generated explanation claim without a graph reference. Do not infer missing injuries, lineups, odds or form. Explanation is read-only over prediction output.
