# P10 Codex Execution

直接 main；先读 P3/P6/P7/P8/P9，不重写预测链。

1. ModelRegistry/domain types。
2. Artifact/provenance persistence。
3. Unified model interface。
4. Poisson/Elo/Dixon-Coles adapters。
5. Structured LLM adapters。
6. Ensemble + calibration。
7. Champion/Challenger evaluator。
8. Evaluation/API/UI integration。

每一步先写 unit/integration tests，再替换调用方。模型失败必须显式失败；不得用其他模型冒充成功。

Required audit：dataset fingerprint、cutoff、feature version、model version、calibration version、artifact hash。
