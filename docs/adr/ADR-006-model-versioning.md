# ADR-006 Model Versioning

## Status
Accepted

## Decision
Model、Feature、Calibration 独立版本化，并保存 dataset fingerprint、training cutoff、artifact hash。

## Consequence
可复现和审计；模型升级需要明确 version transition。