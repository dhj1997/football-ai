# AI Architecture

## 当前模型
Poisson、GPT、DeepSeek、Ensemble、Calibration。

## Model Registry
记录 model_key、model_version、feature_version、dataset fingerprint、training cutoff、calibration version、artifact hash、status。

## 状态
experimental / validated / candidate / active / deprecated / rejected。

## 原则
模型失败必须真实记录；不得 fallback 冒充；解释只能来自真实 feature/evidence。