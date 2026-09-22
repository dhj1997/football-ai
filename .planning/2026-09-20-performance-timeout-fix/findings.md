# Findings

- Production Web and API services are healthy and use MySQL.
- The Web proxy returns 504 after about 4.04 seconds for both decision requests
  under dashboard concurrency and for model evaluation.
- Direct API timing is about 2.45 seconds for 126 ChatGPT decisions, 3.46 seconds
  for 173 all-model decisions, and 21.69 seconds for model evaluation.
- The decision route calls `bet_for_prediction` once per returned row.
- The dashboard requests selected-model and all-model decisions concurrently.
- The default model-evaluation route computes P6 before checking persistence.

## 2026-09-21 Recurrence

- The restarted production host is healthy again; public root and health both
  return HTTP 200.
- The page still launches five core requests plus backtest and model-evaluation
  reads concurrently.
- The strategy route remains fast. Under page concurrency, the all-model
  decision route crosses the four-second proxy deadline and returns 504.
- The earlier batch fix only avoids `bet_for_prediction` for rows that have a
  linked bet. Every no-bet row still calls
  `bankroll_service.execution_for_prediction`, which performs the same
  single-prediction lookup again.
- Client/proxy cancellation does not stop the synchronous FastAPI worker, so
  repeated timed-out decision requests continue consuming MySQL and can
  saturate the small ECS instance.
- The approved design already requires one batch bet read; the follow-up should
  complete that contract rather than add a cache, table, or broader refactor.
- The existing regression monkeypatches `bet_for_prediction` only in a fixture
  that already has a linked bet, so the route never enters the remaining
  no-bet lookup path. The no-bet route test must enforce the same zero
  single-read contract.
- `execution_for_prediction` is also used by fixture-detail views. Preserve its
  default lookup behavior and add an explicit known-bet argument only for the
  already-batched decision report.
- Production deployment of `9da2626` retained MySQL as the database backend.
  The all-model decision report returned HTTP 200 in about 4.38 seconds
  internally and 4.04 seconds through the public proxy, so the report-specific
  30-second limit now covers the observed runtime without relaxing ordinary
  API traffic.
- A normal production browser load rendered the full model-review dashboard
  with 126 decision rows and no backend-timeout message. The Nottingham Forest
  vs Coventry simulated bet rendered as settled `全输 -90.97`, not pending.
