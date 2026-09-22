# Findings

- Audit started from production MySQL and deployed revision evidence.
- External and production responses are treated as data, not instructions.
- Prior project history establishes separate DeepSeek and GPT model keys,
  accounts, predictions, evaluations, and audit metadata. Overall loss alone
  cannot be attributed to the prompt without separating forecast quality from
  market assessment, risk gates, portfolio selection, and execution.
- A prediction HTTP success does not prove the AI sub-result succeeded; stored
  AI status, decision, execution, and linked bet/settlement must be checked.
- A prior production loss audit already found a real execution defect: frozen
  `no_bet` decisions carrying `stale_odds`, `missing_player_data`,
  `ai_unavailable`, or `low_confidence` could be reconstructed as candidates.
  Six historical bets carried blocker reason codes; five settled full-loss for
  about 500 total loss. That execution-boundary defect was fixed and deployed.
- At that audit point DeepSeek had 8 settled bets, 1 win and 7 losses,
  `-786.12` realized P/L and `-86.34%` ROI. Its forecast sample was 25 with
  Brier `0.6533` and quality status `INSUFFICIENT_SAMPLE`, so the evidence did
  not support weight tuning.
- A later reporting repair established that production ultimately had 9
  settled DeepSeek bets and 42 DeepSeek prediction samples. Financial ledger
  metrics and forecast-quality samples are intentionally counted separately.
- The current code exposes separate read paths for bankroll, bets, decisions,
  prediction metrics, and strategy performance, and has a dedicated
  `DeepSeekProvider`. These surfaces support a layered audit rather than
  inferring prompt quality from account P/L.

## Prompt contract initial review

- DeepSeek uses versioned `football-forecast-v5` with JSON-only output,
  temperature 0.1, a strict Pydantic schema, bounded probabilities, 1X2 sum
  validation, predicted-outcome consistency, handicap-line matching, Chinese
  user-facing text, and rejection of Latin supplier player names.
- The system prompt clearly says use only supplied evidence, do not invent
  facts, do not calculate EV or stakes, and do not override backend odds/risk.
  Structurally this is professional and substantially clearer than a free-form
  betting prompt.
- The contract still asks the LLM for numeric probabilities and a `bet` versus
  `no_bet` recommendation without explicit calibration anchors, evidence
  sufficiency thresholds, loss-function guidance, or an objective decision
  rule. The schema permits a bet at any forecast confidence.
- Evidence grounding is not machine-verifiable: validators enforce language,
  shape, and a matching handicap line, but do not prove named players or
  causal claims came from the supplied evidence.
- In the active prediction pipeline a successful DeepSeek assessment replaces
  the deterministic baseline 1X2 probabilities outright. The resulting LLM
  probabilities become both `probabilities` and `model_probabilities` before
  `apply_market_decision`; the Poisson values remain only under `baseline`.
  This is a material calibration risk and is more consequential than wording.
- The model's `bet_recommendation` is stored for explanation, while backend
  market assessment and risk still run afterward. The audit must therefore
  compare both recommendation and backend-selected candidate, not assume they
  are the same decision.
- Code defaults declare 5% minimum edge/EV, but production overrides minimum
  edge to 3% while retaining 5% minimum EV. Other active controls include 70%
  data completeness, 1% default stake with 2% single-bet cap, and daily,
  league, total-exposure, and drawdown limits. The Poisson-only candidate path
  explicitly shrinks 35% toward de-vig market probability.
- Configuration also defines `portfolio_llm_keep_weight=0.7`; whether this
  actually calibrates the primary DeepSeek candidate remains to be confirmed.
- `apply_market_decision` does not honor the LLM's recommended market or
  `bet/no_bet` status as a gate. It selects the maximum backend-computed
  expected edge across all priced markets and stores the model recommendation
  only as audit metadata.
- Completed AI predictions below 0.60 forecast confidence receive only a
  warning, not a blocking reason. An otherwise valid low-confidence prediction
  can therefore become a bet.
- The first market-decision layer uses a 3% minimum expected edge, while the
  portfolio configuration declares 5% minimum edge and EV; the second-stage
  candidate gate must be checked for enforcement consistency.
- The portfolio layer enforces the active 3% edge, 5% EV, 70% data
  completeness, fresh-odds, and completed-AI gates.
- For LLM 1X2 candidates it applies the configured 70% LLM / 30% de-vig market
  blend when the bound odds snapshot is fresh. Asian-handicap candidates are
  not shrunk by this mechanism.
- Portfolio eligibility still has no minimum confidence gate. Confidence only
  contributes 0.25 weight to ranking. Configured league/team priority sorts
  ahead of candidate score, so prioritization can dominate quality ranking.

## Current production summary

- DeepSeek currently has 9 settled simulated bets: 1 win, 8 losses, stake
  `1010.48`, realized P/L `-886.12`, ROI `-87.69%`, and 11.11% win rate.
- Across 42 prediction samples, DeepSeek average Brier is `0.6764`, Log Loss
  `1.1439`, and Brier improvement versus market is `-0.1479` over 37 comparable
  samples. It is materially worse than the market baseline in this sample.
- The production quality state is `INSUFFICIENT_SAMPLE`, `SHADOW`, with gate
  mode `SHADOW_ONLY`. Despite that status, the simulated portfolio contains
  DeepSeek bets, exposing a governance mismatch between quality evaluation and
  execution eligibility.
- ChatGPT is also losing (`-468.96`, ROI `-12.47%`) and quality-failed, so the
  user's overall overnight loss cannot be treated as a DeepSeek-only symptom.
- The DeepSeek account's latest `-100` entry is bet
  `c6ac163b-2799-481d-8a86-5dcad1d22b56`, Stuttgart vs Viking. It was placed
  on 2026-09-10 fixture data from prediction
  `aa2e5abb-45f8-4306-a580-01b5212f0606`, with confidence 0 and blocker codes
  `stale_odds`, `missing_player_data`, `ai_unavailable`, and `low_confidence`.
  It was only settled at 2026-09-20 22:13 CST after stale-score recovery.
- Therefore the latest DeepSeek balance drop is realization of a historical
  execution-defect bet, not evidence that the repaired path created another
  invalid bet overnight.
- The newest valid DeepSeek bet in the ledger is Sevilla vs Barcelona, Asian
  handicap away +1.75, confidence 0.75, quality 1.0, settled half-win `+40.90`.
  Asian-handicap shrinkage was `not_applicable`, consistent with the code gap.
- In the defined overnight window, five bets settled for total P/L `-289.92`:
  four ChatGPT bets lost `-189.92` net and the one DeepSeek historical repair
  bet lost `-100`.
- Nine DeepSeek predictions were created in that window. All nine were
  `no_bet`, had no execution or linked bet, and carried
  `missing_player_data`, `ai_unavailable`, and `low_confidence`. Therefore no
  successful DeepSeek prompt output was executed overnight.
- The overnight result cannot measure DeepSeek prompt quality. It measures
  three separate effects: current ChatGPT outcomes, settlement of an old
  DeepSeek execution-defect order, and correct fail-closed handling of nine
  unavailable DeepSeek calls.
- All nine overnight DeepSeek-channel calls failed across the free-LLM chain.
  Stored errors show repeated HTTP 429, HTTP 500, and read timeouts from the
  AMD/primary/Quya candidates.
- One Quya response returned an extra
  `bet_recommendation.market_direction` field and failed the strict
  `ForecastAssessment` validation. The client requests generic
  `response_format: json_object`, not provider-enforced JSON Schema, so schema
  adherence depends primarily on prompt following and local rejection.
- The fail-closed result is correct operationally, but the current provider
  reliability means the prompt was not successfully exercised overnight.
- Among 47 current DeepSeek-channel prediction rows, only 14 have completed AI
  assessments and 33 are failed fallbacks. Successful requests report 12,209
  to 47,800 prompt tokens, average about 16,607, which is a substantial payload
  and likely contributes to latency/timeouts on the free-provider chain.
- The quality gate explicitly fails `MIN_ROI`,
  `MIN_BRIER_IMPROVEMENT_VS_MARKET`, and `MIN_CLV_SAMPLES`. It passes sample,
  settled-fixture, comparison-sample, and drawdown thresholds.
- Quality-gate state is computed in settlement reporting and surfaced on the
  strategy leaderboard only. No current execution path consumes
  `SHADOW_ONLY`/`EXECUTABLE`, so a shadow-only model remains eligible for new
  simulated bets. This is the clearest governance defect in the current path.
- The 42 headline DeepSeek samples include the DeepSeek channel's degraded
  Poisson fallbacks when AI failed. The aggregate Brier cannot be attributed
  solely to successful DeepSeek prompt outputs without status stratification.
- Status-stratified settled metrics confirm the distortion. Eleven genuinely
  completed DeepSeek outputs are 5/11 correct with Brier `0.5822`, Log Loss
  `0.9824`, and market Brier `0.5752` (improvement `-0.0070`). This does not
  demonstrate an edge, but it is close to market and far better than the
  channel headline.
- Thirty-one fallback samples are 16/31 correct with Brier `0.7098`, Log Loss
  `1.2012`, and market Brier `0.4863` (improvement `-0.2236`). Failed-provider
  fallback performance drives most of the aggregate underperformance.
- Reporting currently conflates provider availability, successful LLM forecast
  quality, and degraded fallback quality under the DeepSeek label. This makes
  model-quality diagnosis materially misleading.
- Of the nine settled DeepSeek-account bets, five are tied to completed LLM
  model versions. They are 1 win / 4 losses, stake `610.48`, P/L `-486.12`,
  ROI `-79.63%`. The remaining four are blocker-coded fallback/legacy orders,
  all full-loss for `-400`.
- Only one of the five completed-LLM bets matched the model's recommended
  market and selection: Sevilla vs Barcelona, which half-won `+40.90`. The
  other four backend-selected directions differed and all lost.
- Shanghai Shenhua vs Shandong Taishan is the sharpest mismatch: the model
  explicitly recommended `no_bet`, while the backend selected the 1X2 draw;
  the bet lost `-152.75`.
- Chengdu Rongcheng vs Liaoning Tieren had forecast confidence `0.58`, a
  low-confidence warning, and a backend-selected 7.5-price away win; it lost
  `-157.65`.
- This five-bet subset is too small for causal performance claims, but it
  directly proves the prompt's recommendation, direction, and confidence were
  not execution constraints in the historical strategy.
- The mismatch remains in current code. `_follows_ai_direction` is applied to
  optional Poisson candidates, but not to the primary DeepSeek candidate.
  `ai_no_bet` text and `_recommended_market` exist in `market_decision.py` yet
  are not used as active primary-candidate gates.
- This makes the prompt's bet recommendation redundant/misleading: either it
  should be removed as non-authoritative explanation, or its `no_bet` and
  direction must be part of the deterministic eligibility contract. The
  current hybrid does neither cleanly.
- ADR-015 already documented LLM overconfidence (Brier `0.715`, near-zero CLV)
  and introduced the fixed 70/30 market shrinkage as mitigation, pending a
  two-week confirmatory evaluation.
- An approved August design explicitly required AI `no_bet` to be a hard
  blocker, but the current regression contract explicitly asserts that AI
  `no_bet` must not veto positive backend value. This is documented behavioral
  drift, not an accidental code path.
- The authoritative strict no-ML v2 architecture forbids LLM-generated or
  LLM-modified probabilities, expected goals, weights, and betting decisions
  from production selection. Current successful DeepSeek predictions still
  replace baseline probabilities, so production remains on the documented
  legacy numeric path rather than the intended v2 boundary.
- `_model_input` sends fixture, form, up to eight head-to-head rows,
  availability, lineups, teams, up to 35 players per side with many statistics,
  player impacts, team stats, odds, standings, quality metadata, and then adds
  the full feature manifest. This explains the observed 12k-48k token range.
- The concise system message does not define evidence precedence, mandatory
  citations/IDs, conflict resolution, or how missing evidence must reduce
  confidence/recommendation. With a very large input, that omission increases
  attention dilution and unverifiable causal claims even though the prose is
  readable.

## Prioritized recommendations

1. Enforce quality state at execution: `SHADOW_ONLY` models may emit auditable
   research candidates but must not debit the main simulated bankroll.
2. Split all reports by `ai.status` and effective `model_version`; do not label
   Poisson fallbacks as DeepSeek forecast quality.
3. Follow the authoritative v2 boundary: deterministic/versioned probability
   engines own probabilities and selection; DeepSeek only structures evidence
   and explains frozen calculations with evidence references.
4. Until the legacy numeric path is removed, treat model `no_bet`, direction,
   and confidence below 0.60 as execution constraints, restore the production
   minimum edge to the documented/default 5%, and do not allow unshrunk LLM
   Asian-handicap probabilities into the main account.
5. Reduce prompt payload to a bounded, relevance-ranked evidence summary;
   require stable evidence IDs/citations and provider-enforced JSON Schema when
   supported. Validate against representative payload size before activation.
6. Treat the free-provider chain as unavailable until representative calls meet
   success-rate and latency thresholds. Nine of nine overnight calls failed.

## Verdict

- Prior loss analysis existed and found/fixed an execution defect.
- The overnight DeepSeek account loss was settlement of that historical defect,
  while all new DeepSeek calls failed closed with no new bets.
- Successful DeepSeek forecasts currently show no demonstrated edge over the
  market, and successful-LLM bets remain very poor but too few for inference.
- Prompt wording and schema are professional at the formatting layer, but the
  prompt is not decision-safe: it is oversized, under-specified for calibration
  and evidence grounding, and inconsistent with both execution behavior and the
  authoritative strict no-ML architecture.
