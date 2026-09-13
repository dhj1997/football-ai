# P14 Phase Report — Automated Research

日期：2026-09-13。分支：`main`。

## Audit 结论

- 已有：P5/P7 历史积累（HistoricalOOSAccumulationService）、P12 回测引擎与 manifest、P6 样本策略、AutomationRunner 的 job 记录（job_runs）。
- 缺失：ResearchRun（假设/冻结/实验/统计/泄漏/报告/归档流水线）、exploratory vs confirmatory 纪律、强制泄漏审计、幂等调度（锁 + 内容寻址去重）、不可变研究报告与查询 API。

## Changed files

- 新增 `apps/api/app/research_engine.py`：
  - `ResearchRun` 流水线：`Hypothesis → Dataset Freeze → Experiment → Backtest → Statistical Check → Leakage Audit → Report → Archive`，逐阶段留痕；任一失败 run 标 failed/partial，绝不生成成功结论。
  - `validate_hypothesis`：confirmatory 必须预注册 selection rule；hypothesis_id 内容哈希。
  - `leakage_audit`：强制 point-in-time 审计（prediction_created_at ≥ settled_at 即违规），无数据 not_applicable。
  - `_statistical_summary`：P6 样本策略（<30 insufficient / <100 low_confidence / ≥100 adequate）+ bootstrap CI + experiment_count。
  - `build_research_report`：dataset/version/method/metrics/uncertainty/limitations/leakage/conclusion/unanswerable；市场基准或策略链缺失列入"不可回答项"。
  - run_id 内容寻址（排除 created_at）→ 重试/重复提交收敛到同一 run，绝不复制报告。
  - `ResearchScheduler`：per-job asyncio 锁 + 幂等缓存 + 已存储 run 复用。
- `apps/api/app/database.py`：新增 `research_runs` 表（insert-only，status 不可变）+ 读写。
- `apps/api/app/main.py`：`POST /api/admin/research/runs`、`GET /api/research/runs`、`GET /api/research/runs/{run_id}`。
- 测试：`tests/test_p14_research_engine.py`、`tests/test_p14_api.py`（11 个用例）。

## Compatibility

- 复用 P12 `run_backtest_engine` 与 P6 `build_backtest_rows`/样本策略，未修改其契约；历史积累/预测刷新 jobs 未触碰。

## Tests

- 全量 `pytest -q`：429 passed（418 + 11）。
- 覆盖：假设校验（confirmatory 强制 selection rule）、样本策略阈值、泄漏审计（清洁/违规/空数据）、完成 run 的报告完整段落与版本冻结、违规 → failed 且 conclusion=None、run 可复现且旧 run 不可变（新假设 → 新 run）、不足数据不造结论、调度器并发三提交只计算一次且锁内幂等、重试返回 reused、API 401/400/404 与列表详情契约。

## Integrity / Governance

- Research Engine 不绕过 P0-P13：数据集来自 fixture_settlements（P1 结算），实验走 P12 引擎（weights train-only），泄漏审计强制，报告溯源 run_id。
- 重试不复制预测/报告：content-addressed run id + insert-only 存储。

## Migration / Rollback

- 新表 additive；回滚 revert 本 commit。

## Risks / 已知限制

- Research UI（前端历史）未做，API 层完整；调度接入 AutomationRunner 独立 job 留待 P15/P16 运维层。
- experiment_count 当前为单次预注册实验（=1）；多次探索性实验的聚合登记留待后续需求。
