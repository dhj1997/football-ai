# P1 — Core Architecture

## Goal
建立统一 Domain：Competition、Season、Stage、Team、Player、Fixture、Market、Evidence、Prediction、Model、Evaluation、Backtest、Portfolio。

## Rule
Domain-first；Provider 是 Adapter；API 不围绕页面建模；历史数据必须 point-in-time。

## Acceptance
Domain contract 清晰、现有 P0 语义不回归、测试通过。