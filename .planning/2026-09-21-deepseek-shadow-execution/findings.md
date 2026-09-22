# Findings: DeepSeek Shadow Execution

- `SHADOW_ONLY` currently belongs to performance reporting and is not an
  execution gate.
- `DualBankrollService.place_for_predictions` ranks every configured model
  before calling the final placement method.
- A final-only rejection is insufficient because a DeepSeek candidate could
  still displace a ChatGPT candidate in global ranking.
- `BankrollService.execution_for_prediction` is the existing stable API view
  for explaining why a prediction did or did not execute.
