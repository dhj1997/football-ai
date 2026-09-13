# ADR-002 Portfolio Model

## Status
Accepted

## Decision
`equity = cash_balance + open_exposure`。exposure 基于 active stakes；Portfolio 逻辑与 Prediction 解耦。

## Consequence
资金语义一致，可独立回测。