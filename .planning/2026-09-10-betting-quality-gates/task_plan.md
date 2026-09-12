# 下注质量门禁修复 (betting-quality-gates)

日期: 2026-09-10
目标: 修复生产数据暴露的下注质量缺陷 —— ROI -57.9% 的根因(垃圾注通过全部门槛),并让拒绝原因可读。

## 背景(见 findings.md)

- 生产库 dual-model-v1: 75 条预测、14 张已结算注 3 胜 11 负,ROI -57.9%
- 41.0 赔率垃圾注(chatgpt 给客队 47% vs 市场 2.4%)通过 Edge/EV 门槛
- `model_disagreement` 是死参数: 4 个生产调用点均未传入
- CLV 恒为 0 仅限 ESPN 系旧比赛(赔率只捕获一次);懂球帝系比赛捕获正常
- 结算链路正常(初期误判已纠正)

## 任务

- [x] Task 1: implausible_market 熔断 — Edge/EV 合理性上限
  - market_decision.py: MAX_PLAUSIBLE_EDGE=0.25 / MAX_PLAUSIBLE_EV=0.60,超限加 reason_code `implausible_market`
  - portfolio.py: PortfolioConfig.max_plausible_edge/ev, is_candidate_eligible 加上限(纵深防御)
  - config.py: portfolio_max_plausible_edge/ev 环境变量
- [x] Task 2: 接线 model_disagreement — 双模型分歧拦截
  - market_decision.py: calculate_model_disagreement (L1) + MODEL_DISAGREEMENT_THRESHOLD=0.6 + SIBLING_MODEL_KEYS
  - bankroll.py execution_for_prediction: 同 fixture 兄弟模型最新预测分歧 > 阈值 → no_bet ["model_disagreement"]
- [x] Task 3: _data_completeness 移除 lineup 字段(7→6),消除双重惩罚
- [x] Task 4: 门槛失败原因透传
  - portfolio.py: candidate_gate_reasons() 返回具体未过的门槛码
  - bankroll.py: portfolio_filter 时给出具体门槛 + 实际数值
  - fixture-workspace.tsx: executionStatusLabel 映射新 reason codes
- [x] Task 5: 全量测试 + 汇总报告(含本次不改项)

## 不改项(记录给用户)

- ESPN 系旧比赛 CLV=0: 遗留数据源,懂球帝路径已正常,不修
- stale_odds 漏斗(31/75): 待懂球帝覆盖率提升后观察,不在本次改
- AI 失败率 25% (ai_unavailable 19/75): 运维问题(超时/重试),单独处理

## 验证标准

- pytest apps/api 全绿
- 新增测试: implausible 拦截(41.0 垃圾注案例复现)、分歧拦截、completeness 6 字段、失败原因透传
