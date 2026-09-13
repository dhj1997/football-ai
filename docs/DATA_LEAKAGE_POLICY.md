# Data Leakage Policy

硬约束：`prediction_timestamp < kickoff`；`captured_at <= prediction_timestamp`。

禁止赛后结果、赛后阵容、赛后赔率、赛后状态、未来新闻、当前数据重算历史预测。

Recent Form：as_of 前最近 15 场 finished + complete score。

确认泄漏时必须冻结受影响 prediction/evaluation，保留证据并重新评价。