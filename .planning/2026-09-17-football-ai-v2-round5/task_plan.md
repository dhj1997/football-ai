# Football AI v2 Round 5 Market Prior / Odds Intelligence

## Goal

Add the smallest cutoff-safe, deterministic, auditable 1X2 Market Prior and
exactly-once fixed-weight fusion on top of the unchanged Round 4
market-independent probability output.

## Phases

### Phase 1: Existing implementation and contract audit
**Status:** complete
- Map the existing odds providers, snapshots, timestamp semantics, aggregation,
  prediction revisions, probability API, and persistence contracts.
- Prove whether Round 4 is market-independent and identify any double-counting
  risk before implementation.

### Phase 2: Minimal Round 5 design and approval
**Status:** complete
- Compare the viable reuse/integration approaches and select the smallest one.
- Specify validation, cutoff, quality, fixed fusion, provenance, append-only,
  API, and real-data verification behavior.
- Obtain user approval before changing business code.

### Phase 3: Market Prior engine
**Status:** complete
- Reuse real existing odds inputs.
- Implement strict 1X2 validation, implied probability, proportional de-vig,
  margin, simple multi-bookmaker aggregation, quality, and unavailable states.

### Phase 4: Deterministic fusion and audit integration
**Status:** complete
- Consume Round 4 model probability without changing its formulas.
- Apply one centralized versioned fixed weight exactly once.
- Preserve separate model, market, and final probabilities with provenance and
  append-only revision behavior.

### Phase 5: Focused verification and report
**Status:** complete
- Cover the critical validation, cutoff, normalization, independence,
  exactly-once, append-only, reproducibility, and no-ML contracts.
- Validate 3-10 eligible real matches when real provider data is available;
  otherwise report truthful unavailable states without fabricated odds.
- Write `docs/AI_ROUND5_REPORT.md`, run compileall and `git diff --check`, then
  stop before Round 6, EV, Kelly, strategy, backtest, live, LLM, or ML work.

## Hard Boundaries

- No ML, fitting, optimization, learned weights/calibration, or LLM numeric path.
- No change to Round 4 expected goals, Poisson, Dixon-Coles, score matrix, 1X2,
  O/U, or BTTS formulas.
- No second odds provider/store, fake odds, historical overwrite, or future-odds
  leakage.
- Preserve all pre-existing dirty-worktree changes and avoid unrelated refactors.
- Run only risk-proportionate focused tests unless a shared contract requires more.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| `head` was not available on PowerShell PATH | 1 | Use Git's explicit `C:\\Program Files\\Git\\usr\\bin\\head.exe` for byte-capped output. |
| Planning session catch-up script could not find a usable Python runtime through `python`, `py`, or the stale repository venv launcher | 3 | Stop retrying; rely on the inspected Git state and existing planning files, and record the limitation. |
| Two prompt chunk reads started beyond the decoded character length because the file-size inventory counted multibyte UTF-8 bytes | 1 | The complete prompt had already ended in the preceding chunk; stop at the decoded character boundary and do not retry invalid offsets. |
| The first PowerShell here-string wrapper for read-only MySQL validation exited without stdout or an error | 1 | Do not repeat the wrapper; probe the interpreter/backend with a direct one-line command, then use a different script-passing method. |
| The direct temporary validation script exceeded the 30-second command yield and its shell session id was not retained by the wrapper | 2 | Poll the returned shell session inside one orchestration call until completion so the compact JSON cannot be lost. |
| The combined full API and Round 2 regression command also exceeded 30 seconds before its wrapper retained the shell session | 1 | Split the suites and explicitly poll each returned session; do not run the combined wrapper again. |

## Decisions

- The user-provided Round 5 execution prompt and the canonical strict no-ML
  architecture are binding scope constraints.
- Business-code implementation is gated on completion of the current-state audit
  and approval of the repository-specific minimal design.
- The user-provided execution prompt is the approved architecture and explicitly
  directs selection of the smallest transparent repository-compatible option;
  the repository mapping is documented in the Round 5 design spec.
