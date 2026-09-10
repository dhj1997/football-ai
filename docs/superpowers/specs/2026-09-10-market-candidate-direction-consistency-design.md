# Market Candidate Direction Consistency Design

## Problem

The market decision layer currently selects the highest expected-value row from every priced market outcome. This can produce a contradictory 1X2 candidate: a model may forecast a strong home win while a low-probability, long-priced away win becomes the displayed candidate solely because its calculated EV is larger.

For Bayern Munich vs Bodo/Glimt, the model forecast was home 81%, draw 11%, away 8%. At away odds of 21.00, the arithmetic EV was `0.08 * 21 - 1 = 0.68`, so the system displayed away win as the considered 1X2 candidate even though the model outcome was home win. The anomaly gate blocked execution, but the candidate itself remained semantically inconsistent.

## Required Behavior

### 1X2

- The eligible 1X2 candidate must match the model's highest-probability outcome.
- Other 1X2 rows remain in `market_assessment.markets` for transparent market comparison.
- Non-matching 1X2 rows must not participate in candidate ranking or execution.
- If the matching outcome has insufficient or negative value, the result is no bet. The backend must not switch to a different 1X2 outcome merely because it has a higher EV.

### Asian Handicap

- Asian-handicap direction remains independent from the 1X2 predicted outcome.
- A home-win forecast may coexist with an away-handicap candidate when the model expects the home team to win without covering the offered line.
- Only handicap rows backed by the existing matching-line settlement or explicit handicap forecast logic remain eligible.

### Candidate Ranking and Display

- Rank only eligible candidates after applying market-specific direction rules.
- Continue showing every calculable market row in the odds-value table.
- `decision.considered_market` and `decision.considered_selection` identify the eligible direction evaluated by the backend, including a same-direction row that fails the value threshold so the no-bet reason remains inspectable.
- The UI displays an "odds candidate" only when the eligible direction has at least the existing minimum expected edge. Otherwise it displays no reasonable odds candidate while retaining the evaluated row and negative edge for diagnosis.
- When no eligible positive-value candidate exists, return no bet using the existing negative-edge or no-matching-market contract.
- Existing stale-odds, data-quality, anomaly, confidence, and risk gates remain unchanged.

## Implementation Scope

- Add a small eligibility filter in `apps/api/app/market_decision.py` before selecting the maximum-EV candidate.
- Reuse `predicted_outcome` for 1X2 direction matching and the existing handicap assessment semantics for handicap rows.
- Adjust the match-detail wording only if needed to distinguish the complete comparison table from the eligible candidate.
- Do not change model probabilities, EV formulas, odds ingestion, portfolio sizing, or settlement logic.

## Verification

- Regression: an 81% home forecast with away odds 21.00 must never select away win as the considered candidate.
- Regression: if the matching home-win row has negative EV, the decision must be no bet and the UI must show no odds candidate even when draw or away has positive EV.
- Regression: a home-win 1X2 forecast may still select away handicap when the handicap forecast supports that side at the matching line.
- Preserve existing market math and anomaly-gate tests.
- Run the focused market-decision tests and the directly affected API contract tests only.
