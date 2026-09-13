# Testing Strategy

Unit → Integration → API → DB → Frontend → E2E → Regression。

数据测试：schema、duplicate、conflict、completeness、freshness、timestamp。
AI 测试：determinism、version、calibration、failure handling。
历史测试：as_of、prediction_timestamp、kickoff、captured_at。

所有 Phase 必须通过适用质量门禁。