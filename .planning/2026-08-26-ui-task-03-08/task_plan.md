# UI Tasks 03-08

## Goal

按既定文档顺序完成 Schedule、Match Detail、Analysis、Performance、Standings、Admin 的前端界面重构，复用 TASK_01/TASK_02 的 UI Foundation 与 Shared Components。

## Scope

- 只修改 `apps/web` 前端展示结构、样式和交互状态。
- 保留现有数据请求、API props、路由、预测计算、结算和权限契约。
- 不修改后端、API、数据库、模型调用、提示词或预测逻辑。
- 不伪造缺失比赛/证据数据；保留中文球员名边界和缺失数据语义。

## Phases

### TASK_03 Schedule

- Status: complete
- 依据 PAGE_SPECS 优化赛程层级、日期/联赛筛选、比赛扫描、就绪度、摘要和反馈状态。

### TASK_04 Match Detail

- Status: complete
- 保持比赛 Hero、证据就绪、赛前快照、页签和详细证据语义。

### TASK_05 Analysis

- Status: complete
- 改善 DeepSeek/GPT 输出的模型身份、概率、结论、依据、风险和审计信息可读性。

### TASK_06 Performance

- Status: complete
- 保持双账户模拟语义，重排资金、指标、对比、曲线、账本和结算记录层级。

### TASK_07 Standings

- Status: complete
- 优化积分榜密度、固定表头、积分/净胜球强调和响应式溢出。

### TASK_08 Admin

- Status: complete
- 提升系统新鲜度、作业状态、失败可见性和手动操作反馈；不改变授权模型。

## Verification

- Status: complete
- 每阶段完成后检查前端编译与关键交互。
- 全部阶段完成后运行 `pnpm lint`、`pnpm exec tsc --noEmit`、`pnpm build` 和 `git diff --check`。

## Errors

暂无。
