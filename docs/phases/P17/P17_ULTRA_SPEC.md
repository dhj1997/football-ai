# P17 Ultra Specification — Football AI Platform

## Vision
形成长期可扩展平台：`Data → Feature → Prediction → Explanation → Evaluation → Research → Improvement`。

## Domain boundaries
Competition、Fixture、Team、Stage、Provider、Snapshot、Feature、Prediction、Decision、Market、Evaluation、ResearchRun、Provenance 是核心领域对象。禁止用 League 作为所有赛事的根对象。

## Product surfaces
Research Terminal、Competition Center、Match Center、Team Center、Model Lab、Backtest Lab、Explainability、Research Engine、Data Platform、Admin、Public/Internal API。

## Extensibility
新增赛事应主要通过 CompetitionDefinition + Provider adapters + capability configuration 完成，不复制一套业务服务。新增 provider 不应修改 prediction domain。

## SDK direction
Provider SDK 标准化 capability、schema、health、rate limit、provenance；Model SDK 标准化 predict/evaluate/version/artifact；Research SDK 标准化 dataset/experiment/report。

## Multi-season
Season 成为一等对象；所有 historical snapshot/prediction/evaluation 都绑定 season 或明确 global scope。跨赛季 team identity 必须可映射。

## Platform governance
ADR、versioning、point-in-time、provenance、evaluation gates 作为平台级规则。新模块不能绕过核心 contracts。

## Long-term direction
未来可扩展更多联赛/杯赛、更多数据源、更多模型、研究 notebook/report、权限与多用户，但不提前引入没有真实需求的复杂 tenancy。
