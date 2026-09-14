# ADR-015 LLM Probability Shrinkage

## Status
Accepted

## Context
近 48h 生产复盘（2026-09-12/13，15 注）显示：账面 ROI +11% 但命中率 33%、Brier 0.715（差于随机基线 0.667）、CLV 均值 ≈0。LLM 概率存在系统性过度自信，直接与市场概率比 edge 会高估优势。P2 已有先例：薄 xG 基线按 0.35 权重向市场先验收缩后才进入候选。

## Decision
组合层（bankroll/portfolio）在计算 LLM 模型候选 edge 时，对 LLM 概率做向去水市场概率的固定权重收缩：

```
p_shrunk = w * p_llm + (1 - w) * p_market_devig   （w = 0.7，市场缺失时 w = 1 原样）
```

约束：
1. 收缩只发生在**组合候选评分**这一规定输入位；预测 payload 的冻结概率不改（P0 分离）。
2. 市场概率必须来自该预测绑定的 odds snapshot（point-in-time），缺失时原样通过。
3. w 固定 0.7 起步，调整必须走新 ADR；不得用近期盈亏动态调 w（避免过拟合近期样本）。
4. 展示层标注 `shrinkage_applied`，让 edge 数字可解释。

## Consequence
LLM 极端概率被市场拉回，edge 更保守——预期减少负 CLV 下注；真实 LLM 优势如果存在仍会保留 70% 权重。效果由两周后的 confirmatory ResearchRun 验证（对比收缩前后 Brier/ROI）。
