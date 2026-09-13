# P12 Phase Report — Advanced Backtesting

日期：2026-09-13。分支：`main`。

## Audit 结论

- 已有：P4 `RollingBacktestService` + `rolling_windows`（滚动窗口、leakage 检查）、P6 实验/指标表、P10 `run_model_protocol`（train/val/test 纪律）与 `learn_ensemble_weights`、`backtest_runs` 表（insert-only 不可变）。
- 缺失：expanding/walk-forward/cross-competition 模式、run manifest（含 seed 与环境指纹）、bootstrap 置信区间、完整执行链门控的策略模拟、naive/market 基准对比、可复现 run 的 API。

## Changed files

- 新增 `apps/api/app/backtest_engine.py`：
  - `expanding_windows`（固定起点、训练窗增长）；rolling 复用 P4 `rolling_windows`；walk_forward 复用 expanding 语义（每窗重拟合）。
  - `run_backtest_engine`：逐窗口从 train 学权重（P10）、test 只做评估；模式 expanding/rolling/walk_forward/cross_competition/model_comparison/strategy。
  - `bootstrap_confidence_interval`（确定性种子、百分位法）；聚合输出 sample_size、ensemble/model/market baseline 的 Brier CI、相对 naive baseline 的 improvement 及 CI。
  - `simulate_strategy`：平注模拟，支持 commission/slippage/void/push；逐场要求 odds+decision+settlement 完整，缺失计数跳过，全缺时 `unavailable`；输出 ROI、equity curve、max drawdown、volatility、max losing streak。
  - `build_manifest`：dataset fingerprint、as_of range、feature/model/calibration/strategy 版本、random seed、params、环境指纹、manifest 指纹（内容哈希）。
- `apps/api/app/main.py`：`POST /api/admin/backtest/runs`（run_id = manifest 指纹 → 相同 manifest 重跑返回既有 run，不可变）。
- 测试：`tests/test_p12_backtest_engine.py`、`tests/test_p12_api.py`（12 个用例）。

## Compatibility

- P4/P6 契约冻结未动：`build_backtest_rows`、`rolling_windows`、`/api/backtest*` 既有 GET 端点原样；引擎是 additive layer。
- `build_backtest_rows` 输出不携带执行链字段，引擎按 fixture_id 合并 `market_odds/decision/settlement_status`，不改动 P6 函数本身。

## Tests

- 全量 `pytest -q`：408 passed（396 + 12）。
- 覆盖：窗口时间序与边界可审计、bootstrap 确定性、策略完整链门控（缺 odds → unavailable + reason）、commission/slippage/push 结算数学、rolling 可复现（同 manifest 同结果）、market baseline 缺数据 honest unavailable、cross-competition 分组覆盖、manifest 冻结全部版本、API 401/400/幂等重跑、旧 run 不可变。

## Integrity / Reproducibility

- 权重仅来自各窗口 train 切片；test 标签不参与选模或调权。
- 无完整执行链的 ROI/策略输出 `unavailable`，不用估算填补。
- run 不可变：同 manifest 重跑返回既有记录；新数据/新参数生成新 manifest 指纹 → 新 run。

## Migration / Rollback

- 无 schema 变更（复用 `backtest_runs`）；回滚 revert 本 commit。

## Risks / 已知限制

- 性能 UI 未做（API 层完成）；CLV 时间锁语义沿用 P0 settlement 的 closing-odds 路径并在 P11 提供 reason 版本。
- cross-competition 模式当前按 league_key 分组，六赛事数据完备后自动扩展。
