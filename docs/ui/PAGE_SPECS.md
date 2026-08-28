# Page Specifications

## 1. Schedule Dashboard

### User questions
Within five seconds the user should know:
1. What matches are available?
2. When are they played?
3. Which league are they in?
4. Which matches are ready for analysis?
5. What action can be taken?

### Desktop layout
`Page Header -> Date Tabs -> League Filters -> Main Schedule + Summary Rail`

The match card should contain:
- competition
- home team and crest
- kickoff/status
- away team and crest
- score when applicable
- analysis/evidence readiness
- clear entry affordance

The right-side summary should contain:
- match count
- competition distribution
- analysis-ready count
- important data freshness state

Do not duplicate information already present in the match list.

## 2. Match Detail

### Hierarchy
1. Match Hero
2. Data readiness strip
3. Pre-match readout
4. Tab navigation
5. Detailed evidence

### Match Hero
Show both teams with equal visual weight. Kickoff/status must be central.

### Readiness strip
Represent:
- evidence completeness
- recent form
- injuries
- lineups
- odds
- prediction state

The existing meaning of missing or partial evidence must remain unchanged.

### Tabs
Recommended grouping:
- Overview
- AI Analysis
- Evidence / H2H
- Squad / Lineups
- Odds

Do not hide important missing-data warnings behind tabs.

## 3. AI Analysis

Do not present the model output as one large wall of text.

Layout:
- model selector or side-by-side comparison
- probability row: home / draw / away
- final stance
- confidence/agreement
- concise thesis
- supporting factors
- risk factors
- evidence caveats
- simulation decision when available

DeepSeek and GPT outputs must remain separately identifiable and auditable.

## 4. Performance

Top row:
- current bankroll
- realized P/L
- ROI
- hit rate
- max drawdown

Then:
- model comparison
- bankroll/equity curve
- outcome distribution
- simulated ledger
- prediction settlement records

The visual design must make the two independent model accounts comparable without implying real-money execution.

## 5. Standings

Priorities:
1. rank
2. team
3. played
4. W/D/L
5. goals
6. goal difference
7. points

Enhancements:
- sticky table header
- compact rows
- team crest
- emphasized points
- responsive overflow strategy

Avoid large colored table rows. If qualification/relegation zones are represented, use subtle markers.

## 6. Admin / Automation

This is an operational page.

Priorities:
- system freshness
- job status
- last/next run
- failure visibility
- manual action

Dangerous or manual actions must have clear feedback and disabled/loading states.
