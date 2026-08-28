# 足球 AI 项目生产就绪审查

日期：2026-08-26

## 结论

项目已经不是纯 Demo：真实赛程、积分榜、球队/球员资料、证据快照、双模型、模拟资金、结算、绩效页和持久任务均已存在，80 个 API 测试、前端 ESLint 和生产构建也全部通过。

但它目前仍不适合对外宣称“AI 预测准确”或直接作为正式投注分析服务。核心短板不是页面数量，也不是必须更换 Next.js/FastAPI，而是：权限边界、任务独占、证据与预测版本一致性、赔率质量、历史训练数据、时间切分回测、概率校准、基准对比和生产观测。

主观成熟度评分（用于排序，不是认证）：

| 维度 | 评分 | 判断 |
|---|---:|---|
| 用户界面 | 7/10 | 已像专业比分站，信息结构清晰；可信度表达和移动细节仍不足 |
| 数据链路 | 5/10 | 有多级降级和快照，但来源无 SLA、单一赔率、版本可能错配 |
| 预测引擎 | 3/10 | Poisson 参数为手工规则，LLM 概率/仓位未经过校准和回测 |
| 工程质量 | 6/10 | 测试和错误状态较完整；鉴权、迁移、只读语义和多实例协调缺失 |
| 生产运维 | 4/10 | 有作业历史和退避，但任务仍与 API 进程耦合且缺少告警/租约 |
| 综合生产就绪度 | 4.5/10 | 可做内部试运行，不宜进行准确率宣传或面向公众开放操作能力 |

## 已有优势

- 赛程优先的比分中心比通用 Dashboard 更符合足球用户习惯。
- 中文队名/球员展示、队徽、近期状态、伤停、首发、赔率和证据就绪度形成了完整阅读路径。
- 不捏造缺失赔率，能显示部分证据、失败和 `no_bet`，方向正确。
- 证据快照、内容哈希、模型/提示词版本和不可变预测为审计打下了基础。
- 双模型、独立模拟账户、结算和 Brier/ROI/回撤等指标让后续实验可持续积累。
- API 全量测试 80 项通过，Web lint/build 通过，说明主要问题是生产边界而非大面积功能故障。

## 上线阻断项（P0）

### 1. 管理能力没有用户鉴权

`/admin` 对未登录访客开放；所有 Next.js `/api/admin/*` 代理会自动附加服务端 `ADMIN_API_KEY`，但没有会话或角色校验。公众还能在比赛页看到“手动生成”。任何访客都可能消耗数据/API/模型额度并写入预测、作业和模拟仓位。

要求：加入 Web 会话鉴权和 `operator` 角色；隐藏公共导航中的操作台；所有代理先鉴权再转发；生产环境缺少非默认密钥时启动失败；昂贵操作增加限流和幂等键。

### 2. 公共 GET 会写数据并调用供应商

赛程列表、球队和比赛详情 GET 都可能触发同步；比赛详情 GET 还可能创建预测和模拟下注。页面刷新因此具有成本和持久副作用，也无法安全缓存、重试或压测。

要求：公共 API 只返回缓存和新鲜度；同步、预测、下注、结算全部由 Worker 或受保护的 POST/队列触发。

### 3. 新证据没有让旧预测失效

实测比赛的证据/赔率在 22:14 更新，两套模型结果仍是 18:00 生成。页面显示“赛前数据已同步”，但预测可能基于旧赔率。当前成功预测只在首次确认首发时自动重跑，没有比较证据版本/哈希。

要求：预测记录必须绑定 `evidence_snapshot_id`、`odds_snapshot_id` 和 `as_of`；材料字段变化后标记 `stale` 并按 T-24h、T-2h、确认首发等策略生成新版本；页面同时展示证据时间、预测时间和是否过期。

### 4. 当前模型不能支撑“准确”承诺

Poisson v0.1 使用硬编码系数和固定 75% 模型/25% 市场权重，没有训练过程。LLM 输出会直接覆盖概率，并可自行决定 0%-100% 仓位。JSON Schema 只保证格式，不保证概率校准、`predicted_outcome` 与最大概率一致，也不保证仓位符合期望收益和风险公式。

要求：在完成时间切分回测和基准对比前，页面只能称“实验性概率”；立即把仓位从 LLM 输出移到确定性策略，禁止 100% 仓位成为默认实验规则。

### 5. 中文球员名契约仍被 API 绕过

实测 61 个球员的显示 `name` 均为中文，但 API 同时暴露 61 个供应商英文 `original_name`。供应商原名可以留在内部实体匹配层，不能出现在公共 DTO、页面或日志。

要求：建立统一公共序列化边界，递归清除/转换球员原名；加入公共 API 契约测试，任何英文供应商球员名都使测试失败。

## 数据源方案

### 方案 A：最小上线方案（推荐）

继续使用已接入的 API-Football，但升级到满足赛季/额度的付费计划；新增 The Odds API 作为独立赔率源；ESPN/TheSportsDB 只做公开展示降级，不作为可下注预测的关键证据。

优点：改动最小、最快上线、保留现有 ID 和适配器。缺点：足球高级特征有限，仍需自己构建历史特征。

### 方案 B：数据质量优先

以 Sportmonks 为足球主源，使用其 fixtures、lineups、sidelined、formations、referee/weather、xG/xPTS、赔率/历史赔率等能力；The Odds API 做独立价格交叉验证；API-Football 保留为备份。

优点：结构化特征更丰富，更适合训练。缺点：成本、ID 映射和迁移工作较大；购买前必须用试用数据验证英超/西甲/中超的覆盖、延迟、历史深度和再展示许可。

### 方案 C：多供应商聚合

API-Football、Sportmonks、The Odds API 同时进入规范化层，按字段质量和新鲜度选择来源并交叉检查。

优点：韧性最好。缺点：实体匹配、冲突处理、费用和运维复杂度最高，当前阶段属于过度设计，不建议直接做。

### 推荐的抓取频率

“每小时跑一次”可作为底线，但临近开赛的数据不能只按小时更新：

| 数据 | 建议频率 |
|---|---|
| 赛程/赛果 | 每 60 分钟 |
| 积分榜/球队资料 | 每 3-6 小时；比赛结束后立即刷新 |
| 伤停/一般证据 | T-36h 起每 60 分钟；T-6h 起每 15-30 分钟 |
| 赔率 | T-36h 起每 30-60 分钟；T-6h 起每 10-15 分钟 |
| 首发 | T-120m 起每 5 分钟，确认后停止高频轮询 |
| 预测 | T-24h 初版、T-2h 更新版、确认首发终版；材料证据变化时重算 |
| 结算 | 每 10-15 分钟 |

所有请求应记录 `provider`、配额响应头、`fetched_at`、上游更新时间、耗时、HTTP 状态、原始哈希和字段级来源。

## 推荐预测架构

```text
供应商 API
  -> 独立 Ingestion Worker（配额、重试、熔断、租约）
  -> 原始不可变快照
  -> 实体解析（比赛/球队/球员/中文别名）
  -> 规范化证据与赔率时间序列
  -> 特征构建（只使用 as_of 前信息）
  -> 数值预测引擎
       1. 去水市场概率基准
       2. Dixon-Coles/Poisson 基准
       3. 结构化 ML（历史数据足够后）
  -> 时间切分校准与集成
  -> 确定性下注/不下注策略
  -> 不可变预测版本
  -> 只读 FastAPI -> Next.js

完赛结果 + 临场收盘赔率
  -> Evaluator（Brier、LogLoss、校准、CLV、ROI、置信区间）
```

关键原则：LLM 不应是正式概率和仓位的唯一决策器。它更适合把新闻/伤停文本转成结构化事件、总结已给出的证据、解释数值模型、指出数据冲突。正式 1X2/让球概率应来自可回测的数值模型；投注策略由确定性公式决定。

### 建议补充的特征

- 主客场拆分、联赛/赛季强度、对手强度修正、时间衰减。
- 最近 xG/xGA、射门质量、定位球、非点球 xG，而不只是比分和积分。
- 休息天数、赛程拥挤、旅行/时区、杯赛轮换、升降级和赛季阶段。
- 确认首发、关键球员预计分钟、伤停影响和阵型变化。
- 主教练更换、裁判倾向、天气/场地（仅在来源稳定时）。
- 多公司 1X2/让球价格、去水概率、分歧、开盘到临场变化和收盘价。

### 如何判断模型真的进步

- 训练/验证必须按时间滚动切分，禁止随机切分导致未来数据泄漏。
- 每个版本同时对比：市场去水概率、Poisson、当前冠军模型和候选模型。
- 核心指标：多分类 LogLoss、Brier、校准曲线/ECE、覆盖率和分联赛表现。
- 投注指标：CLV、ROI、最大回撤、成交样本数和 95% 置信区间；不把小样本 ROI 当准确率。
- 至少累计数百场严格样本并胜过基准后，才允许有限的性能表述；任何页面都展示样本数和评估区间。

## 统一提示词契约 v3

当前两家模型共享输出 Schema，但提示文本和版本号分开，仍会漂移。应建立一个 `PromptContract`，提供同一份系统文本、输入 DTO、输出 Schema 和版本号；DeepSeek/GPT 适配器只负责协议转换。

建议系统约束：

```text
你是足球赛前证据审计与解释模型，不是投注平台，也不执行下注。
只允许使用 evidence_as_of 之前、输入中明确提供的信息；不得补造新闻、球员、赔率或统计。
所有球队和球员只能使用输入中的 chinese_display_name，所有面向用户的文本使用简体中文。
逐项检查来源、新鲜度、样本量和冲突；缺失就明确列出。
不得修改 numeric_engine 提供的已校准概率，不得输出仓位。
若赔率与 numeric_engine 使用的 odds_snapshot_id 不一致，必须标记预测过期。
严格返回 JSON Schema，不输出 Markdown。
```

统一输入至少包含：

- `contract_version`、`fixture_id`、`evidence_as_of`、`kickoff`。
- 每个字段的 `source`、`source_updated_at`、`fetched_at`、`quality`。
- 中文实体、近期状态、H2H、伤停、首发状态、积分榜和结构化高级特征。
- 精确的 `odds_snapshot_id`、bookmaker、market、line、price、overround。
- 数值引擎的模型版本、校准版本和概率。

统一输出建议只负责解释：`summary`、`key_drivers`、`risk_factors`、`missing_evidence`、`source_conflicts`、`stale`、`no_prediction_recommended`。概率、EV、让球结算和仓位由后端计算，避免不同 LLM 的文字偏好改变资金风险。

## 工程与运维补强

- 将调度从 FastAPI lifespan 移到独立 Worker。单机先用一个 Worker + MySQL 租约/命名锁；多实例再引入 Redis/Celery 等队列，不必现在过度设计。
- 使用 Alembic 管理 SQLAlchemy 迁移，停止启动时执行非版本化 DDL。
- 增加结构化日志、request/job/fixture correlation ID、错误脱敏和稳定错误码。
- 指标与告警：作业延迟、连续失败、供应商成功率/延迟/配额、陈旧预测数、映射失败、模型成本、结算积压。
- 增加数据库备份恢复演练、保留策略、原始快照压缩和幂等键。
- 供应商适配器增加指数退避+jitter、熔断、超时分层和每日/分钟配额预算。
- 公共读接口可使用短 TTL/stale-while-revalidate；不要让每个浏览器请求直达供应商。
- 与供应商书面确认存储、历史回测、页面再展示、队徽和赔率的授权范围。

## 用户体验改进

- 首页保留当前比分中心方向；稀疏比赛日加入相邻日期赛程或最近预测，避免大面积空白。
- 去掉没有信息价值的英文小标题，统一中文术语。
- 移动端核心元数据和五个页签不要出现两条可见横向滚动条；使用两行元数据和等宽/可折叠页签。
- 公共页面隐藏操作台和手动生成。
- 每个模型卡增加“本预测使用的数据截止时间、赔率公司/时间、证据版本、是否过期、样本规模”。
- 绩效页默认先显示基准对比和样本数，再显示 ROI；区分“预测质量”和“资金策略”，避免二者混为一谈。
- 明确标识预测首发与确认首发；预计首发不能显示为已确认。

## 12 周路线图

### 第 1-2 周：封住生产风险

鉴权/RBAC、隐藏管理入口、GET 去副作用、默认密钥 fail-closed、证据版本过期规则、中文名公共 DTO、来源去重、Worker 独占锁。

### 第 3-5 周：稳定数据与可观测性

Alembic、供应商配额/熔断/告警、原始快照、赔率时间序列、The Odds API 小范围接入、备份恢复、页面可信度元数据。

### 第 6-9 周：建立真正的评估闭环

历史数据集、严格 `as_of` 特征、市场/Poisson 基准、时间滚动回测、LogLoss/校准/CLV、统一 PromptContract、模型注册表。

### 第 10-12 周：候选生产模型

Dixon-Coles 或梯度提升候选模型、概率校准、冠军/挑战者实验、确定性 EV 和小额分数 Kelly 模拟策略、达到门槛后再决定是否扩大公开范围。

## 上线门槛

- 管理操作未授权访问为 0，昂贵接口具有限流和审计。
- 同一作业在多进程/重启情况下不重复执行，连续失败 5 分钟内告警。
- 赛程新鲜度 P95 < 75 分钟；临场赔率 < 15 分钟；确认首发窗口 < 5 分钟。
- 公共 API 英文供应商球员名为 0，实体匹配错误率有抽样审计。
- 页面不展示证据版本落后的预测；来源链无重复值。
- 预测评估显示样本数、时间范围、LogLoss/Brier/校准和市场/Poisson基准。
- 在冻结的时间外样本上稳定胜过至少一个基准后，才升级“实验性概率”的产品表述。

## 官方资料

- API-Football pricing/coverage: https://www.api-football.com/
- The Odds API v4 and historical snapshots: https://the-odds-api.com/liveapi/guides/v4/index.html
- The Odds API supported sports (includes CSL/EPL/La Liga): https://the-odds-api.com/sports-odds-data/sports-apis.html
- Sportmonks endpoint overview: https://docs.sportmonks.com/v3/endpoints-and-entities/endpoints
- Sportmonks lineups/formations: https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/lineups-and-formations
- APScheduler deployment guidance: https://apscheduler.readthedocs.io/en/master/userguide.html
- Alembic migration tutorial: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- scikit-learn probability calibration: https://scikit-learn.org/stable/modules/calibration.html
- scikit-learn time-series split: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
