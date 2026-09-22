# Findings

- Live player endpoint `50222265` returned HTTP 200 on 2026-09-20.
- `history_market_values` is an object keyed by year; each year contains records
  with numeric `market_value`, `record_date`, player/team identity, and text.
- The sample identifies the player in `base_info` as `50222265`, while history
  records use a second provider person ID (`222265`); both need provenance.
- Existing `player_value_snapshots` has one row per canonical player and a JSON
  payload, so a merged history can be retained without a schema-key migration.
- Existing `PlayerValueService` refreshes inline and has no cutoff parameter;
  runtime currently uses `NullPlayerValueProvider` and hard-coded unavailable
  activation status.
- Existing UI already understands value/source/date/freshness fields.
- `DongqiudiProvider.team()` already emits roster `provider_player_id` values
  and Chinese-normalized player names, and `player_detail()` already wraps the
  required public JSON endpoint.
- `main.py` currently calls `PlayerValueService.enrich()` while building a
  fixture context, so provider network refresh must be removed from this path.
- `player_impact.py` carries market-value provenance into its public summary but
  does not use market value as a deterministic contribution coefficient.
- `AutomationRunner` records every job lifecycle in `job_runs`, converts a
  non-empty `errors` list to `partial`, and exposes manual execution through the
  existing `/api/admin/jobs/{job_name}/run` route.
- The existing squad backfill places Dongqiudi roster players in each upcoming
  fixture's `free_team_data.{side}.squad`; this is the cheapest value-sync
  target source and avoids another team fetch when roster data exists.
- New settings only need interval, per-run player limit, lookahead, and cache
  staleness; Dongqiudi timeout and pacing already exist on the shared provider.
- `PredictionService.prepare_context()` receives the authoritative
  `prediction_timestamp`; fixture detail can use the persisted prediction's
  `prediction_cutoff_at` when enriching its reconstructed display context.
- Canonical player IDs are name-derived whenever a usable localized name is
  present, so the sync and fixture enrichment remain stable across provider
  context labels; unresolved display names must still be normalized through
  `localize_player_record()` and `to_chinese_player_name`.
- The implemented provider was checked live against player `50222265`: it
  parsed 27 dated records, selected EUR 750000 at `2026-06-08`, and produced
  the expected Chinese alias `韦世豪`.
- Production revision `7b53f8443db6f1b30c56c693e60d801bf40a9a6b`
  matches GitHub `main`; both API and Web systemd services are active and the
  health response reports `database_backend=mysql`.
- Public `/`, `/standings`, `/api/backend/health`, and
  `/matches/dongqiudi-54493261` returned HTTP 200. Browser rendering confirmed
  the home fixture queue, live standings, and the real squad value panel.
- The real fixture renders 51/51 player values with Chinese player names and
  Dongqiudi provenance. Value cells expose record dates in their title, for
  example 于纳尔 `7.0m` at `2026/06/03`.
- Remote key-file hashes differ byte-for-byte only because deployed files use
  CRLF. After removing CR from line endings, both hashes exactly match Git
  `HEAD`: provider `8b7e010d...aad32`, sync `7ff29078...eae24`.
