---
name: 足球赛前分析台
description: 以比赛运行看板组织可追溯赛程、证据状态与赛前概率
colors:
  paper: "#f5f6f1"
  surface: "#ffffff"
  surface-soft: "#edf0e9"
  ink: "#17211b"
  muted: "#657068"
  line: "#d8ddd5"
  line-strong: "#bcc6bc"
  pitch-green: "#176044"
  pitch-green-dark: "#0d4530"
  pitch-green-soft: "#dcebe1"
  signal-yellow: "#f3c84b"
  signal-yellow-soft: "#fff4c8"
  focus-blue: "#2c6e9b"
  focus-blue-soft: "#dbeaf4"
  alert-red: "#c7473d"
  alert-red-soft: "#f8e1df"
typography:
  display:
    fontFamily: "Bahnschrift SemiCondensed, Microsoft YaHei, sans-serif"
    fontSize: "clamp(28px, 3vw, 40px)"
    fontWeight: 760
    lineHeight: 1.05
    letterSpacing: "0"
  body:
    fontFamily: "Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    letterSpacing: "0"
  label:
    fontFamily: "Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: "10px"
    fontWeight: 800
    letterSpacing: "0"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "8px"
rounded:
  xs: "3px"
  sm: "4px"
  md: "5px"
  lg: "6px"
  round: "50%"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.pitch-green-dark}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "44px"
  button-icon:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.pitch-green-dark}"
    rounded: "{rounded.sm}"
    size: "44px"
  status-ready:
    backgroundColor: "{colors.pitch-green-soft}"
    textColor: "{colors.pitch-green-dark}"
    rounded: "{rounded.round}"
---

# Design System: 足球赛前分析台

## Overview

**Creative North Star: “比赛运行看板”**

设计源自 seed `a76aed7b`：借用机场运行屏的高效扫读秩序，组织赛程、数据状态和预测证据，但所有表达都使用足球术语与克制的日间分析台视觉。界面服务于连续浏览和临场操作，信息密度高、层级明确，不把概率包装成博彩刺激或确定结论。

**关键特征：** 冷白纸面、深球场绿、信号黄；紧凑的表格化分区；数字使用等宽特性；选择比赛后同步更新的六阶段证据轨道；演示数据、初步预测和缺失信息均明确标注。

## Colors

色彩以纸面中性色承载信息，以球场绿表达选择、就绪与主操作；黄、蓝、红只承担提醒、焦点和错误等有限语义。

- **主色：** 深球场绿用于主按钮、预测标题和高置信层级；球场绿用于选中边线、就绪状态和概率强调；浅绿只作为就绪底色。
- **信号色：** 黄色用于品牌标记、活动筛选下划线、演示数据和管理员操作带；蓝色用于键盘焦点和客队辅助识别；红色用于错误提示。
- **中性色：** 冷白纸面铺底，纯白与柔和灰绿分隔面板；墨绿黑用于正文，灰绿用于次要说明，双层线色承担大部分结构分隔。

**稀缺信号规则。** 高饱和色必须绑定明确状态，不得大面积铺陈；概率、就绪和错误不能只靠颜色表达。

## Typography

标题使用窄体系统字栈，形成运行看板的紧凑力度；正文使用中文系统无衬线字栈，保证跨平台可读性；版本号与精确时间使用等宽字栈。全局字距固定为 `0`。

- **Display：** 页面主标题使用紧缩字面、短行高和较重字重，桌面端在既定范围内响应式变化。
- **Title：** 面板标题主要为 13–16px，保持紧凑，不使用营销页尺度。
- **Body：** 说明文字主要为 10–13px；正文色与次要色形成层级。
- **Label：** 7–10px 的粗体标签用于英文眉题、列头、时间戳与状态，英文眉题可全大写。
- **Numeric：** 开球时间、比分、赔率与概率启用表格数字，便于纵向比较。

**扫读优先规则。** 字号层级服务于列式比较；禁止用超大标题、负字距或装饰字体抢占操作空间。

## Layout

主内容最大宽度为 1480px，桌面端使用赛程列表与比赛详情双栏：左栏最小 430px，右栏最小 520px，列表行高约 94px。顶部状态条、标题区、筛选带和工作区连续衔接，主要区块依靠 1px 分隔线与 8–24px 内边距维持高密度秩序，避免卡片套卡片。

- **≤1040px：** 保持双栏但收紧最小列宽；六项证据轨道改为 3×2；预测事实允许换行；让球结果重排。
- **≤820px：** 工作区改为上下堆叠，赛程在前、详情在后；日期分段控件占满宽度，联赛筛选横向滚动；隐藏状态条长说明。
- **≤560px：** 隐藏品牌副标题、日期印章、赛程状态长文案和次要刷新按钮；列表列宽与队徽缩小；赔率改为 2×2，预测事实单列，让球结果改为三列流式排列。

所有固定格式控件保留稳定尺寸：主要按钮和筛选项高 44px，图标按钮为 44×44px，页面最小宽度为 320px。横向内容优先截断或滚动，不允许文字与相邻控件重叠。

## Elevation & Depth

系统以色调分层和细边线为主，只有完整工作区使用一层低对比环境阴影（`0 12px 30px rgba(30, 47, 36, 0.08)`）。选中筛选仅使用极轻阴影；局部卡片、概率格和轨道节点保持平面，避免把每个区块抬成悬浮卡片。

**默认平面规则。** 阴影只强调整个操作工作区或真实交互状态，不能作为装饰性分区手段。

## Shapes

形态语言克制而接近设备面板：主要容器与控件使用 3–6px 小圆角，选中赛程使用 4px 竖向状态条，分隔线保持直线和连续网格。圆形仅用于状态点和证据图标底座，不把文字标签做成无意义胶囊。

## Components

### Navigation

深绿页头高 68px，底部以 3px 信号黄线收口。品牌标记为 38px 方形黄底图标；导航为紧凑文字链接，悬停仅增加半透明白底。当前页面通过 `aria-current="page"` 暴露给辅助技术。

### Filters and fixture rows

日期使用分段控件，联赛使用带计数的横向选项；两者均以 `aria-pressed` 表达选中状态。比赛行本身是完整按钮，选中时同时使用浅绿底、左侧绿线与 `aria-pressed`，不能只靠背景色。

### Evidence rail

这是系统的标志性组件。选择一场比赛后，详情数据驱动六个固定阶段按“近期状态 → 历史交锋 → 可用阵容 → 当日首发 → 赛前赔率 → 模型结果”呈现；轨道本身只读，不伪装成可点击步骤。标题显示 `n / 6` 总体就绪数，每个节点同时提供编号、图标、足球语义标签、状态文字和带无障碍名称的就绪/等待图标；在中小屏保持 3×2 稳定网格。

### Operator actions and feedback

管理员操作区使用浅黄底与主操作深绿按钮区分于访客浏览区。运行时按钮禁用并显示旋转图标与“计算中”；完成后在按钮下方显示浅绿成功条、短版本号和精确时间。成功条使用 `role="status"` 与 `aria-live="polite"`，按钮通过 `aria-describedby` 关联反馈，异步结束后焦点返回发起按钮。错误条使用 `role="alert"`；关闭、刷新等图标按钮必须保留可访问名称。

全局键盘焦点为 3px 半透明蓝色外框并偏移 2px；系统遵循 `prefers-reduced-motion`，将动画时长压缩到近乎静止。任何新增交互都应延续可见焦点、语义状态和至少 44px 的主要触控高度。

### Prediction panels

预测以三列胜平负概率、数值、球队文字和进度条共同表达，最高项同时使用底色、文字与条形强调。预测阶段、模型版本、生成时间、证据置信度和免责声明必须可见；没有赔率时展示明确空状态，不生成让球内容。

## Do's and Don'ts

### Do

- **Do** 保持运行看板式的连续表格、稳定列宽与高密度扫读顺序。
- **Do** 明确标注演示数据、首发是否确认、预测阶段、模型版本和信息时间。
- **Do** 让颜色、文字、图标和 ARIA 语义共同表达选择、进度、成功与错误。
- **Do** 在小屏重排网格、隐藏次要信息，并保留核心比赛与证据内容。

### Don't

- **Don't** 使用博彩网站式霓虹盘口墙、装饰性渐变、发光色块或制造下注冲动的视觉语言。
- **Don't** 用大面积营销式英雄区、卡片套卡片、过度圆角或无功能装饰稀释操作密度。
- **Don't** 把概率表现为确定赛果，或用多余小数制造虚假精确性。
- **Don't** 在首发未确认时伪装为确认版预测，或在缺少赔率时补造让球盘口。
