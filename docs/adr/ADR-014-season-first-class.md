# ADR-014 Season First-Class + Extension Test Kit

## Status
Accepted

## Decision
Season 是一等对象：canonical fixture 记录携带 `season_id`；`season_scope()` 按赛事 season policy 显式绑定赛季或声明 global scope；历史 snapshot 的 season 绑定状态通过 `audit_season_binding` 可查询（未绑定赛季的行显式归为 global scope，不补造）。扩展测试套件（platform_kit）覆盖 capability schema、provider provenance、模型契约与 point-in-time/leakage 不变量。

## Consequence
跨赛季 team identity 仍经 canonical team identity 映射（P9）；历史语义保持 point-in-time 不变量；新增赛事/模型必须通过 kit 校验。
