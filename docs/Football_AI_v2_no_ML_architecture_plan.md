# Football AI v2 No-ML 架构与开发路线

状态：**Round 3 起唯一权威路线**

生效日期：2026-09-15

## 一、路线优先级

从 Round 3 起，Football AI v2 严格采用 no-ML 架构。本文件覆盖其他规划、审计报告或历史任务中与下列原则冲突的内容：

> Football AI v2 永久不包含任何需要训练参数的机器学习组件。

Round 2 已完成的数据完整性、Feature Snapshot、Prediction Revision、retention、leakage gate 和 reproducibility 约束继续有效，后续只能在其上增量建设，不得建立平行数据系统。

历史文档中的 XGBoost、LightGBM、Random Forest、Transformer、LSTM、GNN、训练型 Calibration、OOF、Stacking、Meta Model、SHAP、Optuna 等路线，从本文件生效时起不再是 v2 的开发目标。

## 二、最终架构

```text
Data Sources
  -> Point-in-Time Feature Engine
  -> Elo / Poisson / Dixon-Coles / Rule Adjustments
  -> Market Prior
  -> Deterministic Probability Fusion
  -> Rule-Based Calibration
  -> Versioned Prediction Revision
  -> LLM Explanation
```

系统核心保持为：

- 透明统计模型
- 确定性规则系统
- 市场信息
- LLM 解释

目标是建立可解释、可审计、可复现、可回测的足球概率预测系统，而不是训练一个从通用特征学习比赛结果的模型。

## 三、永久边界

### 3.1 v2 禁止项

Football AI v2 不得新增、训练、调参、部署或在线更新以下组件：

- XGBoost、LightGBM、Random Forest 或其他监督学习预测器
- Neural Network、Transformer、LSTM、GNN 或其他深度学习预测器
- 从历史样本学习融合权重的 Ensemble、Stacking 或 Meta Model
- OOF 训练链、训练集/验证集管线、超参数搜索或在线学习
- 使用 SHAP 等方式为新增黑盒预测器补做解释
- 由 LLM 生成或修改概率、权重、期望进球或下注结论
- 根据历史样本拟合参数的 Calibration 算法

明确暂停并排除在当前 v2 范围之外：

- Platt Scaling
- Isotonic Calibration
- Temperature Scaling / temperature fitting
- 任何其他依赖历史样本拟合映射参数的概率校准

以后如需评估数据拟合型 Calibration，必须建立独立架构评审和版本范围，不得作为当前 Football AI v2 no-ML 路线的延伸任务直接实施。

### 3.2 允许的统计边界

Elo、Poisson 和 Dixon-Coles 属于 v2 允许的透明统计引擎，但必须满足：

- 公式预先明确，不允许由通用学习器发现公式或特征权重
- 仅使用 `available_at <= prediction_cutoff_at` 的数据
- 初始值、固定系数、更新规则、估计窗口和缺失值策略全部版本化
- 每次预测能够定位当时使用的统计状态和配置快照
- 相同输入、相同版本和相同状态必须得到相同输出
- 禁止自动超参数搜索、按回测结果在线调整权重或隐式自适应

统计量的 cutoff-safe 聚合和显式公式更新不视为机器学习训练。例如 Elo 仅按已发布版本中的固定更新式推进：

```text
expected = 1 / (1 + 10 ^ ((opponent_rating - rating) / scale))
new_rating = rating + K * (actual - expected)
```

其中 `scale`、`K`、初始 rating 和主场修正都必须是固定、可审计的版本配置。

Poisson 默认以截止时刻前的历史聚合计算进球强度：

```text
home_lambda = league_home_goal_rate
              * home_attack_strength
              * away_defence_strength
              * explicit_rule_adjustments

away_lambda = league_away_goal_rate
              * away_attack_strength
              * home_defence_strength
              * explicit_rule_adjustments

P(home_goals = k) = exp(-home_lambda) * home_lambda^k / k!
P(away_goals = k) = exp(-away_lambda) * away_lambda^k / k!
```

各 strength 的分子、分母、窗口和回退值必须写入版本配置。Dixon-Coles 只能对低比分格点应用公开公式；`rho` 必须是人工发布的固定版本参数，禁止根据历史结果自动寻优。

### 3.3 xG 来源边界

xG 只允许来自：

- 有来源、比赛、事件时间和 `available_at` 的外部供应商数据
- 由固定、显式、版本化公式计算的内部指标

禁止在 v2 内训练本地 shot-xG 模型，禁止把来源不明或赛后才产生的 xG 写入赛前预测快照。

## 四、Point-in-Time Feature Engine

后续 Feature Engine 必须复用 Round 2 的 Feature Snapshot、Evidence Snapshot 和 Prediction Revision 审计链。不得另建一套 Feature Store、另存一份无时间边界的特征，或绕过 production leakage gate。

Feature Registry 是现有快照层之上的定义目录，不是平行存储。每个特征定义至少声明：

- `feature_name`
- `feature_version`
- 数据来源与 `source_record_id` 规则
- 显式计算公式或确定性计算步骤
- `available_at` 的确定方法
- rolling window、缺失值和回退规则
- 输出范围和数据质量规则

所有具体特征值继续保存 Round 2 已规定的逐特征时间字段，并满足：

```text
available_at <= prediction_cutoff_at
```

任何违反边界的特征不得进入 production prediction。Rolling form、Elo 状态、球队与球员统计、伤停、首发、赔率、天气、裁判、积分榜、H2H 和新闻证据都遵守同一约束。

## 五、透明统计与规则引擎

### 5.1 Elo

提供 Overall、Home、Away、Attack 和 Defence 等可解释 rating。每次状态更新必须记录赛事、更新时间、前值、后值、公式版本和配置版本；只能消费 cutoff 前已结束比赛。

### 5.2 Poisson 与 Dixon-Coles

Poisson 输出 `home_lambda`、`away_lambda` 和比分概率矩阵。Dixon-Coles 只修正预先声明的低比分组合，不得演变为隐式学习器。最终 1X2 概率必须能从比分矩阵重新聚合得到。

### 5.3 Team Form、Player Impact 与 Fatigue

这些模块只能使用透明聚合和确定性规则：

- Team Form：last 3 / 5 / 8 / 10 与赛季截止时点均值
- Player Impact：确认缺阵、首发变化、阵容稳定性和有来源的球员指标
- Fatigue：休息天数、固定窗口赛程密度、旅行和洲际赛事规则

所有 adjustment 必须保存规则 id、规则版本、输入、公式、输出和证据。规则不得从历史样本自动拟合。

## 六、Market Prior

赔率是市场信息，不是唯一答案。输入可包括 opening odds、current odds、时间序列 movement 和来源质量。

十进制赔率先按固定公式去除 overround：

```text
raw_i = 1 / odds_i
market_probability_i = raw_i / sum(raw_home, raw_draw, raw_away)
```

必须保留赔率值、来源、抓取时间、`available_at`、去水公式版本和结果。未来赔率不得回填到更早 revision。

## 七、确定性 Probability Fusion

Probability Fusion 不是训练型 Ensemble。各输入概率先归一化，再使用人工发布的固定权重：

```text
normalize(p)_i = max(0, p_i) / sum_j(max(0, p_j))
p_fused = normalize(sum_s(weight_s * normalize(p_source_s)))
weight_s >= 0
sum_s(weight_s) = 1
```

归一化分母为 0 或某个来源无效时，必须执行版本配置中预先声明的固定回退。Market Prior 可作为 `p_source_s` 之一，但在整个 prediction revision 的概率链中最多出现一次。

允许权重按数据质量等级选择，但等级阈值和权重映射必须预先写入同一版本配置。例如：

```text
weight_set = configured_weight_map[data_quality_tier]
```

禁止按历史盈利、命中率或近期结果自动学习、搜索或在线更新权重。每个 revision 必须保存输入概率、选择的权重集、规则版本、数据质量等级和融合结果。

当前 v2 把 Market Prior 的单次融合固定在本节。第八节所称“市场概率融合”是指本节步骤受 Calibration Framework、Version Protocol 和 Probability Audit 管理，不是再执行一次融合。若本节已使用 `market_probability`，后续规则不得再次以市场概率作为 prior、权重输入或收缩目标。

## 八、Rule-Based Calibration

### 8.1 保留范围

v2 保留以下治理和评估能力：

- Calibration Framework
- Calibration Evaluation
- Calibration Version Protocol
- Probability Audit
- Historical Reliability Analysis

这里的 Calibration 仅表示确定性概率修正规则及其评估框架，不包含任何拟合型校准模型。

### 8.2 当前允许的规则

当前只允许以下 rule-based calibration：

- 概率归一化
- 市场概率融合（仅指第七节的单次融合，不得重复执行）
- 固定权重调整
- 概率边界限制
- 基于显式数据质量等级的置信度修正

允许的基础公式为：

```text
# 归一化；若分母为 0，则使用版本配置中的固定 prior
p_norm_i = max(0, p_i) / sum_j(max(0, p_j))

# 市场融合使用第七节的 p_fused，只执行一次并纳入本节审计

# 固定权重调整；adjustment_i 由命中的显式规则给出
p_adjusted_i = normalize(p_fused_i * adjustment_i)

# 对 1X2 概率做对称边界保护；epsilon 是 [0, 1/3) 内的版本化常量
p_bounded_i = epsilon + (1 - 3 * epsilon) * p_adjusted_i
# 因而 sum(p_bounded) = 1，且 epsilon <= p_bounded_i <= 1 - 2 * epsilon

# 置信度收缩；shrinkage 是固定质量等级映射，prior 为版本化固定先验
p_final_i = (1 - shrinkage) * p_bounded_i + shrinkage * prior_i
```

其中所有融合权重和 `shrinkage` 必须位于 `[0, 1]`，融合权重之和为 1，`adjustment_i > 0`，`market_probability` 与 `prior` 必须先归一化。`prior` 是版本化固定的非市场收缩先验；同一 revision 已融合市场概率时，不得在收缩阶段再次使用市场先验。任一归一化分母为 0、输入缺失或输入无效时，只能执行版本配置中预先声明的固定回退；不得在运行时根据历史结果生成替代权重或阈值。满足这些输入约束时，`p_final` 仍保持和为 1。

每条规则必须同时具备：

- 显式公式
- 可解释输入和输出
- 不可变的 `calibration_rule_version`
- 生效时间和配置 hash
- 可按历史 revision 重放的完整参数
- point-in-time 回测结果

规则执行顺序必须属于版本协议的一部分，不能依赖运行时随机性。修改公式、阈值、权重、prior、边界、质量等级映射或执行顺序，都必须发布新版本，禁止覆盖旧版本。

### 8.3 Evaluation 与 Historical Reliability

Calibration Evaluation 使用 Brier Score、Log Loss、Calibration Curve、分箱 observed frequency、样本量和覆盖率比较不同规则版本。

Historical Reliability Analysis 只做描述性分析和审计，不得自动产出新参数或回写生产权重。任何基于分析结果提出的规则调整，必须由人工明确公式并发布新的规则版本，再通过 point-in-time backtest 验证。

Probability Audit 至少记录：

- 各统计引擎与市场的原始概率
- normalization、fusion 和 calibration 的逐步结果
- 命中的规则、固定权重、边界、prior 和数据质量等级
- `prediction_cutoff_at`、feature/evidence snapshot id
- 统计引擎版本、规则版本、配置 hash 和最终 revision

## 九、Prediction 与可复现性

后续组件必须沿用 Round 2 的 append-only Prediction Revision。禁止 UPDATE 覆盖历史预测，禁止 live prediction 修改 pre-match prediction，禁止 retention 删除 prediction、revision、feature snapshot 或 evidence snapshot 审计链。

任意预测必须可通过以下标识重新解释：

```text
match_id
+ prediction_revision
+ model_version
+ feature_version
+ evidence_snapshot_id
```

其中现有字段 `model_version` 在 no-ML 路线中表示统计引擎与融合规则 bundle 的版本，不代表机器学习模型。bundle 必须能定位公式、固定配置、统计状态快照、校准规则版本及其 hash。

## 十、LLM 使用边界

LLM 只负责：

- 将有来源的新闻整理为结构化证据候选
- 解释 xG、主场、伤停、首发、疲劳和市场变化
- 解释 prediction revision 为什么变化
- 对已结算预测做赛后复盘

LLM 不得：

- 直接预测胜平负或比分
- 生成、修改或校准概率
- 决定融合权重、统计参数或下注仓位
- 绕过 evidence、feature snapshot、leakage audit 或 revision 审计链
- 用自然语言输出覆盖结构化计算结果

所有 LLM 解释必须引用已经进入对应 revision 的 evidence 和计算结果；解释失败不得改变原始概率。

现有由 LLM 生成概率、权重、期望进球或仓位的 production wiring 视为 legacy numeric path。Round 3 必须关闭其 v2 production 写入与选择入口，并由 fail-closed gate 拒绝这类数值输入；LLM 结构化证据候选和只读解释能力不受影响。

## 十一、Round 3-8 开发路线

### Round 3：Point-in-Time Feature Engine v2

交付：

- 在现有 Feature Snapshot 上建立 Feature Registry
- 实现或整理 Elo、Form、xG、Fatigue、Player Impact 和 Feature Quality 定义
- 明确每个特征的公式、窗口、来源、`available_at` 和版本
- 建立 legacy learned path 冻结清单，并关闭其现有 v2 production 选择与执行入口
- 增加 fail-closed production deny gate，拒绝 learned engine、learned weight 和 fitted calibrator 标识
- 关闭 LLM numeric prediction 入口，拒绝 LLM 生成的概率、权重、期望进球和仓位进入 v2 production

验收：

- 不新增平行 Feature Store
- 所有特征通过 Round 2 leakage gate
- 相同 cutoff 和版本可重建相同 snapshot
- rolling features 不读取 cutoff 后比赛
- v2 production 对 legacy learned/calibration 路径 fail closed 并写审计日志
- legacy artifact 只允许用于读取和解释旧 revision，不得执行后生成新 prediction
- LLM 输出不得进入 probability source、fusion、calibration 或 stake 数值字段；结构化证据仍须经过现有 evidence 审计链

### Round 4：Transparent Probability Engine

交付：

- Elo 状态与概率转换
- Poisson 进球分布
- Dixon-Coles 低比分修正
- Goal Distribution 到 1X2 概率聚合

验收：

- 所有公式和固定配置可定位、可版本化
- 状态更新只读取 cutoff 前已完成比赛
- 相同 snapshot、状态和版本产生相同概率
- 概率有限、非负且归一化
- production probability source allowlist 只包含已版本化的透明统计引擎、Market Prior 和确定性规则

### Round 5：Market Intelligence

交付：

- odds snapshot 与来源时间审计
- implied probability 和去水归一化
- opening/current odds 与 market movement
- 可版本化 Market Prior

验收：

- 不使用 cutoff 后赔率
- 原始赔率、去水过程和结果可重放
- 缺失或过期赔率走显式降级规则

### Round 6：Deterministic Fusion 与 Rule-Based Calibration

交付：

- 固定权重 Probability Fusion
- Calibration Framework、Evaluation 和 Version Protocol
- normalization、market blend、boundary、confidence shrinkage 规则
- Probability Audit 和 Historical Reliability Analysis

验收：

- 不存在拟合、训练、参数搜索或在线自适应步骤
- 每项修正可从公式、版本配置和输入重放
- 旧 revision 的规则版本永久可定位
- reliability 输出只用于描述与人工决策，不自动改写生产配置

### Round 7：Point-in-Time Backtest Lab

交付：

- chronological / rolling-origin replay
- Brier Score、Log Loss、Calibration、ROI、CLV 和 league breakdown
- revision-level、规则版本级和数据质量级对比

验收：

- 每次回放严格使用当时可获得的数据、赔率和配置
- 不建立训练集、OOF、Meta Model 或超参数搜索
- 不因回测结果自动更新生产参数
- 任一指标可追溯到不可变 prediction revision

### Round 8：Read-Only AI Analyst

交付：

- Match Explanation
- Risk Analysis
- Prediction Change Explanation
- Post-Match Review

验收：

- 只读取对应 revision 的结构化事实和证据
- 不生成或修改概率、权重、仓位和 revision
- 对高风险事实保留来源与不确定性
- LLM 不可用时统计预测链仍完整运行

## 十二、Legacy 兼容策略

仓库中已经存在的 learned ensemble、temperature calibration 或其他 ML 路径按 legacy compatibility 处理：

- 冻结实现，不扩展功能
- 不增加调用方；关闭已有 v2 production 选择与执行入口
- v2 production 配置和运行时必须通过 fail-closed deny gate 拒绝 learned engine、learned weight、训练 artifact 和 fitted calibrator
- 不作为 Round 3-8 的目标或验收依赖
- 在日志和配置中明确标记 legacy，避免与 no-ML 版本混用
- 保留读取旧 prediction revision 所需的最小兼容能力
- legacy artifact 仅可作为旧 revision 的只读审计引用，不得执行并产生新 prediction 或 revision
- 后续删除必须另立兼容迁移任务，先证明历史 revision 仍可解释和重放

冻结不代表继续认可该路线，也不得以兼容名义新增训练、拟合或权重学习。

## 十三、运行资源

v2 不需要 GPU。资源优先投入数据来源、历史比赛与球员数据质量、赔率时效性、审计存储和稳定的 point-in-time 计算。

## 十四、最终原则

Football AI v2 不是黑盒预测工程，也不是训练型 ML 平台。

Football AI v2 是：

```text
统计模型 + 规则系统 + 市场信息 + LLM 解释
```

所有概率变化都必须能够回答：用了什么时点的数据、经过什么显式公式、采用哪个不可变版本、为什么发生变化，以及如何用当时的输入重新得到相同结果。
