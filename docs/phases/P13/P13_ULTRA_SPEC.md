# P13 Ultra Specification — Explainable AI

## Goal
回答“为什么 AI 这么判断这场比赛？”时，解释必须可追溯到真实输入，而不是 LLM 事后编故事。

## Explanation graph
`Prediction → Model Output → Feature Snapshot → Evidence → Source/Time`。
每条 reason 至少关联 feature/evidence refs、direction、strength、timestamp、provenance。

## Explanation types
1. Core factors：对概率影响最大的真实特征。
2. Evidence：近期15场、H2H、阵容、伤停、赔率、赛程等实际数据。
3. Model disagreement：Poisson/GPT/DeepSeek/ensemble 差异。
4. Completeness：证据是否完整，哪些缺失。
5. Counterfactual：只有在模型支持并明确标注假设时展示。

## Confidence
解释 confidence 不等于预测 confidence。数据完整度、模型一致性、证据质量分别展示。

## Narrative generation
模板/LLM 只能基于 explanation graph 生成自然语言；任何未出现在 graph 的事实禁止加入。

## Provenance UI
显示 prediction timestamp、data cutoff、model version、feature version、evidence count、odds snapshot、leakage status。

## Safety
解释不能反向修改 prediction。解释失败不应导致预测失败；应退化为结构化 reasons/provenance。
