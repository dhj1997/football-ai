# 懂球帝首发回退链设计

## 目标

在不改变现有定时任务、预测或下注门禁的前提下，为首发刷新增加懂球帝数据源，覆盖没有 API-Football/ESPN 外部 ID 或前两者不可用的比赛。

## 方案

- `DongqiudiProvider.fetch_lineup` 调用懂球帝公开接口
  `/soccer/biz/dqd/v1/match/lineup/{match_id}`。
- `EvidenceProviderChain.fetch_lineup` 保持顺序：API-Football -> ESPN -> 懂球帝；未确认结果继续尝试下一来源，确认结果立即返回。
- 懂球帝 `persons.team_A/team_B.lineups` 映射为首发，`sub` 映射为替补，`formation` 映射为阵型。
- 只有双方真实 `lineups` 都非空时才返回 `confirmed=true`；`forecasts` 永远不作为已确认首发。
- 球员名称经过 `to_chinese_player_name`，保留懂球帝球员 ID、号码和位置。

## 错误与重试

单个 provider 的异常记录在 `provider_failures`，链路继续尝试下一个 provider。懂球帝没有比赛 ID 时抛出受控错误；接口为空或未公布首发时返回未确认结果，由现有 5 分钟轮询重试。

## 验证

增加懂球帝 payload 映射和未确认状态测试，并验证 API-Football/ESPN 失败后能回退到懂球帝。现有赔率快照和执行逻辑不在本次范围内。
