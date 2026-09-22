# Progress: DeepSeek Shadow Execution

## 2026-09-21

- User approved pausing only DeepSeek simulated execution.
- Approved design recorded.
- Added per-model active/shadow execution configuration.
- Excluded shadow services from candidate ranking and guarded final writes.
- Added API and Chinese UI status reporting for shadow execution.
- Verified 18 configuration/dual-model tests and 57 bankroll/API tests.
- Verified focused frontend lint, TypeScript, and Python compilation.
- No historical data mutation performed.
- Pushed `4730800` and `947e51c` to `origin/main`.
- Verified MySQL backup restore against 41 tables before deployment.
- Deployed and matched production hashes for the critical backend/frontend files.
- Verified public DeepSeek execution view returns `model_shadow_only`.
- Verified no post-deployment DeepSeek bet, execution, or transaction rows.
