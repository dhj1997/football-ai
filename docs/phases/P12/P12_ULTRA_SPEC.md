# P12 Ultra Specification — Advanced Backtesting

## Goal
将 P6 历史评估升级为可复现的 walk-forward research/backtest engine。

## Modes
- expanding window
- rolling window
- walk-forward
- cross-competition
- model comparison
- strategy backtest

每个 run 固定 dataset fingerprint、competition、as_of range、feature/model/calibration/strategy versions。

## Split semantics
训练只能看到 train cutoff；validation 用于调参/calibration；test 只用于最终报告。时间边界必须可审计，禁止随机打乱时间序列。

## Betting simulation
仅当历史 prediction、odds snapshot、decision、settlement 全链路存在时计算 ROI。支持 stake rule、odds slippage、transaction cost、void/push、commission；缺失数据输出 unavailable，不用估算填补。

## Statistics
除点估计外输出 sample size、bootstrap confidence interval、drawdown、equity curve、volatility、max losing streak。低样本继续遵循 P6 confidence policy。

## Reproducibility
Run manifest 保存代码版本、dataset fingerprint、random seed、参数、environment fingerprint。相同 manifest 应可重建同一结果。

## Benchmark
至少比较 naive baseline、market baseline（若数据完整）、model、ensemble。报告 improvement 与 uncertainty，而不是只展示最佳模型。
