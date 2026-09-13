# P10 Ultra Specification — AI Model V2

## Goal
把现有 Poisson/GPT/DeepSeek/ensemble 从“可运行模型”升级为可注册、可比较、可复现、可回滚的 Model Platform。

## Model Registry
每个 model artifact 必须记录：`model_key`, `model_version`, `competition_scope`, `feature_version`, `dataset_fingerprint`, `training_cutoff`, `calibration_version`, `artifact_hash`, `created_at`, `status`。
状态：`draft → candidate → champion/active → retired`。

## Model families
Baseline、Elo、Poisson、Dixon-Coles、ML、GPT、DeepSeek、Ensemble、Calibrated Ensemble。模型接口统一输出 probabilities、confidence/readiness、provenance，不统一内部算法。

## Ensemble
权重只能由 training split 学习；validation 只做 calibration/model selection；test 只做最终评估。不得用 test 反向调权。

## LLM contract
GPT/DeepSeek 输出结构化 schema：prediction、probabilities、reasons、evidence_refs、uncertainty、model_version。解析失败必须标记 failure，不得静默 fallback。

## Champion / Challenger
Champion 面向生产；Challenger 只 shadow evaluation。Challenger 在固定 dataset 上连续满足 metric、calibration、stability、leakage gates 后才能晋级。

## Versioning
Feature、dataset、model、calibration、prompt/schema 均独立版本；prediction provenance 必须保存全部版本引用。

## Migration
保留 P3/P6/P7 模型输出；新 registry 作为 additive layer。旧 evaluation API 提供兼容结果。任何概率变化必须能解释为 model/data/version 变化。
