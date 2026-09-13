# ADR-013 Platform Consolidation

## Status
Accepted

## Decision
P0-P16 的领域模块保持独立边界，通过 `apps/api/app/platform_kit.py` 的扩展契约（capability、provenance、leakage 检查）实现平台整合。新增赛事 = CompetitionDefinition + provider adapter + kit 校验；新增 provider 实现 capability contract；新增模型实现统一 ModelPrediction contract。禁止复制业务服务，禁止以 League 作为所有赛事根对象。

## Consequence
扩展不修改 prediction domain；新语义必须先有 ADR。领域边界图通过 `GET /api/platform` 暴露。
