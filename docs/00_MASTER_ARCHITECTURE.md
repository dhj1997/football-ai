# Football AI Master Architecture v1.0

## 产品定位
Football AI 是可追溯、可解释、可回测、可持续研究的足球 AI 研究平台。核心问题：**为什么 AI 这么判断这场比赛？**

## 非谈判原则
1. `prediction_timestamp < kickoff`
2. `captured_at <= prediction_timestamp`
3. Prediction、Market Decision、Execution 分离
4. 历史预测不得使用当前数据重算
5. 模型失败不得冒充其他模型
6. Recent Form 固定为 as_of 前最近 15 场 finished + complete score
7. 不伪造数据、赔率、阵容、指标或样本
8. Model、Feature、Calibration、Evidence、Prediction 全部版本化

## P0-P17
P0 Prediction Integrity → P1 Core Architecture → P2 Portfolio/Risk → P3 Prediction Intelligence → P4 Historical Validation → P5 Historical Data Platform → P6 Model Evaluation → P7 Historical Prediction → P8 Six Competitions + Frontend V2 → P9 Provider/Data Quality → P10 AI Model V2 → P11 Market Intelligence → P12 Advanced Backtesting → P13 Explainable AI → P14 Automated Research → P15 Production → P16 Observability → P17 Football AI Platform。

## 六赛事
CSL、CFA Cup、EPL、La Liga、UCL、ACL。

核心对象从 League 演进为 Competition，并区分 `league / knockout / continental`。不能简单把 `SUPPORTED_LEAGUES` 从 3 扩成 6。

## 数据闭环
Raw → Normalized → Canonical → Snapshot → Feature → Prediction → Evaluation。

## 产品闭环
赛程 → 比赛详情 → AI 最终结论 → 证据 → 模型 → 市场 → 历史复盘。

## Codex
项目是 Brownfield。P0-P7 为 Protected Baseline。每个 Phase 必须先 audit、再 plan、再 implementation、再 tests、再 acceptance。