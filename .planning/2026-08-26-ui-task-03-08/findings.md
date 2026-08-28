# Findings

- TASK_03 目标页面由 `FixtureWorkspace` 提供，公开首页和 operator 模式共用赛程列表；已有日期、联赛、数据源状态、加载/错误状态和详情入口。
- TASK_04 的比赛详情由 `MatchCenter` 与 `fixture-workspace` 的证据组件共同提供，近期战绩、交锋、阵容、伤停、首发、赔率和预测均已有数据契约。
- TASK_05 的双模型预测渲染主要位于 `fixture-workspace.tsx`，不能修改模型调用、提示词或预测计算。
- TASK_06、TASK_07、TASK_08 分别对应 `performance-dashboard.tsx`、`standings-dashboard.tsx` 和 `operations-panel.tsx`；TASK_02 已提供共享页头、区块标题、标签、状态和反馈组件。
- `globals.css` 包含现有页面 class 与 TASK_01 token；页面重构应保留旧 class 以降低视觉回归风险。
