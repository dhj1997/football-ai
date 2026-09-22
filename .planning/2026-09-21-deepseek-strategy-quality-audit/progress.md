# Progress

## 2026-09-21

- Started a read-only DeepSeek strategy-quality and prompt audit.
- Defined the initial overnight analysis window in Asia/Shanghai and planned a
  cross-check by bet, fixture, and settlement timestamps.
- Reviewed relevant project memory and identified prior settlement-loss and
  strategy-ledger work as the next evidence sources before querying production.
- Read both prior plans. Confirmed that loss analysis existed, identified an
  execution-boundary defect, and separated ledger truth from forecast metrics.
- Next: inspect the deployed prompt/contract and query current production rows
  to isolate post-fix overnight performance.
- Located the DeepSeek provider, shared prompt contract, prediction pipeline,
  and all relevant read-only report endpoints.
- Read the complete DeepSeek request client and prompt contract. Recorded both
  its strong structural controls and its missing calibration/grounding rules.
- Next: trace how LLM probabilities and recommendations influence deterministic
  market assessment and execution.
- Traced the successful-model branch: LLM probabilities replace the baseline
  probabilities before market assessment. This elevated probability
  calibration to the primary investigation target.
- Located the deterministic edge, evidence-quality, stake, exposure, and
  drawdown controls; continuing through candidate construction to verify which
  probability stream each control receives.
- Confirmed the prompt's bet recommendation is advisory only and low model
  confidence is warning-only in the initial market decision.
- Confirmed the second-stage portfolio gates and LLM 1X2 market shrinkage, plus
  the remaining Asian-handicap and confidence gaps.
- Phase 1 code inventory is nearly complete; next query production reports and
  row-level evidence for the overnight loss window.
- Queried current production strategy performance. DeepSeek is sharply
  negative, underperforms the market on Brier, and remains shadow-only.
- Retrieved the complete settled-bet field contract for row-level attribution.
- The first full row-detail request hit the public proxy's 4-second timeout.
  Switched to the internal FastAPI listener rather than retrying the same path.
- Internal row audit identified the latest DeepSeek loss as a September 9
  historical invalid bet settled during September 20 stale-score recovery.
- Next: calculate the complete overnight all-model settlement contribution and
  separate historical repair effects from newly generated bets.
- Reconstructed the overnight settlement window: five rows, `-289.92` total,
  with `-189.92` from ChatGPT and `-100` from the old DeepSeek invalid bet.
- Audited all nine overnight DeepSeek decision rows. Every row failed closed
  and no new DeepSeek bet was placed.
- Phase 1 completed and Phase 2 is in progress; next identify provider failures
  and quantify the historical DeepSeek loss subgroups.
- Read the stored AI payload for all nine overnight DeepSeek rows. Classified
  failures as provider rate limit/server errors/timeouts plus one schema drift.
- Aggregated current DeepSeek-channel reliability and prompt-token usage, and
  read the complete quality-gate checks from production metrics.
- Next: stratify settled prediction accuracy by completed AI versus fallback.
- Split all settled DeepSeek-channel evaluation rows by model version. The
  successful LLM subset is near but still slightly worse than market; fallback
  rows account for most of the poor headline score.
- Split settled bets by successful LLM versus blocker-coded fallback and
  compared each successful model recommendation with the executed direction.
- Found four recommendation/execution mismatches, all losses, versus one
  aligned half-win; recorded the small-sample limitation.
- Confirmed recommendation/execution mismatch remains possible in the deployed
  candidate path; only optional Poisson candidates follow AI direction.
- Compared current behavior with ADR-015, the earlier hard-no-bet design, the
  current regression test, and the authoritative strict no-ML architecture.
  Identified a direct contract drift across those artifacts.
- Read the complete model-input shape and linked the oversized 12k-48k token
  requests to 70-player evidence plus the full feature manifest.
- Verified safe production settings and quality-gate references. Production
  uses a 3% edge threshold, and shadow-only quality state is reporting-only.
- Reviewed Asian-handicap settlement mapping and confirmed the LLM cover pair
  reweights deterministic settlement mass but receives no market shrinkage.
- Completed source-line verification for prompt construction, probability
  replacement, backend market selection, low-confidence warning behavior,
  shrinkage, regression contract, and v2 architecture boundary.
- All four audit phases are complete. No production data, model settings,
  strategy code, bets, executions, or settlements were changed.
