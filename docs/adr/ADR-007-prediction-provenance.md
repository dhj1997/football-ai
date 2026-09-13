# ADR-007 Prediction Provenance

## Status
Accepted

## Decision
Prediction 必须保存 prediction_timestamp、data_cutoff、model_version、feature_version、calibration_version、evidence/readiness、odds snapshot。

## Consequence
每次预测可以解释“当时为什么这么判断”。