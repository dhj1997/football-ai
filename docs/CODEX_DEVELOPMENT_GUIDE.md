# Codex Development Guide

## 每个任务
1. 阅读 Master Architecture
2. 阅读 Current Baseline
3. 阅读相关 ADR
4. 检查真实代码与 git status
5. 输出 audit + implementation plan
6. 最小改动实施
7. Unit / Integration / Regression
8. Lint / Build
9. Data Quality
10. Leakage Audit
11. Acceptance
12. 更新 Baseline

## Brownfield
P0-P7 是 Protected Baseline。禁止把项目当 Greenfield 重写。

## 禁止
删除历史数据、伪造数据、伪造指标、关闭测试、模型失败冒充成功、为了 UI 制造虚假数据。