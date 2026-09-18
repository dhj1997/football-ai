# Football AI v2 Round 4 Transparent Probability Engine

## Goal

Add the smallest deterministic, market-independent probability chain on top of
the existing Round 3 Feature Snapshot data:

`Feature Snapshot -> Expected Goals -> Poisson -> Dixon-Coles -> Score Matrix -> 1X2/O-U/BTTS`

## Phases

### Phase 1: Existing implementation and contract audit
**Status:** complete
- Locate reusable Elo/Poisson/Dixon-Coles/probability/storage/API paths.
- Confirm no duplicate Feature Store and select the smallest persistence/API boundary.

### Phase 2: Deterministic probability engine
**Status:** complete
- Add centralized versioned fixed configuration.
- Implement cutoff-safe feature-snapshot input validation, expected goals,
  Poisson tail handling, Dixon-Coles fixed correction, aggregation, and
  explanation/audit payloads.

### Phase 3: Minimal integration and tests
**Status:** complete
- Add only the required read-only probability endpoint or reuse an existing one.
- Add focused unit tests for normalization, correction, cutoff, replay, no-ML,
  and explanation immutability.

### Phase 4: Bounded real-data validation and report
**Status:** complete
- Evaluate 3-10 existing audit-passed snapshots without starting automation or
  full recalculation.
- Write `docs/AI_ROUND4_REPORT.md`, run scoped tests, compileall, and diff check.
- Stop before Market Prior, betting, backtest, live prediction, or LLM analyst.

## Hard Boundaries

- No ML, fitting, training, optimization, learned calibration, or LLM numeric path.
- No Market Prior, odds fusion, EV, Kelly, staking, betting decisions, or live prediction.
- Reuse Round 2/3 snapshots, values, leakage audit, and append-only principles.
- Preserve all pre-existing dirty-worktree changes.
- Do not run broad unrelated tests.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| System Python did not have pytest | 1 | Used the repository `apps/api/.venv` interpreter. |

## Decisions

- Legacy `prediction.py` and `model_platform.py` fitted/learned/market paths are not Round 4 inputs. The new engine reuses only their pure Poisson and Dixon-Coles scalar helpers.
- No `0007` migration is needed. The probability endpoint is read-only and returns a structured probability audit; existing revision storage remains untouched.
- Expected goals use fixed baselines, bounded attack/defense ratios, Elo differential, fatigue, and source-backed player impact. Missing or out-of-range values use an explicit neutral fallback and lower input quality.
- The score matrix uses exact buckets `0..9` plus a `10+` tail bucket, applies fixed rho `-0.10` only to low exact cells, and normalizes deterministically.
- Production calculation is fail-closed unless the snapshot has its own ID, a clean leakage audit, and matching per-feature cutoff/version fields.
