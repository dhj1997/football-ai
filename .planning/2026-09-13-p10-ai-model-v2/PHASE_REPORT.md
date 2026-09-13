# P10 Phase Report — AI Model V2 (Model Platform)

日期：2026-09-13。分支：`main`。

## Audit 结论

- 既有模型资产：Poisson（含 Dixon-Coles 校正，`prediction.py`）、Elo（`elo.py`）、LLM 双模型（`prediction_service` + `PromptContract` schema）、Ensemble/温度校准（`prediction_intelligence`，FEATURE/ENSEMBLE/CALIBRATION 三版本独立）。
- 缺失：模型产物注册表（版本/状态/工件哈希）、统一模型接口、显式 failure 语义、train/val/test 纪律的协议执行器、champion/challenger 晋升门禁。
- P10 以 additive layer 落地，不重写预测链。

## Changed files

- 新增 `apps/api/app/model_registry.py`：`ModelRecord`（model_key/model_version/competition_scope/feature_version/dataset_fingerprint/training_cutoff/calibration_version/artifact_hash/created_at/status）+ 生命周期 `draft→candidate→champion/active→retired`（含非法迁移拒绝）+ `artifact_hash`/`dataset_fingerprint` + `evaluate_promotion`（metric/calibration/stability/leakage 四门禁）+ `ModelRegistry`（注册幂等、artifact 不可变、晋升需证据）。
- 新增 `apps/api/app/model_platform.py`：`ModelPrediction`（probabilities/readiness/failure/provenance，显式 `failed`/`insufficient_evidence`）+ adapters（Baseline 去水市场先验、Elo 先验、Poisson v2、Dixon-Coles v1、LLM 适配器校验 schema 字段失败即 failed、Ensemble、CalibratedEnsemble）+ `learn_ensemble_weights`（仅 train split 逆 Brier）+ `run_model_protocol`（60/20/20 时间序切分；权重=train，温度=validation，指标=test）。
- `apps/api/app/database.py`：新增 `model_registry` 表（PK model_key+model_version，artifact_hash 不可变校验）。
- `apps/api/app/main.py`：`GET /api/models`（families + registry records + champions）、`POST /api/admin/models/{key}/{version}/status`（带 promotion evidence 校验的流转）。
- 测试：`tests/test_p10_model_registry.py`、`test_p10_model_platform.py`、`test_p10_api.py`（29 个用例）。

## Compatibility

- 未修改既有预测/评估 API 契约；P3/P6/P7 历史输出与 `/api/ensemble`、`/api/calibration` 等保持原样。
- LLM 同 relay 的一次性 fallback 重试（`chatgpt_fallback_model`，P0-P8 既有、配置注释明示）未被改动；适配器按实际 `returned_model` 记录 model_version。
- 新表 additive；无数据迁移。

## Tests

- 全量 `pytest -q`：381 passed（352 + 29），无回归。
- 关键验证：同 dataset+version 产出相同 fingerprint/weights（可复现）；权重仅来自 train、校准仅来自 validation（样本不足显式 `calibration_unavailable`，不造指标）；LLM schema 失败显式 failed 且绝不借用其他模型概率；Poisson/DC/Elo/Baseline 概率和为 1 且证据缺失即 not_ready；晋升四门禁逐一验证；非法迁移与未评估晋升被拒绝。

## Integrity / Provenance

- 每个注册产物不可变（artifact_hash 校验）；provenance 保存全部版本引用。
- 模型失败语义显式：`ModelPrediction.failed`/`not_ready`，无静默 fallback 路径。

## Migration / Rollback

- 回滚：revert 本 commit；`model_registry` 表残留无害。

## Risks / 已知限制

- 注册表当前由 admin/评估流程写入；尚未在自动化中批量注册产物（后续 phase 接入）。
- ML family 在 spec 中列出，当前平台以 Poisson/DC/Elo/Baseline/LLM/Ensemble 覆盖；ML adapter 留待有真实训练数据与特征管道的 phase 再加，避免虚构。
- Frontend 未改动。
