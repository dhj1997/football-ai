# P17 Phase Report — Football AI Platform

日期：2026-09-13。分支：`main`。

## Audit 结论

P8-P16 契约审计（本任务 P9-P16 实施过程中逐 phase 完成）：competition/capability（P9）、model registry/统一接口（P10）、market 研究层（P11）、回测协议（P12）、解释图（P13）、研究流水线（P14）、生产门禁（P15）、可观测性（P16）均已独立成模块且各自有契约测试。缺失项：扩展测试套件（新赛事/新 provider/新模型的机械校验）、season 一等对象、平台边界图 API、ADR 与发布清单沉淀。

## Changed files

- 新增 `apps/api/app/platform_kit.py`：
  - `validate_competition_definition`：任何新赛事必须是 CompetitionDefinition（key 规范、类型/season policy/能力全集、provider key 形态）。
  - `validate_provider_adapter`：capability contract——declared supported 必须有实现方法；fixture provider 必须声明 SOURCE_NAME（provenance）；静态检查不触网。
  - `validate_model_adapter`：统一模型契约——空 context 必须 not_ready/failed（fabrication 即违规）、概率和为 1、ready 必须带 provenance。
  - `audit_point_in_time`：snapshot 必须有 as_of + canonical identity 且 created_at == as_of（重建幂等）。
  - `audit_season_binding` + `season_scope`：season 一等对象——历史行显式绑定 season 或声明 global scope，不补造。
  - `DOMAIN_MAP`/`PRODUCT_SURFACES`：模块所有权与产品面导航。
- `apps/api/app/main.py`：`GET /api/platform`（边界图 + season 绑定审计 + 治理规则）。
- 新增 ADR-013（平台整合）、ADR-014（season 一等 + 扩展测试套件）。
- 新增 `docs/RELEASE_CHECKLIST.md`（质量门禁/数据与模型/生产部署/治理四段清单）。
- 测试：`tests/test_p17_platform_kit.py`、`tests/test_p17_api.py`（8 个用例）。

## Compatibility

- 纯 additive：kit 是校验层，不改变任何既有服务；六赛事既有定义全部通过 kit 校验。
- 新赛事扩展示例（world_cup definition）证明无需复制任何业务服务。

## Tests

- 全量 `pytest -q`：459 passed（451 + 8），P0-P16 无回归。
- 覆盖：六赛事定义过 kit、新赛事经 definition + canonical 层直接工作（group stage 正确）、provider 超声明能力被拒、模型伪造输出被拒（fabrication/provenance）、point-in-time 不变量（as_of/canonical/幂等）、season 绑定审计、平台端点契约。

## Integrity / Governance

- provenance 与 point-in-time 仍是平台级不变量（kit 强制）；season 未绑定的历史行显式 global scope，不虚构。
- 架构冻结：ADR-013/ADR-014 + RELEASE_CHECKLIST.md；新语义必须先 ADR。

## Migration / Rollback

- 无 schema 变更；回滚 revert 本 commit。

## Risks / 已知限制

- Provider SDK / Model SDK / Research SDK 以 kit 校验函数 + 既有契约形式落地（函数级标准化）；独立 SDK 包化留待有真实多团队需求时进行。
- season 绑定审计覆盖 P4 historical snapshots（读取上限 200）；P9 canonical 层本身已 season-aware。
