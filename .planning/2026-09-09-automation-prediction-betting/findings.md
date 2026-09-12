# 研究发现

- `AutomationRunner._refresh_lineups()` 已实现但未放入 `_jobs`。
- 当前 `AUTOMATION_ANALYSIS_ENABLED=false`，分析任务即使注册也不会运行。
- 当前预测逻辑按最新预测状态判断，不支持五个独立窗口。
- 当前 `BankrollService` 通过 `PortfolioConfig` 按资金比例和暴露上限计算 stake。
- 初始资金 1000 同时存在于 `bankroll.py` 常量、`database.py` 新账户初始化和 `prediction_service.py` 模型输入。
- 运行时 `.env` 和 `.env.example` 的 portfolio stake 配置仍是旧的 1% 值，需要与本次固定下注配置区分开。
