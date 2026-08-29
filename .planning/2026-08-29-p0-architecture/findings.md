# Findings

## Current State

- `apps/api/app/prediction.py` blends Poisson model probabilities with implied odds using a 75/25 mix; this is the primary P0 defect.
- `PredictionService` creates and stores an evidence snapshot, then applies market decision data before saving the prediction.
- `evidence_snapshots` is already append-only by insert, stores SHA-256 and payload, and is referenced by predictions.
- No `odds_snapshots` table or repository API exists; odds currently live inside mutable fixture evidence/context.
- `market_decision.py` already computes market rows with model probability, de-vig market probability, and expected edge, but it mutates the prediction with derived forecast/decision fields.
- `SettlementService` reads prediction probabilities and writes separate fixture settlement rows; it currently also stores market comparison probabilities.
- `PredictionRepository.save()` inserts predictions; no general update method was found in the inspected code path.
- Bankroll placement recomputes market assessment from current context odds, so it needs to prefer the frozen prediction odds snapshot/context and avoid changing forecast fields.
- Dual prediction service runs both model providers against one shared context; snapshot creation currently occurs independently inside each `PredictionService`.

## Design Decisions

- Keep `probabilities` as the backward-compatible pure model probability field and add `model_probabilities` plus `forecast` aliases where needed.
- Add a minimal append-only `odds_snapshots` table with fixture/market/selection/line/price/bookmaker/source/captured_at and a payload/hash-friendly snapshot ID.
- Capture one odds snapshot at prediction creation and store `odds_snapshot_id` on the prediction; market assessment reads the snapshot values.
- Keep market assessment and decision fields as derived prediction payload data, but prohibit repository updates to frozen fields after insertion.
- Settlement writes only settlement/bet/transaction records and copies frozen values; it never updates predictions or evidence/odds snapshots.
