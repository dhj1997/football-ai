# P2 — Portfolio / Risk

## Goal
保持 portfolio-only 资金语义：`cash_balance` 来自 bankroll ledger；`open_exposure` 为全部 active stakes；`equity = cash_balance + open_exposure`。

## Rule
daily/league/total exposure 均基于 active stakes。预测系统与下注资格分离；0.03 仅为上游 decision signal。

## Acceptance
资金账本一致、exposure 一致、无旧 BankrollService 分支回归。