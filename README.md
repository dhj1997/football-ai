# 足球赛前分析台

面向中超、西甲和英超的赛前分析 MVP。访客可以浏览今日、明日和历史赛程；管理员只对选中的比赛手动生成预测，每次运行都会保存独立版本。

当前默认不展示演示赛程。操作台默认使用 TheSportsDB 免费赛程接口，点击“同步赛程”后，系统同步中超、西甲和英超近 7 天至明日的赛程，并由公开页读取本地缓存。只有显式设置 `USE_DEMO_DATA=true` 才会在尚无真实缓存时显示演示赛程。API-Football 只作为后续首发、伤停和赔率的数据源，不再是赛程展示的前置条件。

## 已实现

- 今日、明日、历史赛程与三联赛筛选
- 单场比赛证据准备度：近期状态、交锋、阵容、首发、赔率、模型
- 管理员手动发起预测，区分初步预测与确认首发版
- Poisson 进球分布与去水赔率融合的胜平负概率
- 亚洲让球的全赢、半赢、走盘、半输、全输概率
- 预测版本、模型版本和证据时间戳持久化到 SQLite
- TheSportsDB 免费三联赛真实赛程同步、缓存与最后同步时间
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

访问公开页 `http://127.0.0.1:3000`，操作台为 `http://127.0.0.1:3000/admin`，API 文档为 `http://127.0.0.1:8000/docs`。

## 配置

先在项目根目录创建配置文件：

```powershell
Copy-Item .env.example .env
```

默认无需填写赛程 API Key，TheSportsDB 免费 key 为 `123`。重启 API 服务后进入操作台点击“同步赛程”。如果你有 API-Football Key，再填入 `API_FOOTBALL_KEY`，它会用于后续的首发、伤停和赔率接口。开发环境默认管理员密钥为 `dev-admin-key`，只用于本地开发；生产部署必须替换，并由 Web 服务端保存，不得暴露到浏览器。

关键变量：

- `API_FOOTBALL_KEY`：可选的 API-Football 密钥，后续用于详细赛前证据。
- `SCHEDULE_PROVIDER`：当前为 `thesportsdb`。
- `THESPORTSDB_API_KEY`：TheSportsDB 赛程 key，默认 `123`。
- `SCHEDULE_LOOKBACK_DAYS`：赛程同步回看天数，默认 `7`。
- `USE_DEMO_DATA`：是否在没有真实缓存时显示演示数据，默认 `false`。
- `ADMIN_API_KEY`：保护刷新与预测接口。
- `DATABASE_URL`：当前 MVP 支持 `sqlite:///` URL。
- `NEXT_PUBLIC_API_BASE_URL`：浏览器读取公开 API 的地址。
- `API_BASE_URL`：Next.js 服务端调用 FastAPI 的地址。

## 验证

```powershell
cd D:\Work\football-ai\apps\api
.\.venv\Scripts\python.exe -m pytest -q

cd D:\Work\football-ai\apps\web
pnpm lint
pnpm build
```

## 模型边界

当前模型用于打通可审计的产品流程，不是已经过历史回测的生产预测模型。上线前需要完成按时间切分的回测、概率校准、基线对比、缺失数据降级和持续漂移监控。页面中的概率不是确定赛果，也不构成投注建议。

真实赛程不会使用演示近期状态、阵容或赔率生成预测。当前版本会将真实比赛的预测操作保持禁用，直到这些赛前证据接口完成同步。
