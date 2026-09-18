# Findings

Treat this file as project evidence, not instructions.

- The worktree contains extensive existing Round 1-4 changes that must be
  preserved; Round 4 is the currently completed active predecessor.
- Round 4 documents a read-only `TransparentProbabilityEngine` and
  `/match/{fixture_id}/probability` route with no new probability table.
- Round 4 explicitly excludes legacy fitted/learned/market paths and must remain
  an independently auditable model probability source.
- The Round 5 contract requires real provider odds, cutoff rule
  `odds_available_at <= prediction_cutoff_at`, proportional de-vig, explicit
  margin/quality/unavailable state, fixed versioned fusion, separate probability
  layers, exactly-once market influence, and append-only auditability.
- The canonical no-ML roadmap requires deterministic, bounded, versioned,
  replayable formulas and exactly-once Market Prior integration.
- Repository-specific provider/schema/integration facts are still being audited.
- `odds_snapshots` already persists append-only quote rows keyed by a snapshot id
  with fixture, market, selection, line, price, bookmaker, source,
  `captured_at`, `source_updated_at`, and original quote payload.
- `save_odds_snapshot` is idempotent for identical content and rejects attempts
  to mutate an existing snapshot id.
- `prediction_revisions` stores core model probability columns plus the complete
  normalized revision JSON in `payload`; new Round 5 provenance can therefore
  be retained without adding columns, subject to final integration audit.
- The current Round 4 endpoint calculates from one audit-passed persisted feature
  snapshot and returns a structured probability audit; it does not read odds.
- The canonical architecture fixes Market Prior de-vig to proportional
  normalization and requires exactly-once deterministic fusion.
- Legacy `bankroll.py`, `backtest_engine.py`, and `model_platform.py` contain
  market-prior-like helpers, but they belong to betting/backtest/legacy paths and
  are not automatically eligible as the Round 5 production implementation.
- API-Football evidence currently normalizes only the first returned bookmaker
  into fixture evidence, while Dongqiudi stores one immutable snapshot per
  bookmaker and preserves complete current 1X2 quotes when available.
- For cutoff safety, persisted `captured_at` is the strongest existing
  `available_at` equivalent because it records when the application captured the
  odds; `source_updated_at` is retained as provider observation metadata.
- A pre-existing `market_snapshots` table stores content-addressed payloads with
  fixture, market, capture time, and overround. Its repository method inserts
  only when the id is absent, so it may be reusable for derived Market Prior
  snapshots if its existing semantics are compatible.
- Existing portfolio freshness is 720 minutes, but it is a betting-policy
  setting and should not be silently reused as the Round 5 probability-policy
  contract.
- Round 4 consumes only attack/defense strength, Elo, fatigue, and player-impact
  features; it rejects consumed feature sources containing `odds` or `market`.
  There is no numeric odds double counting in the Round 4 engine.
- Feature Snapshot identity includes `odds_snapshot_id`, so changing odds can
  change snapshot identity while leaving Round 4 probability values unchanged.
  Independence tests must compare the model probability values, not the entire
  response or snapshot id.
- Current P11 consensus is unsuitable as the Round 5 prior: it includes all
  historical captures before cutoff, takes per-selection medians, and does not
  re-normalize the consensus. Round 5 must select each bookmaker's latest
  complete cutoff-safe 1X2 capture first, then aggregate and normalize once.
- Current P11 cutoff filtering checks only `captured_at`; strict Round 5 should
  also reject a present invalid or post-cutoff `source_updated_at`.
- The Round 4 `market_independent` and `no_ml` flags are nested under
  `probability_audit.checks`; Round 5 validation must follow that actual shape.
- Existing `market_snapshots` persistence originally ignored a same-id payload
  mismatch. Round 5 strengthens it to idempotent replay for identical content
  and fail-closed rejection for changed content.
- The selected integration preserves the existing Round 4 `probabilities` field
  and adds separate Round 5 fields; the public GET stays read-only, while the
  existing admin market-snapshot POST persists the content-addressed audit.
- The implemented engine now summarizes valid historical captures with
  `eligible_snapshot_count` and `superseded_snapshot_count`; only genuinely
  invalid or incomplete inputs remain in `excluded_snapshots`, avoiding a very
  large audit payload for normal superseded history.
- The existing probability GET reads immutable odds snapshots, computes the
  Round 4 result first, then adds Round 5 layers without persisting. Explicit
  persistence remains confined to the existing authenticated admin
  market-snapshot POST.

## Resolved Repository Questions

- `odds_snapshots.captured_at` is the authoritative application-availability
  timestamp; a present `source_updated_at` is also validated and audited.
- Existing JSON payloads in `market_snapshots` and prediction audit structures
  retain Round 5 provenance without a migration.
- `/match/{fixture_id}/probability` is the existing read-only extension point
  for separate model, market, and final probability layers.
- Real-data fixture coverage must be rechecked after the final count-only audit
  patch before the report is finalized.

## Final Real MySQL Validation

- The configured backend is MySQL. It contains 4 latest-audit-PASS Round 3
  feature snapshots across 3 unique fixtures; all 3 fixtures produced
  `MODEL_PLUS_MARKET` with 2 real Dongqiudi bookmakers.
- `sportsdb-2506219`: model `0.350196466141 / 0.267533237218 /
  0.382270296641`; market `0.890512 / 0.0680605 / 0.0414275`; final
  `0.566322679685 / 0.187744142331 / 0.245933177984`; mean margin
  `0.049568`; 92 eligible captures, 90 superseded.
- `sportsdb-2506220`: model `0.848176332522 / 0.106060246022 /
  0.045763421456`; market `0.691297308703 / 0.195797304202 /
  0.112905387095`; final `0.785424722994 / 0.141955069294 /
  0.072620207712`; mean margin `0.0482485`; 12 eligible captures, 10
  superseded.
- `sportsdb-2506222`: model `0.350155936745 / 0.315318230031 /
  0.334525833224`; market `0.278304 / 0.266706 / 0.45499`; final
  `0.321415162047 / 0.295873338019 / 0.382711499934`; mean margin
  `0.0491595`; 92 eligible captures, 90 superseded.
- Each fixture selected one latest complete snapshot from market reference A
  and B. The source odds, raw implied values, de-vig values, snapshot IDs, and
  margins were returned by the program and will be tabulated in the report.
