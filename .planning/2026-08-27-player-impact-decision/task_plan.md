# Player Impact and Bet Decision Upgrade

## Goal

Deliver the active Codex Goal: canonical player linkage, Chinese-name enforcement, inspectable player contribution, an authorized optional value-provider boundary, deterministic market decisions, one shared prompt contract, clear product explanations, and complete verification.

## Phases

### Phase 1: Player identity and Chinese-name boundary

- Status: completed
- Normalize injury/lineup/squad identities and eliminate supplier-English player names from public API, model input, page, and log boundaries.

### Phase 2: Player contribution model

- Status: completed
- Compute expected minutes, role/star classification, attack/defense contribution, replacement contribution, absence impact, and retained strength from existing authorized evidence.

### Phase 3: Authorized market-value boundary

- Status: completed
- Add a replaceable optional `PlayerValueProvider` contract, provenance/freshness, caching semantics, and explicit null behavior without scraping or fabrication.

### Phase 4: Forecast and market-decision separation

- Status: completed
- Deterministically calculate break-even/de-vig/model probabilities, expected edge, uncertainty, decision status/reason codes, and bounded risk sizing.

### Phase 5: Unified prompt contract

- Status: completed
- Make DeepSeek and GPT consume the same versioned system instructions, evidence, player-impact context, and JSON schema; keep deterministic decision fields backend-owned.

### Phase 6: Product surfaces

- Status: completed
- Extend the current TASK_03-08 match UI with outcome, price value, execution decision, player impact, and value provenance while preserving its design system.

### Phase 7: Regression and live verification

- Status: completed
- Run focused/full API tests, lint, TypeScript, build, and desktop/mobile browser verification with a real cached fixture.

## Constraints

- Preserve every existing worktree change; do not revert or restyle unrelated TASK_03-08 work.
- Do not lower `no_bet` standards or optimize for bet count.
- Do not connect to a real-money platform.
- Do not scrape Transfermarkt or add any source without verified authorization/coverage.
- Missing values remain `null` and neutral.
- Every public/logged/model-facing player name goes through `to_chinese_player_name`.
- Keep implementation and tests proportional to current risk.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Legacy Asian settlement reused with a changed line | 1 | Require an exact forecast/current handicap-line match and add regression coverage. |
| Existing 3000/8000 services served old code | 1 | Preserve user processes; verify on isolated 3002/8001 services. |
