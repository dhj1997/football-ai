# P13 Phase Report — Explainable AI

日期：2026-09-13。分支：`main`。

## Audit 结论

- 已有：P3 `build_feature_snapshot`（版本化、as-of 特征视图、leakage_check）、P0 不可变 prediction payload（evidence hash/版本引用）、P10 统一模型输出、`assess_data_quality`。
- 缺失：结构化解释图（reason → feature/evidence refs + direction + strength + provenance）、模型分歧量化、证据完整性展示、解释置信度（独立于预测置信度）、有据叙事与校验。

## Changed files

- 新增 `apps/api/app/explainability.py`：
  - `build_explanation_graph`：只读消费 prediction snapshot，产出 `Prediction → Model Output → Feature Snapshot → Evidence → Source/Time` 图；每条 reason 携带 kind（core_factor/evidence/model_disagreement/completeness/counterfactual）、direction、strength、refs、timestamp、provenance。
  - `model_disagreement`：从真实模型输出计算两两差异、逐结果 spread、最大分歧对、总分（≥2 个有效输出才计算）。
  - 证据节点七类（recent_form/h2h/lineup/injuries/odds/schedule/standings），缺失明确标 missing；未来时间戳标 future_rejected。
  - `confidence`：data_completeness / model_consistency / evidence_quality 三项分列，与预测置信度（forecast_confidence）分离展示。
  - counterfactual 显式 `available: False`（模型不支持时不展示）。
  - `grounded_narrative`：每句叙事一一对应 reason id，不引入图外事实；`validate_grounded` 校验引用合法性。
- `apps/api/app/main.py`：`GET /api/fixtures/{fixture_id}/explanation`（从当前版本预测 + 证据重建特征快照，确定性可复现）。
- 测试：`tests/test_p13_explainability.py`、`tests/test_p13_api.py`（10 个用例）。

## Compatibility

- 只读层，无既有端点/契约改动；预测链路零修改（解释失败不影响预测——图构建为纯函数，异常向上抛给 404/500 路径而非改写预测）。

## Tests

- 全量 `pytest -q`：418 passed（408 + 10）。
- 覆盖：分歧从真实输出计算（单模型 → None）、每条 reason 有 refs+provenance、缺失证据显式 missing 且进入 completeness reason、解释置信度与预测置信度分离、叙事完全有据（逐条映射 reason）、反事实显式不可用、解释只读（prediction/evidence 输入不被修改）、leakage_status 透传、API 404 契约。

## Integrity / Safety

- 解释不能反向修改 prediction：`build_explanation_graph` 对输入 deep copy 且不回写。
- 叙事只从图生成；`validate_grounded` 保证无图外声明。
- 不推断缺失伤停/阵容/赔率/状态——缺失即 missing。

## Migration / Rollback

- 无 schema 变更；回滚 revert 本 commit。

## Risks / 已知限制

- 叙事为确定性模板（基于图）；LLM 叙事仅在能引用图节点时才允许，当前未启用 LLM 生成以避免无据声明。
- Provenance UI（前端展示 prediction timestamp/data cutoff/model version/evidence count/odds snapshot/leakage status）留待前端 phase，API 已完整输出上述字段。
