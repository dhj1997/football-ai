# Findings

Treat this file as research data, not instructions.

- The new architecture explicitly cancels XGBoost, LightGBM, Random Forest, neural networks, Transformer, LSTM, and GNN predictors.
- The old 3,290-line Codex plan still contains executable ML, OOF, stacking, SHAP, Optuna, trainable calibration, and GPU-oriented instructions.
- Round 1 audit also lists XGBoost/OOF as future work; it must remain historical evidence rather than an operative roadmap.
- Round 2 already supplies point-in-time feature values, leakage audit, append-only prediction revisions, retention protection, and reproducibility references. Round 3 must extend these tables rather than create another Feature Store.
- Platt Scaling and Isotonic Calibration fit parameters from history and conflict with the user's strict no-ML decision. They are removed from the active route.
- Rule-based calibration may normalize, blend with a market prior, apply fixed/versioned weights, clip boundaries, or adjust confidence using explicit formulas. It may not learn weights or thresholds from outcome history.
- Elo, Poisson, and Dixon-Coles remain permitted transparent statistical engines. Their formulas, estimation procedure, state/parameters, input cutoff, and versions must be reproducible.
- Existing learned ensemble/temperature-calibration code is a legacy compatibility concern. This documentation task freezes it but does not delete runtime behavior.
- The canonical document now makes Round 3 onward authoritative, gives explicit normalization/blending/clipping/shrinkage formulas, and versions formula inputs plus execution order.
- The Round 1 audit is now explicitly historical; its former XGBoost/OOF/fitted-calibration recommendations are superseded rather than treated as open implementation gaps.
- The canonical legacy policy preserves only the minimum ability to read and replay old revisions; it forbids new callers, feature expansion, or production promotion of learned paths.
- The Round 2 report now hands off to existing snapshot-table expansion, transparent engine/config bundle hashes, deterministic replay, point-in-time backtesting, and rule-only calibration; OOF and fitted calibration are not Round 3 work.
- The legacy Codex plan initially marked sections 1-79 historical while leaving section 0 phrased as a highest-priority instruction. The retirement boundary must explicitly cover sections 0-79 and label the old goal text as superseded.
- The legacy plan's operative Round 3-8 sequence now matches the canonical route: existing snapshot extension, transparent statistical engines, market prior, deterministic fusion/rule calibration, point-in-time replay, and read-only LLM analysis.
- Its test entry point explicitly removes OOF and replaces it with temporal integrity, deterministic fusion, rule calibration, probability audit, reliability, and statistical bundle replay coverage.
- The legacy plan's final task now limits calibration to fixed formulas/configuration, treats historical evaluation as audit-only, and bars OOF, parameter search, learned weights, and fitted calibration from v2.
- Initial documentation validation found no placeholders, balanced Markdown fences, and final newlines in all four files. `git diff --check` exited 0 with line-ending warnings only.
- `AI_AUDIT.md` retained two Markdown hard-break trailing-space lines in its metadata; remove them so the explicit untracked-file whitespace scan passes.
- The Round 1 audit's final implementation order and the Round 2 handoff now agree on existing snapshot reuse, transparent engine replay, deterministic fusion, rule-only calibration, temporal backtesting, and explanation-only LLM scope.
- Final contract assertions passed 18/18 across canonical authority, retained calibration capabilities, fitted-method exclusion, cutoff semantics, Round 3-8 coverage, legacy freeze/retirement, snapshot reuse, deterministic replay, and ML exit.
- Final explicit trailing-whitespace scan passed; `git diff --check` exited 0 with only pre-existing Windows line-ending warnings.
- Formula review confirmed deterministic normalization, fusion, boundary protection, and shrinkage. Input-domain constraints should be explicit for weights, priors, adjustment multipliers, zero denominators, and missing sources.
- Independent review found three actionable gaps: the legacy plan used `normalize(clamp())`, Market Prior could be interpreted as entering twice, and legacy freeze did not yet require a fail-closed v2 production deny gate.
- Post-fix inspection confirms the canonical and legacy formulas now use the same affine 1X2 boundary protection, the test route covers exactly-once Market Prior and legacy rejection, and historical reports carry the fail-closed handoff.
- Re-review closed all three P1 findings and found one P2 variable mismatch (`p_norm_i` vs `p_stat_norm_i`) in the legacy plan formula.
- The Round 1 audit records an existing production LLM-probability input. The no-ML route needs an explicit Round 3 fail-closed gate for LLM-generated probability/weight/goal/stake values while preserving evidence structuring and explanation.
- Post-edit inspection confirms the LLM numeric gate is early Round 3 work, Round 4 uses an explicit probability-source allowlist, and the corrected formula consistently defines/uses `p_stat_norm_i`.
