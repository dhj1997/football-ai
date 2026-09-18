# AI Round 3 Feature Coverage

Generated at: `2026-09-16T04:12:04Z` (read-only post-activation verification)

Feature version: `round3-feature-engine-v2`

Persisted Feature Engine v2 snapshots: `4`

Latest audit-passed fixture snapshots used for coverage: `3`

Fixtures represented: `3`

Persisted feature values: `448` (latest-per-fixture denominator: `336`)

Leakage audits: `4 PASS`

Status: `ok`

## Data Scope

Migration `0006-round3-feature-engine` was applied at
`2026-09-16T03:39:15Z`. The bounded activation covered three upcoming
`LALIGA` (西甲) fixtures and six teams. One fixture was calculated twice at
different cutoffs to verify append-only history; coverage counts only the
latest audit-passed snapshot per fixture.

| Fixture | Home | Away | Kickoff (UTC) |
|---|---|---|---|
| `sportsdb-2506220` | 马德里竞技 | 奥萨苏纳 | 2026-09-16 17:00 |
| `sportsdb-2506219` | 巴塞罗那 | 桑坦德竞技 | 2026-09-16 18:00 |
| `sportsdb-2506222` | 莱万特 | 毕尔巴鄂竞技 | 2026-09-16 19:30 |

## Competition Coverage

The denominator is every expected feature row in the latest PASS snapshot for
each fixture. `insufficient_sample` rows with a real value count as available;
explicit missing rows do not.

| Competition | Feature group | Available | Expected | Coverage |
|---|---|---:|---:|---:|
| LALIGA (西甲) | attack | 12 | 12 | 100.00% |
| LALIGA (西甲) | defense | 12 | 12 | 100.00% |
| LALIGA (西甲) | elo | 12 | 12 | 100.00% |
| LALIGA (西甲) | fatigue | 30 | 30 | 100.00% |
| LALIGA (西甲) | form | 144 | 192 | 75.00% |
| LALIGA (西甲) | home_away | 6 | 30 | 20.00% |
| LALIGA (西甲) | player | 0 | 6 | 0.00% |
| LALIGA (西甲) | strength | 6 | 6 | 100.00% |
| LALIGA (西甲) | xg | 0 | 36 | 0.00% |

## Feature Coverage

All 62 registered definitions were emitted in the latest snapshots. The
following compact breakdown is per feature (`available / expected`):

- `6/6` (100%): `attack_strength`, `days_since_last_match`,
  `defense_strength`, `draw_rate_last_10`, `draw_rate_last_3`,
  `draw_rate_last_5`, `draw_rate_last_8`, `fatigue_score`,
  `goal_difference_last5`, `goals_against_last5`, `goals_against_last_10`,
  `goals_against_last_3`, `goals_against_last_5`, `goals_against_last_8`,
  `goals_for_last5`, `goals_for_last_10`, `goals_for_last_3`,
  `goals_for_last_5`, `goals_for_last_8`, `loss_rate_last_10`,
  `loss_rate_last_3`, `loss_rate_last_5`, `loss_rate_last_8`,
  `matches_last_14_days`, `matches_last_30_days`, `matches_last_7_days`,
  `points_last_10`, `points_last_3`, `points_last_5`, `points_last_8`,
  `team_elo`, `win_rate_last_10`, `win_rate_last_3`, `win_rate_last_5`,
  `win_rate_last_8`.
- `3/3` (100%): `home_elo`, `away_elo`.
- `1/3` (33.33%): `away_goals_against`, `away_goals_for`,
  `away_win_rate`, `home_goals_against`, `home_goals_for`, `home_win_rate`.
- `0/3` (0%): `away_xg`, `away_xga`, `home_xg`, `home_xga`.
- `0/6` (0%): `performance_vs_expectation_last_10`,
  `performance_vs_expectation_last_3`, `performance_vs_expectation_last_5`,
  `performance_vs_expectation_last_8`, `player_impact`, `rolling_xg_3`,
  `rolling_xg_5`, `rolling_xg_8`, `rolling_xga_3`, `rolling_xga_5`,
  `rolling_xga_8`, `xpoints_delta_last_10`, `xpoints_delta_last_3`,
  `xpoints_delta_last_5`, `xpoints_delta_last_8`.

## Value Status and Missing Reason

Across the 336 latest-per-fixture rows:

| Status | Rows |
|---|---:|
| `available` | 60 |
| `insufficient_sample` | 162 |
| `missing` | 114 |

Missing reasons (114 rows total):

| Missing reason | Rows |
|---|---:|
| `source_xpoints_unavailable` | 48 |
| `source_xg_unavailable` | 40 |
| `no_prior_split_matches` | 20 |
| `player_impact_rule_or_evidence_unavailable` | 6 |

Every persisted feature value has a non-null `quality_score` (`448/448`). The
latest snapshot quality scores (the `quality_payload.overall_score` persisted
in each snapshot) were `0.6011` (`sportsdb-2506220`), `0.5754`
(`sportsdb-2506219`), and `0.6021` (`sportsdb-2506222`).

## Time Boundary and Method

- Completed-result history is filtered by result availability at or before the
  prediction cutoff; future match results are excluded from Elo, form, goals,
  strength, home/away, and fatigue windows.
- xG/xPoints fields use their own source availability timestamp and are missing
  when that timestamp is after the cutoff.
- Coverage selects only `round3-feature-engine-v2` snapshots whose latest
  leakage audit is `PASS`, then selects the latest eligible snapshot per
  fixture. No test fixtures are included in these numbers.

Read-only integrity checks found `0` rows where
`available_at > prediction_cutoff_at` and `0` null `quality_score` values.
