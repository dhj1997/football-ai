# 定时赛程与证据刷新设计

## 背景

当前 FastAPI 进程内已有 `AutomationRunner`，但它的 `fixtures` 任务默认每小时刷新今天前后两天，`analysis` 任务将证据刷新、模型预测和模拟下注耦合在一起，且线上 `AUTOMATION_ANALYSIS_ENABLED=false`。证据链对 API-Football、ESPN 和 TheSportsDB partial 有降级能力，但只有近期状态少于三场时才会主动触发补全，因此历史交锋、伤停和球队信息缺失时不会独立刷新。

目标是把数据采集与模型运行分开，并按固定业务周期维护未来比赛的赛前资料：每天凌晨同步未来七天赛程和基础证据；每场比赛在开赛前 60 分钟、30 分钟各刷新一次首发；所有任务可重启、可重试、可审计且不重复消耗配额。

## 已确认需求

- 每日一次处理未来 7 天比赛。
- 每日任务获取或补齐历史交锋、近期状态、伤停和球队信息。
- 首发在开赛前 60 分钟和 30 分钟各执行一次。
- 首发任务若已确认不再重复；同一时间窗口重启或下一轮调度不重复执行。
- 数据任务不自动触发模型预测或模拟下注。
- 任务按 `Asia/Shanghai`（北京时间）判断日期和开赛窗口。

## 方案与职责

### 1. 赛程任务 `fixtures`

保留现有 `ScheduleSyncService` 和持久化作业记录，将默认刷新间隔改为每天一次，并增加 `schedule_lookahead_days=7` 配置。刷新窗口为当地当天至未来第七天；现有 `lookback_days` 继续用于保留结果回看范围。`replace_fixtures` 的证据/预测保留语义不变，避免每日替换清掉已同步资料。

### 2. 每日证据任务 `evidence`

新增独立自动任务，遍历未来七天内状态为 `scheduled` 的比赛。对每场比赛评估以下字段的完整度和新鲜度：`head_to_head`、`recent_form`、`availability`、`teams`。任一字段缺失，或证据超过 `evidence_refresh_minutes`，才进行刷新。任务复用现有证据合并和玩家中文名本地化逻辑，保留更丰富的旧字段及不可变证据链。

证据获取按现有链路执行：优先 API-Football，失败后 ESPN，最后保存明确标注的 TheSportsDB partial 结果。对于已有供应商证据但只缺 H2H/伤停/球队资料的比赛，允许使用 ESPN/public secondary 刷新，避免无谓消耗 API-Football 配额。每场异常写入该作业的错误摘要，其他比赛继续处理；不调用 `prediction_service` 或 `bankroll_service`。

### 3. 首发任务 `lineup`

新增独立任务，调度器仍按 `automation_tick_seconds` 唤醒（默认 60 秒），只选择距离开赛落在 60 分钟或 30 分钟窗口的 `scheduled` 比赛。窗口按北京时间转换为 UTC 比较，允许一个小的调度容差，避免 tick 未恰好落在整分钟时漏跑。

每场比赛为两个窗口分别维护持久化标记，例如证据上下文中的 `automation_refresh.lineup_60_at` 和 `lineup_30_at`。标记写入前先检查，写入与证据保存使用现有仓储锁/更新路径，保证服务重启和并发循环不会重复调用。首发接口只请求 lineup 数据并与已有证据合并；若供应商返回未确认首发，仍记录该窗口已执行，30 分钟窗口可再次尝试。确认后两个窗口都不再请求。该任务不生成预测、不下注。

为避免完整证据请求重复消耗配额，新增 provider/chain 的 lineup-only 方法：API-Football 只请求比赛详情与 `/fixtures/lineups`；ESPN 只读取事件 summary 的 rosters；不支持 lineup-only 的 TheSportsDB 返回明确不可用结果。已有完整证据字段不得被空 lineup 响应覆盖。

### 4. 模型分析任务 `analysis`

保留当前手动/独立模型流程及其开关，不把 `evidence` 或 `lineup` 任务挂到 `AUTOMATION_ANALYSIS_ENABLED` 下。线上默认仍可关闭自动预测，数据同步开启后不会产生模型调用或模拟下注。

## 调度与幂等

- `fixtures` 和 `evidence` 的默认间隔为 1440 分钟；任务第一次启动会执行，之后按持久化的 `last_job_run.finished_at` 判断是否已完成当天任务。
- 每日任务使用北京时间日期键，避免服务在凌晨前后重启造成同一自然日漏跑或重复跑。若任务失败或 partial，沿用现有失败退避，并允许下一次窗口重试。
- `lineup` 任务使用 5 分钟以内的调度 tick，窗口标记确保每场每窗口最多一次；任务失败不写成功标记，下一轮仍可重试。
- 所有任务通过 `AutomationRunner` 的进程锁串行执行，并记录 `job_runs` 的状态、数量、错误摘要和结果。

## 配置默认值

新增或调整以下环境变量，并同步 `.env.example`、部署配置和运行时文档：

- `SCHEDULE_LOOKAHEAD_DAYS=7`
- `AUTOMATION_FIXTURE_INTERVAL_MINUTES=1440`
- `AUTOMATION_EVIDENCE_INTERVAL_MINUTES=1440`
- `AUTOMATION_LINEUP_INTERVAL_MINUTES=5`
- `LINEUP_REFRESH_OFFSETS_MINUTES=60,30`
- `AUTOMATION_EVIDENCE_REFRESH_LIMIT` 默认改为覆盖每日未来七天的受控批量值，实际并发和单轮上限仍受供应商配额保护。
- `AUTOMATION_ANALYSIS_ENABLED` 保持独立，不因上述任务开启而自动变更。

## 错误与降级

- 单场 API-Football/ESPN 请求失败时记录 provider failure，并继续处理其他比赛。
- TheSportsDB partial 结果明确保留空 H2H、空伤停和未确认首发，不伪造数据；页面显示来源和缺失状态。
- 任务整体无可处理比赛时返回成功且 `item_count=0`，不制造错误告警。
- 不改变已完场比赛的历史回填与结算规则；每日证据任务只处理未来 scheduled 比赛。

## 测试计划

- ScheduleSync：验证未来七天窗口、回看窗口保留、每日间隔和证据字段保留。
- AutomationRunner：验证新 `evidence`/`lineup` 任务注册、每日幂等、失败退避、作业记录和分析任务独立开关。
- Evidence：验证“只缺 H2H/伤停/球队资料”会刷新、“字段均新鲜”跳过、secondary 降级和旧字段合并。
- Lineup：验证 60/30 分钟窗口各执行一次、未确认允许下一个窗口重试、确认后跳过、重启不重复，以及 lineup-only provider 请求边界。
- API/provider：验证 API-Football、ESPN、TheSportsDB partial 的 lineup-only/降级契约。
- 运行最小后端测试集及 Web lint；部署后手动执行一次每日 evidence 与 lineup 作业，检查 `job_runs` 和目标 fixture evidence。

## 不在本次范围

- 不自动生成模型预测或模拟下注。
- 不为历史完场比赛补造缺失 H2H。
- 不引入外部 cron、队列服务或新的数据库表；优先复用现有 JSON fixture/evidence 与 `job_runs` 持久化。
- 不绕过供应商配额，不把 TheSportsDB partial 空字段伪装成真实数据。
