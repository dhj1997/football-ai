# Data Architecture

Raw → Normalized → Canonical → Snapshot → Feature → Prediction → Evaluation。

Raw：provider、captured_at、payload/hash、status。
Canonical：统一 Competition、Season、Team、Fixture。
Snapshot：point-in-time。
Feature：version + as_of。
Prediction：model_version、feature_version、prediction_timestamp、data_cutoff。
Evaluation：固定 dataset fingerprint。

所有历史计算必须能够回答“当时系统知道什么”。