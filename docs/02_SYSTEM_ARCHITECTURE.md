# System Architecture

## 分层
Frontend → API → Domain/Service → Repository → Database。

## 横向能力
Provider、Scheduler、Historical Pipeline、Prediction Pipeline、Evaluation Pipeline、Observability。

## Domain
Competition、Season、Stage、Team、Player、Fixture、Lineup、Injury、Market、Evidence、Prediction、Model、Evaluation、Backtest、Portfolio。

## 迁移模式
Adapter → Canonical Domain → Dual Read/Write → Verification → Deprecation。禁止大爆炸重写。