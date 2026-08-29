# DotaScope-Style Performance Implementation

## Goal

Implement the approved minimal football performance evaluation loop: versioned baseline experiments, auditable bet/no-bet decisions, forecast/decision/portfolio metrics, quality gates, and a usable performance page.

## Phases

### Phase 1: Backend experiment and metrics contract

- Status: completed
- Add experiment metadata to predictions and settlements.
- Add log loss, RPS, market comparison, decision counts, and quality gates.

### Phase 2: API and web performance surface

- Status: completed
- Expose the enriched report through the existing API.
- Add strategy, quality-gate, and decision audit sections to the current performance page.

### Phase 3: Verification

- Status: completed
- Run focused backend tests, the relevant API suite, frontend type/lint/build checks, and browser verification.

## Constraints

- Keep manual prediction mode unchanged.
- Do not connect real-money betting or invent closing odds.
- Reuse current model accounts and tables for the single baseline strategy.
- Preserve unrelated user changes.
- Convert any player names exposed by new API/UI paths with `to_chinese_player_name`.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Global `pytest` command was unavailable | 1 | Use the repository virtual environment: `.venv/Scripts/python.exe -m pytest`. |
| New market-comparison test expected a negative Brier delta for a stronger model forecast | 1 | Recalculate the sample (`market 0.305 - model 0.245 = +0.060`) and correct the assertion. |
| Initial runtime browser check could not reach API/web ports | 1 | Start API on 8002 and Web on 3001 with `API_BASE_URL=http://127.0.0.1:8002`. |
| Web proxy initially used its default API port 8001 | 1 | Restart the development server with an explicit `API_BASE_URL` and verify all three performance requests return 200. |
