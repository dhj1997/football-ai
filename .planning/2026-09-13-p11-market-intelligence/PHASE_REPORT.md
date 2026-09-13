# P11 Phase Report — Market Intelligence

日期：2026-09-13。分支：`main`。

## Audit 结论

- 已有：`odds_snapshots` 表（append-only、source/captured_at、内容哈希 id）；`select_closing_odds`/`classify_odds_timeline`（as-of 安全）；settlement 的 `calculate_clv`（bet/close-1，closing 严格早于 kickoff）；P0/P2 prediction/market decision 分离。
- 缺失：统一报价规范化与 invalid 标记、单快照去水（overround）+ 市场共识/离散度、按 selection 的赔率时间线与 cutoff 语义、model-vs-market 研究信号、带 reason 的 CLV、市场快照持久化与查询 API。

## Changed files

- 新增 `apps/api/app/market_intelligence.py`：`normalize_quote`（无效赔率标记不丢弃）、`devig_market`（同一 snapshot 内 selections 计算 overround；margin ≤ 0 标记 invalid）、`build_market_snapshots`（按 snapshot+bookmaker+captured 分组，cutoff 过滤）、`market_consensus`（跨庄家中位数共识 + 离散度）、`build_odds_timeline`（按 selection 时间线：opening/current/closing、绝对/相对变化、方向、post_cutoff 标记仅供赛后研究）、`model_vs_market`（edge = 模型 − 去水市场概率，role=research_signal，无执行语义）、`compute_clv_with_reason`（缺 closing/时间语义不明 → null+reason）、`MarketIntelligenceService`（report + 幂等持久化）。
- `apps/api/app/database.py`：新增 `market_snapshots` 表（内容哈希 id 幂等）+ 读写；**修复** `save_odds_snapshot` 不可变校验的顺序敏感 bug（报价按内容排序比较；原实现按 `ORDER BY id` 回读顺序与传入顺序直接比较，同 id 重放合法快照会被误拒）。
- `apps/api/app/main.py`：`GET /api/fixtures/{id}/market`（时间线/共识/分歧/CLV，全部带 source 与 captured_at）、`POST /api/admin/fixtures/{id}/market-snapshot`（幂等持久化）。
- 测试：`tests/test_p11_market_intelligence.py`、`tests/test_p11_api.py`（15 个用例）。

## Compatibility

- 未修改既有市场决策/下注/结算契约；edge 仅输出为 research_signal，不进入 bet qualification。
- `save_odds_snapshot` 修复只放宽误拒（合法重放不再误报），不可变保证不变；dongqiudi 既有调用方行为不变。

## Tests

- 全量 `pytest -q`：396 passed（381 + 15），连续多轮运行稳定。
- 覆盖：去水可复现且保留 margin、异常 margin 标记 invalid 且不进入快照、时间线排序/cutoff 排除/post-kickoff 不作 closing、共识离散度、CLV 四种 null+reason、edge 研究信号无执行字段、服务报告与幂等持久化、API 契约与 admin 鉴权。

## Integrity / Leakage

- 历史研究只用 cutoff 前最后快照；post-cutoff/post-kickoff 报价仅标记 `post_cutoff_research_only`。
- 缺 closing line → null + reason，不补造。
- 原始 odds 快照只读，从不覆盖。

## Migration / Rollback

- 新表 additive；`save_odds_snapshot` 修复可随 commit revert。
- 回滚：revert 本 commit。

## Risks / 已知限制

- UI 展示（timeline/consensus/divergence 面板）未做，本轮交付 API 层；验收项 "API/UI show source and timestamp" 的 API 部分已完成，UI 留待前端 phase。
- `over_under`/`asian_handicap` 的 devig 依赖同一 snapshot 出齐两个 selection；dongqiudi 数据形态满足。
