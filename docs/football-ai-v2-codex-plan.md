# Football AI v2 优化实施总方案（Round 1/2 历史基线）

> **状态：历史文档。** 本文仅记录 Round 1/2 的审计背景和早期方案，不再作为 Round 3 及后续轮次的实现依据。
>
> 从 Round 3 起，唯一有效的架构与开发路线是 [`Football_AI_v2_no_ML_architecture_plan.md`](./Football_AI_v2_no_ML_architecture_plan.md)。如本文任何内容与该文档冲突，以 no-ML 架构文档为准。
>
> Football AI v2 永久停止 XGBoost、LightGBM、Random Forest、LSTM、Transformer、GNN、OOF、Stacking、Meta Learner、SHAP、Optuna，以及 Platt Scaling、Isotonic Calibration、Temperature Scaling 等需要用历史样本拟合参数的设计。禁止用其他名称重新引入同类训练组件。
>
> v2 的固定边界是：**透明统计模型 + 确定性规则系统 + 市场信息 + LLM 解释**。Elo、Poisson、Dixon-Coles 仅在公式、输入、状态、参数和版本均可审计、可回放时允许使用；LLM 不生成或修改概率与融合权重。
>
> **阅读边界：** 第 0-79 节保留为历史背景，不构成待办、验收标准或技术选型；当前可执行的 Round 3-8 顺序、测试和最终任务以第 80-90 节及上述 no-ML 架构文档为准。

> **以下为已失效的 Round 1/2 原始目标，仅作历史记录：**
>
> **目标：让 `dhj1997/football-ai` 从“LLM 赛前分析 + 模拟资金系统”升级为“数据驱动、概率校准、可回测、可解释、可持续学习”的足球预测平台。**
>
> 重点不是让 LLM “猜得更准”，而是建立一套 **真实数据 → 特征工程 → 多模型概率预测 → 概率校准 → 情景模拟 → 多维输出 → 历史回测 → 持续迭代** 的闭环。

---

## 0. Round 1/2 原始指令（已失效）

### 历史核心原则（已失效）

1. **不要推倒重写现有项目。**
2. 先审计现有代码、数据库、Provider、Prediction、Evidence、Metrics、Simulation 结构。
3. 优先增强后端数据与模型层，UI 只做必要改造。
4. **任何模型概率都必须有数据来源、时间戳、模型版本、feature snapshot 和 prediction snapshot。**
5. 严禁未来信息泄漏（data leakage）。
6. 严禁用 Demo 数据补齐真实比赛缺失字段。
7. LLM 是“解释/综合/情景分析层”，**不是唯一的概率计算器**。
8. 最终概率必须来自可验证的数值模型或经过校准的 ensemble。
9. 所有模型必须支持时间序列回测。
10. 不追求单一 Accuracy 最大化，优先优化：
   - Log Loss
   - Brier Score
   - RPS
   - Calibration / ECE
   - ROI / Yield（仅作为模拟策略指标）
   - 最大回撤
11. 不允许为了漂亮的预测页面而人为提高 confidence。
12. 任何数据缺失都要产生 `data_quality` 和 `uncertainty`，而不是静默填值。
13. 每次预测都必须可审计、可复现。
14. 所有模型必须支持 `shadow mode`，新模型在证明优于 baseline 前不得自动替换生产模型。

---

# 1. 当前项目基线

当前项目已经具备比较好的产品骨架：

- FastAPI + Web 前端
- SQLite / MySQL
- TheSportsDB 赛程
- ESPN 公共数据
- API-Football / API-Sports 可选补充
- DeepSeek + GPT 双模型
- 赛前证据快照
- 首发 / 伤停
- 赔率
- Poisson
- 亚洲盘结算
- prediction / decision / simulation
- Brier / Log Loss / RPS
- 数据完整度
- 模拟资金与最大回撤
- 自动刷新任务
- 不可变 evidence / prediction snapshot

这些能力应当保留。

**真正需要加强的是：**

```text
数据质量
    ↓
特征工程
    ↓
球队实力模型
    ↓
进球模型
    ↓
比赛结果模型
    ↓
球员影响模型
    ↓
赔率/市场模型
    ↓
模型 Ensemble
    ↓
概率校准
    ↓
情景模拟
    ↓
最终预测
```

当前项目已经实现很多“产品层”和“证据层”能力，但距离真正的数据科学预测引擎还缺少一套系统化的 **feature store + model pipeline + backtesting framework**。

---

# 2. 总体目标架构

```text
                    DATA SOURCES
                         |
       --------------------------------------
       |          |          |       |       |
     Fixtures   Results     Stats    Odds   Players
       |          |          |       |       |
       --------------------------------------
                         |
                   RAW DATA STORE
                         |
                 Data Normalization
                         |
                  Feature Store
                         |
       ------------------------------------------------
       |             |             |                 |
   Team Rating     xG Engine   Player Impact     Market Model
       |             |             |                 |
       ------------------------------------------------
                         |
                  Prediction Models
       ------------------------------------------------
       |              |             |               |
    XGBoost        LightGBM      Poisson/DC      Sequence
       |              |             |               |
       ------------------------------------------------
                         |
                     Ensemble
                         |
                Probability Calibration
                         |
                Bayesian / Scenario Layer
                         |
                 Final Match Engine
                         |
       ------------------------------------------------
       |              |              |               |
      1X2          Goals          Asian        BTTS/O-U
       |              |              |               |
       ------------------------------------------------
                         |
                  LLM Explanation
                         |
                  Prediction API
                         |
       ------------------------------------------------
       |              |              |               |
    Dashboard     Backtest       Monitoring      Audit
```

---

# 3. 数据层：这是第一优先级

## 3.1 数据源分层

不要让任何单一 Provider 成为系统唯一真相。

建立：

```python
DataProvider
├── ScheduleProvider
├── MatchResultProvider
├── TeamStatsProvider
├── PlayerStatsProvider
├── InjuryProvider
├── LineupProvider
├── OddsProvider
├── WeatherProvider
└── EventProvider
```

每个 provider 返回统一 schema：

```python
{
    "provider": "...",
    "provider_event_id": "...",
    "retrieved_at": "...",
    "event_time": "...",
    "payload_hash": "...",
    "source_quality": 0.0
}
```

---

# 4. 建立统一数据模型

建议增加以下核心表。

## 4.1 matches

```text
matches
- id
- competition_id
- season_id
- home_team_id
- away_team_id
- kickoff_at
- status
- home_score
- away_score
- referee_id
- venue_id
```

---

## 4.2 match_events

如果 Provider 能提供事件：

```text
match_events
- id
- match_id
- minute
- second
- team_id
- player_id
- event_type
- event_subtype
- x
- y
- end_x
- end_y
- outcome
```

事件类型：

- shot
- goal
- assist
- pass
- key_pass
- tackle
- interception
- foul
- card
- substitution
- corner
- free_kick
- penalty

---

## 4.3 team_match_stats

```text
team_match_stats
- match_id
- team_id
- possession
- shots
- shots_on_target
- shots_inside_box
- shots_outside_box
- big_chances
- xg
- xa
- passes
- progressive_passes
- final_third_entries
- penalty_area_entries
- corners
- offsides
- fouls
- ppda
- high_turnovers
- deep_completions
```

---

# 5. Feature Store

这是整个项目最重要的新模块之一。

建议：

```text
apps/api/app/features/

team_features.py
player_features.py
match_features.py
market_features.py
form_features.py
tactical_features.py
fatigue_features.py
injury_features.py
weather_features.py
elo_features.py
xg_features.py
```

所有 feature 必须满足：

```text
feature_timestamp <= prediction_timestamp
```

绝不能使用比赛开始后才知道的信息。

---

# 6. 球队特征体系

不要只使用积分、胜负。

至少建立以下维度。

## 6.1 基础实力

```text
Elo
xG Rating
Attack Rating
Defense Rating
Home Rating
Away Rating
Squad Rating
```

---

## 6.2 近期状态

建立多窗口：

```text
Last 3
Last 5
Last 8
Last 10
Season
```

每个窗口计算：

```text
Goals For
Goals Against
xG
xGA
Shots
Shots on Target
Possession
PPDA
Big Chances
Set Pieces
```

---

# 7. Form Decay

不要：

```python
average(last_5)
```

使用指数衰减：

```text
weight = exp(-lambda * days_since_match)
```

这样：

```text
昨天的比赛 > 30天前的比赛
```

同时保留多个 half-life：

```text
7 days
14 days
30 days
60 days
120 days
```

---

# 8. 主客场拆分

必须区分：

```text
Home Attack
Home Defense

Away Attack
Away Defense
```

例如：

```text
Team A
Home xG = 2.15
Away xG = 1.38
```

不能把所有比赛直接平均。

---

# 9. xG Engine

这是必须重点建设的模块。

目标：

```text
Expected Goals
```

至少保留：

```text
team_xg
opponent_xga
home_advantage
shot_quality
big_chance_rate
box_entry_rate
set_piece_xg
penalty_xg
```

如果有 shot-level 数据，进一步建立：

```text
shot_xg
post_shot_xg
non_penalty_xg
```

---

# 10. xG 不应该只使用“过去进了多少球”

例如：

```text
Team A

过去 5 场：
进球 10
xG 15
```

模型应该知道：

```text
实际进球 < 创造机会能力
```

因此未来可能存在回归。

反之：

```text
进球 12
xG 6
```

可能存在过度兑现。

这类变量应该进入模型。

---

# 11. PPDA / Pressing

增加：

```text
PPDA
High Turnover
Possession Won Final Third
Pressure Success
Defensive Line Height（如果数据可得）
```

建立：

```text
Pressing Strength
```

并计算：

```text
Home Pressing vs Away Build-up
```

因为战术不是独立的：

```text
A 的高压能力
        ×
B 的后场出球能力
```

比单独看 PPDA 更有价值。

---

# 12. 球员影响模型

这是非常值得投入的一层。

不要：

```text
3人伤停 = -15%
```

这是错误的。

应该计算：

```text
Player Impact
```

考虑：

```text
Minutes Share
xG
xA
Progressive Pass
Key Pass
Defensive Action
Position
Replacement Quality
Team Dependency
```

---

# 13. Squad Availability Score

建立：

```text
Starting XI Strength
Bench Strength
Missing XI Strength
Replacement Gap
```

最终：

```text
Effective Squad Strength
```

例如：

```text
攻击保留率 91%
中场保留率 84%
防守保留率 97%
门将保留率 100%
```

而不是：

```text
伤停 4 人 → -4%
```

---

# 14. 首发确认后的二次预测

必须建立两个版本：

```text
T-24h prediction
T-6h prediction
T-1h prediction
T-30m prediction
Post-Lineup prediction
```

首发确认后：

```text
Prediction Revision
```

例如：

```text
T-24h

Home 51%
Draw 27%
Away 22%

↓

Confirmed XI

Home 57%
Draw 25%
Away 18%
```

记录变化：

```text
probability_delta
```

---

# 15. 赛程疲劳模型

建立：

```text
days_since_last_match
matches_last_7_days
matches_last_14_days
minutes_played_last_14_days
travel_distance
extra_time_recent
rotation_rate
```

进一步：

```text
Fatigue Score
```

---

# 16. 旅行因素

如果数据可得：

```text
distance
timezone_change
travel_days
away_trip_count
```

国际比赛尤其重要。

---

# 17. 天气

如果可靠数据源可用：

```text
temperature
rain
wind
humidity
pitch_condition
```

不要把天气影响写死。

模型需要自己学习：

```text
weather → goal rate
weather → shot quality
weather → possession
```

---

# 18. 战术 Matchup

建立：

```text
Team A Style
vs
Team B Style
```

例如：

```text
Possession
High Press
Low Block
Transition
Crossing
Set Piece
Build-up
Direct Play
```

形成：

```text
Tactical Matchup Score
```

重要：

**战术因素不能由 LLM 自由编造数字。**

必须来自数据或明确的规则。

---

# 19. Elo 2.0

传统 Elo 不够。

建立：

```text
Elo
xG-Elo
Home-Elo
Attack-Elo
Defense-Elo
Competition-adjusted Elo
```

例如：

```text
Overall Elo
Attack Elo
Defense Elo
```

---

# 20. 联赛强度

跨联赛时必须考虑：

```text
League Strength
Competition Strength
Promotion/Relegation
European Competition
```

例如：

```text
Premier League rating
La Liga rating
Serie A rating
Bundesliga rating
```

避免直接比较：

```text
英超球队 xG 1.8
vs
低级别联赛 xG 1.8
```

---

# 21. 比赛目标/动机

谨慎使用。

可以建立：

```text
match_importance
```

包括：

```text
relegation battle
title race
European qualification
knockout
first leg
second leg
must-win
rotation likelihood
```

但：

**不能直接写成“心理因素 +10%”。**

必须让模型从历史数据学习，或者只作为解释变量。

---

# 22. H2H

H2H 可以保留，但权重应该很低。

建议：

```text
H2H_last_3
H2H_last_5
H2H_recent
H2H_home
```

并设置 decay。

不要让 5 年前的比赛影响当前预测太多。

---

# 23. 赔率模型

赔率不是简单展示。

建立：

```text
Market Probability
```

步骤：

```text
Raw Odds
↓
Remove Overround
↓
Normalized Probability
```

例如：

```text
Home 2.00
Draw 3.50
Away 4.00
```

转成去水概率。

---

# 24. 赔率动态

记录：

```text
opening_odds
current_odds
closing_odds
odds_change
odds_velocity
odds_volatility
```

尤其：

```text
T-24h
T-12h
T-6h
T-1h
T-30m
```

---

# 25. Market Model

建立：

```text
market_model
```

输入：

```text
market_probability
odds_movement
liquidity_proxy
bookmaker_count
consensus_probability
```

输出：

```text
market_prior
```

注意：

**市场概率是一个 feature / prior，不应该无脑覆盖 AI。**

---

# 26. 模型体系

不要只有一个模型。

推荐：

```text
Model A:
Poisson / Dixon-Coles

Model B:
XGBoost

Model C:
LightGBM

Model D:
Logistic Regression

Model E:
Sequence Model

Model F:
Market Model
```

然后：

```text
Ensemble
```

---

# 27. Poisson / Dixon-Coles

优先实现：

```text
Independent Poisson
↓
Dixon-Coles correction
↓
Bivariate Poisson（可选）
```

预测：

```text
P(Home Goals = k)
P(Away Goals = k)
```

最终生成：

```text
Correct Score
1X2
Over/Under
BTTS
Asian Handicap
```

这样所有市场共享一个概率世界，而不是每个市场单独瞎猜。

---

# 28. XGBoost / LightGBM

主要处理：

```text
非线性
交互
大量 tabular features
```

输入可以达到：

```text
100-500 features
```

但：

**feature 多 ≠ feature 好。**

必须通过：

```text
feature importance
SHAP
ablation test
```

筛选真正有效的变量。

---

# 29. Sequence Model

LSTM / Transformer 不应该直接取代传统模型。

用于：

```text
最近 N 场比赛
```

学习：

```text
form trajectory
```

例如：

```text
下降
↓
下降
↓
反弹
↓
持续上升
```

这比简单：

```text
Last 5 average
```

更有价值。

---

# 30. Ensemble

建议第一版：

```text
Poisson/DC
       30%

XGBoost
       30%

LightGBM
       20%

Elo / Rating
       10%

Market
       10%
```

**不要永久写死权重。**

后续使用 validation data 学习 ensemble weights。

---

# 31. Stacking

最终阶段：

```text
Base Models
    ↓
Out-of-Fold Predictions
    ↓
Meta Model
    ↓
Final Probability
```

Meta model 可以：

```text
Logistic Regression
```

优先简单、可解释。

---

# 32. 防止数据泄漏

这是整个项目的最高风险之一。

错误：

```text
随机 train/test split
```

正确：

```text
Train:
2018-2021

Validation:
2022

Test:
2023
```

或者 rolling origin：

```text
Train 2018-2020
Test 2021

Train 2018-2021
Test 2022

Train 2018-2022
Test 2023
```

---

# 33. Feature Leakage 检查

每个 feature 必须有：

```python
available_at
```

并保证：

```python
available_at <= kickoff_at
```

建立自动测试：

```text
test_no_future_data_leakage
```

如果 feature 的时间晚于预测时间：

```text
FAIL
```

---

# 34. Out-of-Fold

尤其是：

```text
xG prediction
goal expectation
rating prediction
```

进入下一级模型时，必须使用：

```text
Out-of-Fold prediction
```

不能把训练集内拟合结果直接作为 feature。

否则会产生 stacking leakage。

---

# 35. Probability Calibration

这是项目必须重点升级的部分。

模型输出：

```text
Home 0.72
Draw 0.18
Away 0.10
```

不代表真实概率就是 72%。

必须校准。

候选：

```text
Platt Scaling
Isotonic Regression
Temperature Scaling
Dirichlet Calibration
```

第一版建议：

```text
Isotonic
```

+ validation set。

---

# 36. Calibration Dashboard

增加：

```text
Reliability Diagram
Expected Calibration Error
Brier Score
Log Loss
RPS
```

例如：

```text
模型预测 70-80%

实际命中:
74.2%
```

说明 calibration 良好。

---

# 37. Confidence 不应该是 AI 自己说的

不要：

```text
GPT:
confidence = 8/10
```

改成：

```text
Confidence =
data completeness
+
model agreement
+
calibration
+
uncertainty
+
lineup certainty
```

例如：

```text
Data Quality      92
Model Agreement   84
Lineup Certainty  70
Market Agreement  76
Historical Skill  81

Final Confidence  82
```

---

# 38. Prediction Uncertainty

不仅输出：

```text
Home 61%
```

还输出：

```text
uncertainty:
±6%
```

或者：

```text
Home:
61%

credible interval:
55-67%
```

模型越不确定：

```text
no_bet / no_action
```

---

# 39. Monte Carlo

使用进球模型：

```text
Expected Home Goals
Expected Away Goals
```

模拟：

```text
10,000 - 100,000
```

得到：

```text
1X2
Correct Score
O/U
BTTS
Asian Handicap
```

注意：

Monte Carlo 不是“让模型更准”，它只是把概率分布传播到不同市场。

---

# 40. Scenario Engine

这是项目非常值得做的高级功能。

例如：

```text
Scenario A:
正常首发

Scenario B:
核心前锋缺阵

Scenario C:
核心中卫缺阵

Scenario D:
主队先领先

Scenario E:
客队先领先
```

输出：

```text
Scenario Probability
```

---

# 41. 比赛状态模型

后期可以加入：

```text
0-0 15'
1-0 30'
0-1 60'
```

实时更新：

```text
live xG
red card
possession
shots
game state
```

最终成为：

```text
Pre-match Model
+
Live Model
```

但这是第二阶段，不要第一版就做。

---

# 42. LLM 的正确定位

LLM 不应该直接负责：

```text
胜率 = 67%
```

LLM 更适合：

```text
Evidence synthesis
Tactical interpretation
Risk explanation
Scenario explanation
Natural language report
```

输入：

```json
{
  "model_probability": 0.62,
  "xg_edge": 0.41,
  "elo_edge": 78,
  "injury_impact": -0.12,
  "lineup_quality": 0.91,
  "market_probability": 0.55
}
```

然后让 LLM：

```text
解释为什么模型倾向主队
```

而不是：

```text
让 GPT 自己计算 62%
```

---

# 43. 双 LLM 继续保留

可以继续：

```text
DeepSeek
GPT
```

但输出必须结构化：

```json
{
  "tactical_view": "...",
  "key_factors": [],
  "risk_factors": [],
  "scenario_analysis": [],
  "contradictions": []
}
```

然后后端决定：

```text
probability
market
EV
decision
```

---

# 44. 增加 Model Disagreement

非常重要。

例如：

```text
Poisson:
Home 58%

XGBoost:
Home 64%

Elo:
Home 55%

Market:
Home 51%

LLM A:
Home

LLM B:
Draw
```

这不是坏事。

这是：

```text
Disagreement Signal
```

可以直接进入 uncertainty。

---

# 45. 最终 Prediction Object

建议统一：

```json
{
  "match_id": "...",
  "prediction_version": "...",
  "model_version": "...",
  "feature_version": "...",

  "probabilities": {
    "home": 0.58,
    "draw": 0.25,
    "away": 0.17
  },

  "expected_goals": {
    "home": 1.72,
    "away": 0.91
  },

  "score_distribution": {},

  "markets": {
    "btts_yes": 0.51,
    "over_2_5": 0.57
  },

  "uncertainty": 0.08,

  "data_quality": 0.91,

  "model_agreement": 0.76,

  "key_factors": [],

  "risk_factors": [],

  "evidence_snapshot_id": "...",

  "created_at": "..."
}
```

---

# 46. 数据质量评分

建议拆成：

```text
Schedule Quality
Team Stats Quality
Player Quality
Injury Quality
Lineup Quality
Odds Quality
Event Data Quality
Weather Quality
```

最终：

```text
Data Quality Score
```

并明确：

```text
90-100 Excellent
75-89 Good
60-74 Limited
<60 Insufficient
```

低于阈值：

```text
Prediction only
```

不要自动执行策略。

---

# 47. No Bet / No Action Engine

应该升级成：

```text
NO_DATA
LOW_CONFIDENCE
MODEL_DISAGREEMENT
STALE_ODDS
LOW_EDGE
UNCONFIRMED_LINEUP
HIGH_UNCERTAINTY
INSUFFICIENT_SAMPLE
```

这比强行预测更重要。

---

# 48. 回测系统

增加：

```text
BacktestRunner
```

支持：

```text
date_from
date_to
competition
model_version
feature_version
strategy_version
```

输出：

```text
Accuracy
Log Loss
Brier
RPS
ECE
ROI
Yield
Max Drawdown
Sharpe-like metric
Coverage
Abstention Rate
```

---

# 49. Baseline 必须存在

每次新模型都必须对比：

```text
Baseline 1:
League majority

Baseline 2:
Home advantage baseline

Baseline 3:
Elo

Baseline 4:
Poisson

Baseline 5:
Market implied probability
```

只有超过 baseline 才能升级。

---

# 50. 重点：不要只和旧模型比

最重要的是：

```text
Model
vs
Closing Market
```

因为市场本身是非常强的 benchmark。

如果模型：

```text
Accuracy 58%
```

但市场：

```text
Accuracy 61%
```

不能说模型优秀。

---

# 51. Champion / Challenger

建立：

```text
Champion
    ↓
当前生产模型

Challenger
    ↓
新模型
```

新模型必须：

```text
rolling backtest
+
calibration
+
market benchmark
```

通过后才能替换。

---

# 52. Model Registry

建立：

```text
model_registry

model_id
model_type
version
training_start
training_end
feature_version
hyperparameters
metrics
artifact_path
status
created_at
```

状态：

```text
candidate
shadow
champion
retired
```

---

# 53. Feature Registry

同样建立：

```text
feature_registry

feature_name
version
description
source
available_at_rule
formula
owner
status
```

这样以后不会出现：

```text
“这个 xG 到底怎么计算的？”
```

---

# 54. SHAP

XGBoost / LightGBM 增加：

```text
SHAP
```

页面展示：

```text
Top Positive Factors

+ Home xG
+ Elo
+ Home Advantage
+ Opponent xGA

Top Negative Factors

- Missing striker
- Fixture congestion
- Away defensive strength
```

---

# 55. Feature Ablation

必须支持：

```text
remove odds
remove injuries
remove xG
remove Elo
remove lineup
remove weather
```

然后重新回测。

这样可以回答：

> 到底什么数据真的有用？

而不是凭感觉加指标。

---

# 56. 特征分组实验

至少建立：

```text
Experiment A:
Basic

Experiment B:
Basic + Elo

Experiment C:
Basic + Elo + xG

Experiment D:
+ Player

Experiment E:
+ Odds

Experiment F:
+ Lineup

Experiment G:
Full
```

最终做：

```text
Incremental Performance Table
```

---

# 57. 重点数据指标清单

## Team

```text
Elo
xG
xGA
npxG
npxGA
Goals
Shots
Shots on target
Big chances
Possession
PPDA
High turnovers
Progressive passes
Deep completions
Penalty area entries
Set piece xG
Corners
```

## Player

```text
Minutes
xG
xA
npxG
Shots
Key passes
Progressive passes
Progressive carries
Tackles
Interceptions
Duels
Aerials
Goalkeeper PSxG
```

## Match Context

```text
Home/Away
Rest days
Travel
Fixture congestion
Competition
Match importance
Weather
Referee
```

## Market

```text
Opening odds
Current odds
Closing odds
Overround
Market probability
Odds movement
Market consensus
```

---

# 58. 第一阶段不要做太多

建议 MVP 只实现：

```text
1. Elo
2. xG
3. Rolling Form
4. Home/Away
5. Rest/Fatigue
6. Player Availability
7. Odds normalization
8. Poisson/Dixon-Coles
9. XGBoost
10. Probability Calibration
11. Ensemble
12. Temporal Backtest
```

这 12 项完成后，再增加复杂模型。

---

# 59. 第二阶段

加入：

```text
LightGBM
LSTM / Transformer
Tactical Matchup
Player Impact
Weather
Referee
Market Movement
Scenario Engine
SHAP
```

---

# 60. 第三阶段

加入：

```text
Live Prediction
Live xG
State-space model
Player tracking
Computer Vision
Pitch control
Possession chains
Graph Neural Network
```

---

# 61. 推荐目录

```text
apps/api/app/

data/
├── providers/
│   ├── thesportsdb.py
│   ├── espn.py
│   ├── api_football.py
│   └── odds.py
│
├── normalization/
│   ├── teams.py
│   ├── players.py
│   └── matches.py
│
features/
├── team.py
├── player.py
├── xg.py
├── elo.py
├── form.py
├── fatigue.py
├── lineup.py
├── injury.py
├── odds.py
└── tactical.py
│
models/
├── poisson.py
├── dixon_coles.py
├── elo.py
├── xgboost_model.py
├── lightgbm_model.py
├── sequence_model.py
├── ensemble.py
└── calibration.py
│
backtest/
├── runner.py
├── temporal_split.py
├── metrics.py
├── benchmarks.py
└── reports.py
│
experiments/
├── registry.py
├── ablation.py
└── feature_importance.py
│
prediction/
├── engine.py
├── scenario.py
├── uncertainty.py
└── decision.py
```

---

# 62. 数据库新增表

至少：

```text
feature_snapshots
feature_values

model_registry
model_runs
model_predictions

backtest_runs
backtest_predictions
backtest_metrics

calibration_models

odds_snapshots

player_match_features
team_match_features

prediction_revisions

experiments
experiment_results
```

---

# 63. API 建议

增加：

```text
GET /api/predictions/{match_id}

GET /api/predictions/{match_id}/history

GET /api/features/{match_id}

GET /api/models

GET /api/models/{model_id}

GET /api/backtests

GET /api/backtests/{run_id}

GET /api/calibration

GET /api/experiments

GET /api/feature-importance
```

---

# 64. 页面建议

比赛详情新增：

```text
Overview
├── Final Probability
├── Expected Goals
├── Correct Score
├── Market
└── Confidence

Data
├── Team
├── Player
├── Injury
├── Lineup
├── Odds
└── Data Quality

Model
├── Poisson
├── XGBoost
├── Elo
├── Market
├── Ensemble
└── Disagreement

Explain
├── Positive Factors
├── Negative Factors
├── Tactical Matchup
└── Scenario

History
├── Previous Predictions
├── Probability Changes
└── Actual Result
```

---

# 65. 预测版本管理

同一比赛：

```text
Prediction #1
T-24h

Prediction #2
T-12h

Prediction #3
T-6h

Prediction #4
T-1h

Prediction #5
T-30m

Prediction #6
Confirmed XI
```

必须全部保留。

这样以后可以研究：

```text
什么时候预测最准确？
什么时候预测变化最大？
什么数据导致变化？
```

---

# 66. Prediction Drift

增加：

```text
probability_delta
```

例如：

```text
Home:

52%
→
54%
→
57%
→
61%
```

系统解释：

```text
+ lineup confirmed
+ market movement
+ opponent injury
```

---

# 67. 自动化流程

建议：

```text
T-48h
↓
基础数据

T-24h
↓
第一次模型

T-12h
↓
赔率 + 数据刷新

T-6h
↓
模型重算

T-60m
↓
阵容扫描

T-30m
↓
首发确认

T-20m
↓
最终模型

Kickoff
↓
Freeze pre-match prediction
```

---

# 68. Prediction Freeze

开赛后：

```text
pre_match_prediction
```

必须冻结。

实时模型：

```text
live_prediction
```

另存。

绝对不能修改历史赛前预测，否则回测会失真。

---

# 69. 预测结果存档

每场比赛最终保存：

```text
prediction
+
features
+
odds
+
lineup
+
evidence
+
model_version
+
feature_version
+
prompt_version
```

确保几年后仍然可以重现：

> 当时模型为什么给出这个概率？

---

# 70. 推荐的最终评分体系

不要只给：

```text
Confidence 8/10
```

改成：

```text
Prediction Quality

Probability:
Home 58%
Draw 25%
Away 17%

Data Quality:
91/100

Model Agreement:
78/100

Uncertainty:
Low

Lineup Certainty:
92/100

Market Agreement:
64/100

Historical Calibration:
Good
```

---

# 71. 最终输出示例

```text
Manchester City vs Arsenal

Model Probability

Home 57%
Draw 24%
Away 19%

Expected Goals

City 1.78
Arsenal 1.02

Most Likely Scores

1-0 14%
1-1 12%
2-0 11%
2-1 10%

Over 2.5
56%

BTTS
51%

Data Quality
93/100

Model Agreement
81/100

Uncertainty
Medium

Key Factors

+ Home xG advantage
+ Home Elo advantage
+ Arsenal away xGA
- Fixture congestion
- One key midfielder questionable

Prediction Revision

T-24h:
Home 53%

T-6h:
Home 55%

Confirmed XI:
Home 57%
```

---

# 72. 最重要的“准确率”策略

不要追求：

```text
预测谁赢
```

而要追求：

```text
Probability Quality
```

真正目标：

```text
预测 60%
→
长期真实发生约 60%
```

这就是 calibration。

---

# 73. 第二目标：模型是否发现信息增量

例如：

```text
Market:
Home 54%

Our Model:
Home 59%
```

模型真正提供的是：

```text
+5 percentage points
```

而不是单纯：

```text
Home Win
```

---

# 74. 第三目标：识别什么时候不要预测

优秀模型不是：

```text
每场都下注
```

而是：

```text
高质量数据
+
低不确定性
+
模型一致
+
概率校准良好
```

才允许：

```text
ACTION
```

否则：

```text
NO_ACTION
```

---

# 75. 最终决策公式

建议：

```text
Decision Score =
Probability Edge
×
Data Quality
×
Calibration Reliability
×
Model Agreement
×
Market Liquidity/Quality
×
Lineup Certainty
```

但这只是决策层，不要用它反向修改真实概率。

---

# 76. 不要把 EV 和 Probability 混在一起

必须分开：

```text
Prediction

P(Home)=58%
```

和：

```text
Market

Implied P(Home)=53%
```

以及：

```text
Edge

+5%
```

最后才是：

```text
Decision

BET / NO BET
```

如果项目仅做研究，也可以命名：

```text
ACTION / NO ACTION
```

---

# 77. 研究模式

强烈建议增加：

```text
Research Mode
```

只展示：

```text
Prediction
Probability
Uncertainty
Backtest
Calibration
```

不涉及资金策略。

---

# 78. 最重要的实验路线

## Experiment 001

```text
Baseline
```

仅：

```text
Home/Away
Elo
Recent Form
```

---

## Experiment 002

加入：

```text
xG
```

---

## Experiment 003

加入：

```text
Poisson/DC
```

---

## Experiment 004

加入：

```text
XGBoost
```

---

## Experiment 005

加入：

```text
Player Availability
```

---

## Experiment 006

加入：

```text
Odds
```

---

## Experiment 007

加入：

```text
Lineup
```

---

## Experiment 008

加入：

```text
Calibration
```

---

## Experiment 009

加入：

```text
Ensemble
```

---

## Experiment 010

加入：

```text
Sequence Model
```

每一步必须保存：

```text
Log Loss
Brier
RPS
ECE
Accuracy
Coverage
```

---

# 79. 成功标准

不要要求：

```text
Accuracy > 65%
```

因为足球预测没有这么简单。

第一阶段成功标准：

```text
1. 无未来数据泄漏
2. 完整 temporal backtest
3. 概率可校准
4. Ensemble 优于单模型
5. xG 比纯进球数据有增量
6. lineup 数据有增量
7. odds 有独立增量
8. 新模型稳定优于 baseline
9. 所有预测可复现
10. 数据质量可量化
```

---

# 80. Codex 实施顺序（Round 3-8，strict no-ML）

Round 1/2 已完成审计、数据完整性、逐特征时间边界、不可变预测修订和可复现基础。后续只能复用并增量扩展现有 P0-P17 与 Round 2 数据结构。

## Round 3 — Feature Engine v2

实现：

```text
extend existing Round 2 feature snapshots
feature registry and feature version protocol
point-in-time Elo/form/xG/xGA/home-away/fatigue/player/lineup/quality features
legacy learned-path freeze inventory
fail-closed v2 production deny gate for legacy learned/calibration paths
fail-closed rejection of LLM-generated probability/weight/goal/stake values
```

`Feature Store` 在 v2 中仅表示对现有 Round 2 feature snapshot 层的增量扩展。禁止创建第二套特征表、快照链、时间语义或平行数据系统。xG 只能来自可追溯供应商数据，或固定、显式且已版本化的计算公式。

## Round 4 — Transparent Statistical Engines

实现：

```text
Elo
Poisson
Dixon-Coles
Goal Distribution
```

公式、输入、估计过程、状态、参数、边界和版本必须可审计、可回放。禁止增加通用 feature-to-outcome learner，禁止以“统计增强”为名引入训练型分类器或回归器。

## Round 5 — Market Prior

实现：

```text
odds normalization
de-vig
market movement snapshots
versioned market prior
```

市场数据必须服从 `available_at <= prediction_cutoff_at`。市场概率是可审计输入和 benchmark，不是训练标签或自动调参信号。

## Round 6 — Deterministic Probability Fusion and Calibration

保留并实现：

```text
Calibration Framework
Calibration Evaluation
Calibration Version Protocol
Probability Audit
Historical Reliability Analysis
```

当前只允许确定性 rule-based calibration：概率归一化、固定权重的市场概率融合、按固定数据质量条件切换权重、边界限制和显式置信度修正。每条规则必须有公式、输入、边界、版本和回测结果。

权重只能由人工审查后配置发布，或按预先声明的数据质量条件确定。历史评估只用于审计和决策，不得自动拟合、搜索或更新权重。Platt Scaling、Isotonic Calibration、Temperature Scaling 及任何依赖历史样本拟合参数的校准算法不属于 v2。

## Round 7 — Point-in-Time Backtest

实现：

```text
chronological evaluation
rolling-origin replay
baseline comparison
fixed-rule ablation
probability and calibration audit
```

每次回测必须复用生产时间边界和版本化快照。禁止训练集、OOF、参数搜索、超参数优化、Stacking、Meta Model 或通过回测结果自动调整线上规则。

## Round 8 — AI Analyst

LLM 只读取不可变的 prediction、feature、evidence、market 和 revision 审计链，用于：

```text
evidence-backed explanation
news structuring
revision-difference explanation
post-match review
```

LLM 禁止生成、修改或校准概率，禁止选择融合权重，禁止覆盖赛前预测。UI 仅做呈现审计链所需的最小增量，不在本路线中大改。

---

# 81. Codex 必须新增测试

按对应轮次与改动风险增量增加：

```text
test_feature_temporal_integrity
test_no_future_leakage
test_feature_store_reuses_round2_snapshot
test_rolling_features_do_not_use_future_matches
test_odds_normalization
test_market_prior_respects_prediction_cutoff
test_poisson_probability_sum
test_dixon_coles_probability_sum
test_prediction_probability_sum
test_probability_fusion_is_deterministic
test_probability_fusion_rule_versioning
test_rule_based_calibration_formula
test_rule_based_calibration_boundaries
test_rule_based_calibration_versioning
test_probability_audit
test_calibration_evaluation
test_historical_reliability_analysis
test_point_in_time_backtest
test_rolling_origin_replay
test_prediction_freeze
test_prediction_reproducibility
test_statistical_bundle_replay
test_market_prior_is_applied_once
test_v2_production_rejects_legacy_ml
test_v2_production_rejects_llm_numeric_prediction
```

`test_oof_predictions` 已从 v2 验收范围永久移除；不得新增或维护任何以 OOF、训练型 learner 或拟合型 calibration 为目标的 v2 测试。

---

# 82. 代码质量要求

所有影响概率的输入和变换必须来自以下三类之一：

```text
带时间边界和来源的数据
可审计、可版本化的透明统计公式
可审计、可版本化的确定性规则
```

禁止球队特例、无来源常量、隐藏训练 artifact、运行时自适应权重和无法回放的人工修正。统计引擎和规则 bundle 必须能通过版本与内容 hash 定位并确定性重放。

---

# 83. Rule-based Calibration 约束

允许直接修正概率，但必须同时满足：

1. 显式写出公式及适用条件。
2. 输入全部满足 prediction cutoff。
3. 权重、阈值和边界由版本化配置给出，不从历史样本拟合。
4. 输出归一化且边界行为有测试。
5. 每个版本可在相同快照上确定性重放和回测。

允许的例子包括：

```text
p_stat_norm_i = max(0, p_stat_i) / sum_j(max(0, p_stat_j))
p_fused_i = normalize(w_stat * p_stat_norm_i + w_market * p_market_i)
p_adjusted_i = normalize(p_fused_i * adjustment_i)
p_bounded_i = epsilon + (1 - 3 * epsilon) * p_adjusted_i
p_final_i = (1 - shrinkage) * p_bounded_i + shrinkage * prior_i
```

其中 `w_stat >= 0`、`w_market >= 0`、`w_stat + w_market = 1`、`epsilon` 位于 `[0, 1/3)`、`shrinkage` 位于 `[0, 1]`、`adjustment_i > 0`，且 `p_market` 与非市场 `prior` 已归一化。零分母或缺失输入只能使用版本化固定回退。市场概率在同一 revision 中只允许融合一次，不得在收缩阶段再次作为 prior。所有权重和边界必须是人工审查后发布的版本化配置，或由预先声明的数据质量规则选择；禁止通过历史结果拟合、网格搜索或在线学习得到。

---

# 84. 关于数据源

优先级保持为：

```text
Official / Licensed
        ↓
Reliable API
        ↓
Established public data
        ↓
Versioned derived metrics
        ↓
LLM interpretation
```

LLM 不得生成不存在的数据。缺少供应商 xG 时使用 `null`；只有在固定公式、输入来源、时间边界和版本全部明确时，才允许输出单独命名的 derived xG，且不得与供应商 xG 混用。

---

# 85. 关于参考项目

参考项目仅可用于数据来源、时间切分、数据溯源、透明统计公式、回测和审计工程思路。其 XGBoost、LightGBM、LSTM、Transformer、OOF、Stacking、SHAP、Optuna、训练型 calibration 等实现均不属于 v2 可借鉴范围。

任何参考方案都不能覆盖 [`Football_AI_v2_no_ML_architecture_plan.md`](./Football_AI_v2_no_ML_architecture_plan.md) 的边界。

---

# 86. 最终产品定位

产品定位仍为：

> **Football Intelligence & Prediction Engine**

核心能力固定为：

```text
Data Intelligence
+
Transparent Statistical Modeling
+
Deterministic Rule System
+
Market Intelligence
+
Player Intelligence
+
Scenario Simulation
+
LLM Explanation
+
Historical Validation
```

Football AI v2 不包含任何需要训练参数的机器学习组件。

---

# 87. 最终目标

每场比赛输出一个可审计、可复现的 `Probability Object`：

```text
Match
  -> Evidence and Feature Snapshots
  -> Transparent Statistical Engines
  -> Market Prior
  -> Deterministic Fusion
  -> Rule-based Calibration
  -> Data Quality and Uncertainty
  -> Immutable Prediction Revision
  -> Historical Validation
  -> LLM Explanation
```

每个箭头都必须有输入来源、prediction cutoff、公式或规则版本以及审计记录。

---

# 88. 最终原则

1. 数据比 AI 重要，时间边界比数据量重要。
2. 概率必须来自透明统计引擎和确定性规则。
3. Calibration 保留框架、评估、版本和审计，不做参数拟合。
4. 回测只做 point-in-time 验证，不承担训练或自动调参。
5. 市场是 benchmark 和显式 prior，不是隐藏训练器。
6. LLM 只做解释和信息结构化，不制造数据、概率或权重。
7. 数据缺失应降低 data quality 和 confidence，不得伪造填充。
8. 不确定时允许 `NO_ACTION`。
9. 每次预测及其全部 revision 必须可复现。
10. 任何数据拟合型 calibration 或其他训练组件都必须另行评估，且不属于当前 v2 no-ML 架构。

---

# 89. 给 Codex 的最终任务

Round 3 起只按以下顺序执行：

```text
1. Treat the no-ML architecture plan as the sole authority
2. Preserve existing P0-P17 and Round 2 audit chains
3. Extend the existing feature snapshot layer; do not build a parallel store
4. Add versioned point-in-time features and a feature registry
5. Freeze and inventory legacy learned-model paths; fail closed if v2 production attempts to execute them or accept LLM-generated numeric predictions
6. Add transparent Elo, Poisson, Dixon-Coles, and goal distribution engines
7. Add odds normalization, de-vig, movement snapshots, and market prior
8. Add deterministic probability fusion with explicit versioned formulas
9. Add rule-based calibration framework, evaluation, version protocol, and audit
10. Add historical reliability analysis without fitting parameters
11. Add chronological and rolling-origin deterministic replay
12. Compare fixed rules and statistical baselines without OOF or parameter search
13. Restrict LLM to evidence-backed explanation and post-match review
14. Add only the tests required by the corresponding no-ML round
15. Document formulas, versions, cutoff semantics, replay inputs, and audit results
```

禁止把旧文档中的 ML、OOF、Stacking、Meta Model、SHAP、Optuna 或拟合型 calibration 项目重新加入待办。

---

# 90. 最重要的一句话

> **Football AI v2 = 更可靠的数据 + 严格时间边界 + 透明统计模型 + 确定性规则 + 市场信息 + 可审计回测 + LLM 解释。**
>
> **Football AI v2 不训练任何机器学习组件。**

---

## References

- `dhj1997/football-ai`：当前项目基线与现有架构。
- 外部足球预测项目：仅参考数据、统计公式、时间序列验证、概率审计和工程组织方式。
- [`Football_AI_v2_no_ML_architecture_plan.md`](./Football_AI_v2_no_ML_architecture_plan.md)：Round 3 及后续唯一有效的架构与路线。

**所有包含训练型模型、OOF、参数搜索或拟合型 calibration 的参考内容仅作为历史研究记录，不构成 v2 实施建议。**
