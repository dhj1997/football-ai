# Release Process

Plan → Implement → Test → Data Audit → Leakage Audit → Build → RC → Acceptance → Deploy → Smoke Test。

代码、数据库 migration、模型 artifact 分别考虑回滚。

测试、数据质量或泄漏门禁失败时不得发布。