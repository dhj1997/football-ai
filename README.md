# 足球赛前分析台

面向中超、西甲和英超的持续赛前分析与模拟资金系统。系统自动同步赛程、积分榜和赛前证据，并行使用 DeepSeek 与 GPT-5.6 Sol 生成两套可审计赛果预测；赔率价值、`no_bet` 原因和模拟仓位由后端确定性规则统一计算。

默认不展示演示赛程。TheSportsDB 提供短窗口真实赛程和免费球队资料，ESPN 提供三个联赛的完整当前赛季积分榜、阵容、球员统计和比赛记录，API-Football 在额度允许时补充交锋、伤停、首发和赔率。API-Football 不可用时，系统会保存明确标注的部分真实证据并允许两个模型生成 `no_bet` 预测，不会用演示值补齐缺失数据。

## 已实现

- 今日、明日、历史赛程与三联赛筛选
- 单场比赛证据准备度：近期状态、交锋、阵容、首发、赔率、模型
- FastAPI 常驻自动任务：赛程、积分榜、证据同步和赛后结算；模型预测全部由管理员手动触发
- 管理员可查看持久作业记录并立即运行指定作业
- 完整当前赛季积分榜：英超、西甲、中超
- 球队详情：当前赛季赛果、完整阵容、球员出场/进球/助攻/牌/伤病状态
- DeepSeek 与 GPT-5.6 Sol 使用同一个版本化 `PromptContract`、证据版本和 JSON Schema，分别输出预测及下注观点，区分初步预测与确认首发版
- 伤停、阵容和首发关联到稳定球员身份；按预计分钟、赛季表现、位置贡献和替补差值识别明星、关键主力、轮换与边缘球员
- 比赛详情展示关键可用/缺阵球员、预计替补及进攻、防守、中场和门将战力保留率，不按伤停人数直接扣减整体实力
- Poisson 进球分布与去水赔率融合的胜平负概率
- 亚洲让球的全赢、半赢、走盘、半输、全输概率
- 赛果预测、赔率价值和执行决定分层输出；后端计算回本概率、去水概率、预期优势、不确定性和标准原因码
- 不可变证据快照、内容哈希、提示词版本、模型版本和预测版本持久化
- 两个独立的 1000 初始模拟账户；后端按最高正优势市场计算 10%-25% 单注仓位，每日最多 50%，且每个模型每个联赛每天最多执行一场，不借款且不连接真实投注平台
- 逐笔模拟下注、资金流水、已实现权益曲线、赛后盈亏、ROI、命中率、Brier、数据完整度和最大回撤
- 亚洲盘全赢、半赢、走水、半输、全输分类汇总
- 预测指标支持联赛、赛季、日期和模型版本筛选
- TheSportsDB 免费三联赛真实赛程同步、缓存与最后同步时间
- API-Football 单场赛前证据同步；未发布首发或暂缺赔率时明确显示缺失状态，不使用演示值代替
- 赛前赔率来自 API-Football / API-Sports 的 `/odds` 接口，展示返回结果中的第一家 bookmaker、1X2 与亚洲让球盘口，并记录同步时间
- 详情面板展开近期可用比赛、历史交锋、去重后的伤停球员与首发/替补名单；当前赛季已进行场次不足 5 场时按实际数量展示
- 球队档案、队徽、成立年份、主场容量和全队注册名单；所有球员名经过统一中文别名边界，人工审核别名优先，未收录姓名使用已配置 DeepSeek 做纯姓名音译并持久缓存、标记“自动音译”，失败时显示带号码或稳定标识的唯一“待核验球员”，公共 API 不暴露供应商英文原名
- `PlayerValueProvider` 提供可替换的授权、覆盖和再展示门禁及持久缓存；当前没有覆盖三联赛且授权明确的身价源，金额保持 `null` 并显示“暂无可靠身价”，不抓取 Transfermarkt 或伪造数据
- 供应商英文队名通过统一词典转换为中文；暂未收录的名称保留原文，避免误译

## 本地运行

环境要求：Node.js 22+、pnpm、Python 3.12+。

```powershell
cd D:\Work\football-ai
pnpm install

cd apps\api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端：

```powershell
cd D:\Work\football-ai\apps\web
pnpm dev --hostname 127.0.0.1 --port 3000
```

页面入口：

- 赛程与预测：`http://127.0.0.1:3000`
- 三联赛积分榜：`http://127.0.0.1:3000/standings`
- 模拟资金与绩效：`http://127.0.0.1:3000/performance`
- 管理与作业状态：`http://127.0.0.1:3000/admin`
- API 文档：`http://127.0.0.1:8000/docs`

只要 FastAPI 进程保持运行，数据库驱动的自动任务就会持续工作。生产环境应使用 Windows 服务、systemd、Docker 或其他进程守护方式保持 API 进程常驻；浏览器和 Codex 任务不承担生产调度。

## 配置

先在项目根目录创建配置文件：

```powershell
Copy-Item .env.example .env
```

默认 TheSportsDB key 为 `123`。DeepSeek 和 GPT 密钥只从后端环境变量读取。如果配置 `API_FOOTBALL_KEY`，系统会优先拉取交锋、伤停、首发和赔率；遇到额度、限流或请求失败时会尝试 ESPN 公共数据，最后才使用 TheSportsDB 部分证据。ESPN 使用现有 `ESPN_BASE_URL` 配置，不需要额外密钥；接口不可用时会自动降级并记录来源。开发环境默认管理员密钥为 `dev-admin-key`，只用于本地开发；生产部署必须替换，并由 Web 服务端保存，不得暴露到浏览器。

关键变量：

- `API_FOOTBALL_KEY`：可选的 API-Football 密钥，后续用于详细赛前证据。
- `ESPN_BASE_URL`：ESPN 公共数据地址，默认 `https://site.api.espn.com`，用于积分榜、球队资料和 API-Football 失败时的比赛证据。
- `API_DEEPSEEK_KEY`：DeepSeek 后端密钥，不得使用 `NEXT_PUBLIC_` 前缀。
- `DEEPSEEK_MODEL`：默认 `deepseek-v4-flash`。
- `DEEPSEEK_BASE_URL`：默认 `https://api.deepseek.com`。
- `DEEPSEEK_TIMEOUT_SECONDS`、`DEEPSEEK_MAX_RETRIES`、`DEEPSEEK_MAX_TOKENS`：模型超时、重试和输出预算。
- `API_CHATGPT_KEY`：GPT 服务端密钥，不得使用 `NEXT_PUBLIC_` 前缀。
- `CHATGPT_MODEL`、`CHATGPT_BASE_URL`：默认分别为 `gpt-5.6-sol` 和 `https://api.quya.org/v1`。
- `SIMULATION_COMPETITION_ID`：当前双模型模拟竞赛标识；更换标识可开始一轮新的独立 1000 对 1000 对比，旧记录继续保留。
- `SCHEDULE_PROVIDER`：当前为 `thesportsdb`。
- `THESPORTSDB_API_KEY`：TheSportsDB 赛程 key，默认 `123`。
- `SCHEDULE_LOOKBACK_DAYS`：赛程同步回看天数，默认 `1`，避免免费源的请求频率限制。
- `AUTOMATION_ENABLED`：是否启动 FastAPI 常驻自动任务，默认 `true`。
- `AUTOMATION_ANALYSIS_ENABLED`：是否自动运行证据与模型分析；当前本地配置为 `false`，模型预测需从比赛详情手动触发。
- `AUTOMATION_*_INTERVAL_MINUTES`：赛程、积分榜、分析和结算间隔。
- `AUTOMATION_FAILURE_BACKOFF_MINUTES`：失败或部分成功后的退避时间。
- `PREDICTION_LEAD_HOURS`：进入自动分析的开赛前时间窗，默认 `36`。
- `AUTOMATION_EVIDENCE_REFRESH_LIMIT`：每轮最多刷新多少场 API-Football 证据，默认 `1`。
- `USE_DEMO_DATA`：是否在没有真实缓存时显示演示数据，默认 `false`。
- `ADMIN_API_KEY`：保护刷新与预测接口。
- `DATABASE_URL`：默认使用 `sqlite:///./football_ai.db`；生产或共享环境可使用 `mysql+pymysql://用户名:密码@主机:3306/football_ai?charset=utf8mb4`。应用启动时会创建赛程、联赛/球队/授权身价快照、不可变证据/预测、模拟下注/流水/结算和作业记录表。
- `NEXT_PUBLIC_API_BASE_URL`：浏览器读取公开 API 的地址。
- `API_BASE_URL`：Next.js 服务端调用 FastAPI 的地址。

### 切换到 MySQL

先创建数据库和账号：

```sql
CREATE DATABASE football_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'football_ai'@'%' IDENTIFIED BY 'change-this-password';
GRANT ALL PRIVILEGES ON football_ai.* TO 'football_ai'@'%';
FLUSH PRIVILEGES;
```

然后把根目录 `.env` 的 `DATABASE_URL` 改为：

```text
DATABASE_URL=mysql+pymysql://football_ai:change-this-password@127.0.0.1:3306/football_ai?charset=utf8mb4
```

重启 API 服务即可。当前代码已保留 SQLite 兼容；本地没有 MySQL 服务时继续使用 SQLite。

## 验证

```powershell
cd D:\Work\football-ai\apps\api
.\.venv\Scripts\python.exe -m pytest -q

cd D:\Work\football-ai\apps\web
pnpm lint
pnpm exec tsc --noEmit
pnpm build
```

## 模型边界

当前模型用于可审计的概率分析和模拟资金流程，不是已经过充分历史回测的生产投注模型。页面中的概率不是确定赛果，也不构成投注建议；系统没有真实投注平台接口，不会执行真实交易。

真实赛程不会使用演示近期状态、阵容、身价或赔率。LLM 输出赛果/让分概率、球员证据解释、风险说明和下注观点，不能覆盖后端 EV、市场选择、原因码或仓位。后端扫描全部可用市场并选择预期优势最高的方向；亚洲盘 EV 以各模型自己的覆盖概率为方向权威，Poisson 只补充模型契约未提供的走盘及全赢/半赢结算形状。模型原始 `no_bet` 仍展示但不再拥有否决权。首发未确认和低于 60% 的总体置信度是告警；正优势、赔率时效、数据完整度和风控仍决定能否模拟执行。未执行场次继续展示建议方向、预期优势和理论仓位；完整证据不可用、赔率过期、没有匹配市场或未获得联赛当日名额时，实际下注金额为 0。“最可能获胜”不等于“当前赔率值得下注”。
