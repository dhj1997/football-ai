# Findings

- Existing `evidence_snapshots` and `odds_snapshots` are append-only and already contain captured timestamps; closing odds can be selected from their quote rows strictly before kickoff.
- Existing `PredictionService` persists immutable predictions and `DualPredictionService` owns the P3 ensemble; P4 should use adapters/callbacks for historical runs instead of duplicating model logic.
- Existing league/team snapshots are current-state upserts, so historical reconstruction needs a separate append-only historical snapshot record rather than treating them as history.
- Existing `fixture_settlements` contains P1 forecast metrics and P2 betting/CLV fields; P4 forecast and betting reports must remain separate.
- No P4 tables or services currently exist. A small persistence layer plus a pure validation module is required.
