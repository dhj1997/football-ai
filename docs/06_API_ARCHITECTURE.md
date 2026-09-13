# API Architecture

## Domain APIs
`/api/competitions` `/api/seasons` `/api/fixtures` `/api/fixtures/{id}` `/api/teams` `/api/predictions` `/api/models` `/api/evaluations` `/api/backtest` `/api/evidence`

## Admin
`/api/admin/*`

## Migration
`/api/backtest/three-leagues` → `/api/backtest`。

## Evaluation
GLOBAL + competition。样本不足：`status=insufficient_sample`，metrics=null。

API 必须围绕 Domain，而不是围绕单个页面。