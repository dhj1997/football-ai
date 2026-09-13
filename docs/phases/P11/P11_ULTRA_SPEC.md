# P11 Ultra Specification — Market Intelligence

## Goal
建立严格的赔率时间线与市场研究层，把 market probability、model probability、edge、CLV 分开；市场信息只能进入 prediction/decision 的规定输入位置。

## Odds normalization
统一 bookmaker、market、selection、line、decimal odds、captured_at。每个 snapshot 必须可回溯到 source。去水概率使用同一 market snapshot 内 selections 计算 overround；异常 odds 标记 invalid。

## Market probability
保存 raw implied probability、normalized probability、overround、market consensus。不得把归一化概率当作真实概率而隐藏 bookmaker margin。

## Line movement
按时间排序形成 odds timeline，计算 opening/current/closing、绝对变化、相对变化、方向、market dispersion。历史研究必须使用 cutoff 前最后可用 snapshot。

## Model vs market
`edge = model_probability - normalized_market_probability` 只是 research signal。不得自动转化为 bet qualification；继续沿用 P0/P2 的 prediction/market decision separation。

## CLV
只在 prediction/decision timestamp 与 closing snapshot 均存在且时间语义明确时计算。缺失 closing line 输出 null + reason，不补造。

## API/UI
新增 market timeline、market consensus、model-vs-market divergence、CLV/provenance。UI 必须同时显示 snapshot time 与 market source。

## Historical integrity
禁止使用 kickoff 后赔率作为历史决策输入。任何 late odds 只能用于赛后研究并明确标记 post-cutoff。
