# ADR-008 Provider Abstraction

## Status
Accepted

## Decision
Provider 必须通过 capability matrix 声明 fixture、standings、stage、team、lineup、injury、odds、historical 等能力；Canonical domain 屏蔽供应商差异。

## Consequence
可替换 provider，且不会把未实现能力伪装成可用。