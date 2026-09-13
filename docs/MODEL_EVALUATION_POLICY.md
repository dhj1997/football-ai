# Model Evaluation Policy

指标：Hit Rate、Brier、Log Loss、RPS、ECE、Calibration、CLV、ROI、Drawdown。

样本状态：N < 30 → insufficient_sample；30 ≤ N < 100 → low_confidence；N ≥ 100 → adequate_sample。

模型比较必须使用相同 fixtures、时间窗口、过滤规则和 scoring convention。

不得为不足样本制造指标。