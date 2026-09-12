# 根因调查记录

## 生产数据 (mysql dual-model-v1, 2026-09-10 只读查询)

- predictions 75 (preliminary 69 / confirmed_lineup 6);decision: bet 18 / no_bet 49 / insufficient_data 8
- reason_codes: missing_player_data 33, stale_odds 31, low_confidence 29, ai_unavailable 19, negative_edge 18, no_matching_market 8
- data_completeness: median=0.714 (=5/7),45/75 ≥ 0.70 → 0.70 门槛卡在 5/7 悬崖下
- market rows 137: edge median 0.002 但 34% ≥ 0.05;EV max 18.278,12% ≥ 0.7 → 配对/校准异常
- bets: placed 4 + settled 14;settled 3 胜 11 负,staked 1356.22,pnl -785.00,ROI -0.579

## 根因

R1 垃圾注通过全部门槛:
- 案例: 1x2 away @41.0,chatgpt probs {home .278, draw .252, away .470} vs 市场 2.4%,edge .447 EV 18.28 → 下注 100,全损
- market_decision 只有下限 (MIN_EXPECTED_EDGE=0.03),无合理性上限
- model_disagreement 参数存在 (market_decision.py:39) 但 prediction_service.py:158/205、main.py:930/1459 均未传入(死参数,仅测试传过)

R2 CLV 恒为 0:
- sportsdb-2494014 (ESPN 源): 15 条报价全部集中在 11:12:58–11:14:03 同一分钟窗,价格完全相同 → closing==bet
- 懂球帝系比赛 (dongqiudi-*): 07:15→07:47 多次捕获,价格 4.1→4.3 移动,CLV 链路通
- 结论: 只影响 ESPN 遗留源,非代码 bug

R3 结算链路: 正常。settlement_result/net_profit/actual_outcome 均在,初期探测用错字段名导致误判。

## 关键代码位置

- market_decision.py:12-16 常量; 36-115 apply_market_decision; 244-266 _market_row (含 edge/ev 字段)
- portfolio.py:134-164 PortfolioConfig; 319-333 is_candidate_eligible
- bankroll.py:203-282 execution_for_prediction (portfolio_filter 文案 :241)
- prediction_service.py:498-514 _data_completeness (7 字段含 lineup)
- database.py:1766-1802 closing_odds_for_bet; 3084-3177 settle_bet (无 closing fallback,正常)
- fixture-workspace.tsx:692-706 executionStatusLabel
