# Frontend Architecture

## Match Center 首屏
Match Header → AI Final Conclusion → Probability → Model Agreement → Key Reasons → Evidence → Form → H2H → Squad → Injury → Lineup → Odds → Models → Market Decision → Provenance。

## Competition UI
League：standings。
Knockout：stage、aggregate、qualification。
Continental：阶段、排名、晋级状态、淘汰赛路径。

## 组件拆分
FixtureWorkspace → Toolbar / List / Detail。
Detail → PredictionSummary / Evidence / Form / H2H / Squad / Lineup / Odds / ModelComparison / MarketDecision / Provenance。