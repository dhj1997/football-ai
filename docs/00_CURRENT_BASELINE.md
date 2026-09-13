# Current Baseline

## 已完成
P0-P7.4 已建立 Prediction Integrity、Portfolio/Risk、Prediction Intelligence、Historical Validation、Historical Data、Model Evaluation、Recent Form、Historical Prediction、Historical Accumulation。

P9 已建立 Competition Registry（六赛事 capability matrix）、canonical fixture/stage contract、数据质量规则引擎（freshness/completeness/conflict 分列可查询）、provider reliability 聚合与 `/api/admin/provider-health`、`/api/competitions`。

P10 已建立 Model Registry（版本化产物 + draft/candidate/champion/retired 生命周期 + 四门禁晋升）、统一模型接口（Baseline/Elo/Poisson/Dixon-Coles/LLM/Ensemble/CalibratedEnsemble，显式 readiness/failure）、train/validation/test 协议执行器与 `GET /api/models`。

P11-P17 已建立：市场智能层（P11 赔率时间线/去水共识/CLV）、可复现回测引擎（P12 六模式 + manifest）、有据解释图（P13）、自动研究引擎（P14 幂等 ResearchRun）、生产门禁（P15 环境契约/版本化迁移/备份验证/CI）、可观测性（P16 关联ID/脱敏日志/SLO/告警）、平台整合（P17 扩展测试套件 + season 一等对象 + ADR-013/014 + 发布清单）。

## 历史数据基线
- CSL：100 fixtures
- EPL：79 fixtures
- La Liga：100 fixtures
- Total：279 fixtures

历史预测：Poisson 251、GPT 251、DeepSeek 163、Total 665；三模型完整 fixtures：163。

## Recent Form
最近 15 场 finished + complete score，严格按 as_of 排序。

## 当前主要债务
- Backend 部分仍 League-centric
- Provider capability 未完全统一
- LeagueSync 假设 standings
- Evaluation 主要围绕三赛事
- Backtest 仍有 three-leagues 语义
- Standings UI 固定三联赛
- FixtureWorkspace 过大
- Admin 与用户工作区耦合
- Frontend 六赛事类型与 Backend 真实能力不完全一致

## P8 保护范围
不得破坏 P0-P7 的历史数据、prediction provenance、as_of、leakage guarantees、模型评价语义。