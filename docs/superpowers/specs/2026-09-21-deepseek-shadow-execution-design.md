# DeepSeek Shadow Execution Design

## Problem

DeepSeek is currently reported as `SHADOW_ONLY`, but that quality state does
not prevent its predictions from entering the simulated-bet candidate pool.
This allows a model without demonstrated forecast edge to create financial
records or displace an executable ChatGPT candidate.

## Selected Design

1. Add an explicit per-model execution mode with two valid values: `active`
   and `shadow`. DeepSeek defaults to `shadow`; ChatGPT remains `active`.
2. Keep shadow models enabled in prediction, persistence, settlement-based
   scoring, and quality reporting.
3. Exclude shadow models before global candidate ranking so they cannot consume
   a portfolio slot that an active model could use.
4. Enforce the same policy again immediately before bet persistence so direct
   or legacy placement paths cannot bypass it.
5. Report rejected shadow execution with reason code `model_shadow_only` and
   the Chinese reason `模型仅观察，不执行模拟下注`.
6. Preserve all historical predictions, bets, executions, settlements,
   balances, and bankroll transactions.

## Alternatives Rejected

- Hard-coding a DeepSeek check in the dual-bankroll service would be smaller,
  but would hide an execution policy inside model-specific branching.
- Disabling DeepSeek entirely would also stop predictions and quality samples,
  preventing the evidence needed to decide whether it can be promoted later.
- Blocking only at final persistence would let a shadow candidate win global
  ranking and incorrectly suppress an active ChatGPT candidate.

## Verification

- Focused service tests prove shadow DeepSeek creates no bet or execution while
  active ChatGPT still executes from the same prediction batch.
- A direct placement test proves the persistence guard cannot be bypassed.
- Execution-view tests prove the explicit shadow reason is returned.
- Configuration and frontend checks prove the default modes and Chinese label.
- Production verification confirms DeepSeek predictions continue while no new
  DeepSeek financial records are created.
