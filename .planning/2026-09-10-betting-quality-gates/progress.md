# 进度

## 2026-09-11 设计修订:移除双模型分歧门(用户决定)

用户明确指示:下注决策必须单模型独立判断,AI 预测之间不做相互比较。
- 已移除: bankroll.py 分歧拦截块与 _sibling_disagreement;market_decision.py 的 MODEL_DISAGREEMENT_THRESHOLD / SIBLING_MODEL_KEYS / calculate_model_disagreement;前端 executionStatusLabel 的 model_disagreement 分支
- 已固化规则: test_bankroll.py::test_execution_is_single_model_and_ignores_sibling_disagreement(兄弟模型给出完全相反观点也不拦截)
- 保留: apply_market_decision 原有的 model_disagreement 死参数(先于本次工作存在,从未在生产触发;test_stale_odds_..._without_cross_model_disagreement_rule 契约与用户方向一致)
- 结算指标里的双模型对比研究 (_paired_model_comparison 等) 不受影响——研究层对比是双模型实验的目的,只有执行层不比较
- 单模型风险敞口由 implausible_market 熔断(edge/EV 上限)兜底,与模型间状态无关

## 2026-09-10 完成

全部 5 个任务完成,TDD 全程红→绿。

### 改动清单

- app/market_decision.py: MAX_PLAUSIBLE_EDGE=0.25 / MAX_PLAUSIBLE_EV=0.60;implausible_market 拦截;REASON_TEXT 新文案
- app/portfolio.py: PortfolioConfig.max_plausible_edge/ev;candidate_gate_reasons() 逐门槛诊断;is_candidate_eligible 加合理性上限并复用诊断
- app/config.py: portfolio_max_plausible_edge / portfolio_max_plausible_ev (env 可覆盖)
- app/bankroll.py: portfolio_filter 替换为 _candidate_gate_diagnosis 具体门槛 + 实际数值文案
- app/prediction_service.py: _data_completeness 移除 lineup (7→6 字段),消除与 phase/warning 的双重惩罚
- apps/web fixture-workspace.tsx: decisionReasonLabels + executionStatusLabel 新增 reason code 映射
- tests: 新增测试覆盖上述各项

### 验证

- pytest: bankroll/market_decision/p2_portfolio 54 passed;全量 283 passed / 1 failed
- 唯一失败 test_dongqiudi_provider.py 为用户未提交的在制品(HEAD 不存在),与本次改动无关
- test_asian_settlement_is_aggregated_in_metrics 的桩原用 cover=1.0 病态分布,被新熔断正确拦截;已改为合理分布 (cover 0.7),保留测试意图
- web: npx tsc --noEmit 通过

### 不改项

- ESPN 遗留比赛 CLV=0: 懂球帝路径已正常,不修
- stale_odds 漏斗(31/75): 待懂球帝覆盖率提升后观察
- AI 失败率 25%: 运维问题(超时/重试),单独处理
- 阈值维持 5%/5%: 待熔断生效积累真实 CLV 后再评估是否降至 3–4%
