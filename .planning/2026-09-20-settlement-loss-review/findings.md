# Findings

## 线上数据

线上 `/api/metrics/predictions` 返回 128 个已结算预测样本，准确率 49.22%，平均 Brier 0.6130，平均 Log Loss 1.0308。模拟账户的近期亏损并非单纯界面问题：DeepSeek 账户 6 笔已结算下注仅 1 胜 5 负，ChatGPT 35 笔 14 胜 21 负。

## 代码证据

- `apps/api/app/settlement.py` 在 `settle_fixture()` 中读取 `current_predictions_for_fixture()`，随后只对这些预测查找下注并结算。
- `apps/api/app/database.py` 的 `current_predictions_for_fixture()` 按模型分组后取最新一条，因此旧预测绑定的开放下注被排除。
- `apps/api/app/bankroll.py` 的候选执行路径调用 `_complete_candidate_decision()`，该函数只刷新 `market_assessment`；`build_candidates()` 不检查预测冻结的 `decision.status` 或 `reason_codes`。
- 生产下注记录中出现 `stale_odds`、`missing_player_data`、`ai_unavailable`、`low_confidence` 等原因码，说明候选执行边界与预测决策边界存在不一致，需要用回归测试锁定。

## 实施与线上结果

- 用户选择继续自动模拟下注；已有开放下注不直接取消。
- 最终 GitHub/local `main` 为 `591caab`，生产三个修复文件哈希一致，API/Web 服务 active，公开健康 HTTP 200 且数据库为 MySQL。
- 诺丁汉森林 vs 考文垂目标单已按 0:1 结算为 `full_loss`，本金和净亏损均为 `90.97`；重复结算保持幂等，账本只有一笔 `stake` 和一笔 `return`。
- 生产修复进程于 20:19:33 CST 启动；此后没有新增下注，因此目前未观察到新的冻结决策绕过。
- 当前 3 笔开放单中，拉科鲁尼亚 vs 皇家贝蒂斯、比利亚雷亚尔 vs 莱万特的预测状态为 `bet` 且无阻断原因码；斯图加特 vs 维京是 9 月 9 日遗留单，预测为 `no_bet` 且包含 `stale_odds`、`missing_player_data`、`ai_unavailable`、`low_confidence`，赛程仍错误地是 `scheduled`。

## 最新表现复盘

- 原始结算账本：46 笔，16 胜 30 负，投注额 `4392.75`，盈亏 `-1156.13`，ROI `-26.32%`。
- ChatGPT：38 笔，15 胜 23 负，盈亏 `-370.01`，ROI `-10.63%`。
- DeepSeek：8 笔，1 胜 7 负，盈亏 `-786.12`，ROI `-86.34%`。
- 9 月 15 日以来：16 笔，7 胜 9 负，盈亏 `-423.70`，ROI `-27.40%`。
- 6 笔带冻结阻断原因码的历史单中，5 笔已结算全负，另 1 笔仍开放；已结算亏损 `-500`。执行边界缺陷造成了确定性不应发生的亏损。
- ChatGPT 104 个预测样本，Brier `0.6091`，质量闸门 `QUALITY_FAILED`；DeepSeek 25 个样本，Brier `0.6533`，质量闸门 `INSUFFICIENT_SAMPLE`。样本仍小且被执行缺陷污染，不应据此调权。

## 下一阶段初步调查

- 现有 `DongqiudiSyncService.sync_scores()` 已负责把懂球帝的 live/finished 状态和比分写回缓存；需要确认它的日期扫描窗口为何遗漏 9 月 9 日长期 `scheduled` 记录。
- 自动化已有独立 `dongqiudi_scores` 五分钟任务和 `settlement` 十五分钟任务，修复应复用这条链路，不新增调度器。
- API-Football 适配器也能返回完场比分，但生产主赛程源为 TheSportsDB、免费懂球帝源已启用；回退策略必须依据现有身份映射，不能按队名猜测或硬编码斯图加特这一场。
- `BankrollService.summary()` 的回撤计算已显式传入 `self.initial_bankroll`，但返回的 `equity_curve` 调用遗漏第三个参数，导致配置为 5000 时曲线仍从 1000 起步；这是独立的一行修复并需补非默认资金测试。
- 2026-09-20 实时读取懂球帝公开详情确认 `dongqiudi-54577422` 已是 `finished/Played`，比分斯图加特 3:1 维京；生产缓存也有这条正确完场记录。
- 旧开放下注仍绑定另一条 `scheduled` 赛程，因此问题还包含跨来源重复赛程未把赛果传播到承载预测/下注的主记录，不能只扩大日期窗口。
- 精确查询确认旧单绑定 `sportsdb-2594578`，该记录已带 `external_ids.dongqiudi=54577422`；无需新增身份映射，只需让比分任务对过期 `scheduled` 记录继续调用现有 `match_result()`。
- 现有去重函数已经有斯图加特/维京的中英文别名回归测试，并会保留主赛程 ID、优先 live/finished 结果；当前持久化缺口来自 `sync_scores()` 仅筛选“昨天至未来窗口”。

## 陈旧赛果恢复结果

- 生产受保护 `dongqiudi_scores` 任务成功：12 个陈旧恢复候选，匹配 28 场、更新 13 场、错误 0。
- `sportsdb-2594578` 已通过懂球帝比赛 ID `54577422` 更新为 `finished/Played`，比分斯图加特 3:1 维京，`result_source=dongqiudi`。
- 正式结算把下注 `c6ac163b-2799-481d-8a86-5dcad1d22b56` 更新为 `settled/full_loss`，净亏损 `-100`，执行状态 `SETTLED`。
- 首次结算后账本恰好一笔 `stake=-100` 和一笔 `return=0`；已重复运行正式结算，待最终只读核对流水数量和结算时间不变。
- 重复结算后 `settled_at`、stake 和 return 均未变化，幂等验证通过。
- 两个生产模拟账户的配置初始资金和资金曲线起点均为 5000，曲线展示修复生效。
- 当前 2 笔开放单的预测状态均为 `bet` 且 `reason_codes=[]`；部署后未产生新的冻结下注。
