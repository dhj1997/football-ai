# Live Score Refresh And Prediction State Design

## Goal

Correct current-match status and score refresh without weakening the existing pre-kickoff prediction boundary.

## Confirmed Behavior

- Real Madrid vs Malaga kicked off at 23:00 Asia/Shanghai. No prediction may be created at or after kickoff.
- TheSportsDB may return an in-progress status such as `2H` together with a partial score. A partial score must not imply `finished`.
- ESPN currently provides the authoritative live/final state for the affected supported-league matches.

## Design

1. Keep TheSportsDB as the schedule and fixture-identity source.
2. Add a bounded ESPN scoreboard read for CSL, EPL, and LAL to the existing league provider.
3. During the existing schedule refresh, match ESPN rows to TheSportsDB rows only when league, kickoff, home team, and away team agree. Overlay only `status`, `provider_status`, and `score`; preserve the existing fixture ID, external IDs, evidence, and free team data.
4. If ESPN is unavailable or a row cannot be matched confidently, retain the TheSportsDB row unchanged.
5. Map TheSportsDB `1H`, `HT`, `2H`, and other active phases to `live`. Only explicit final states such as `FT`, `AET`, `PEN`, or `Match Finished` map to `finished`.
6. On the match page, treat `kickoff <= now` as prediction-blocked even if a stale provider status still says `scheduled`. Display the existing no-post-kickoff explanation instead of an actionable prediction button.

## Data Flow

```text
TheSportsDB schedule rows
        +
ESPN scoreboard status/results
        |
confident fixture match
        |
existing ScheduleSyncService
        |
fixture cache -> UI / settlement
```

P6/P7 historical data, historical predictions, production predictions, bets, bankroll, and settlement semantics are not changed.

## Error Handling

- ESPN request failure does not fail or erase the primary TheSportsDB refresh.
- Unmatched or ambiguous ESPN events are ignored.
- Missing scores remain unavailable; no score is inferred.
- Manual prediction after kickoff remains rejected by the backend with HTTP 409.

## Verification

- TheSportsDB `2H` maps to `live`, not `finished`.
- An exact ESPN match updates status and score while preserving fixture identity.
- An unmatched event does not overwrite a fixture.
- ESPN failure preserves the primary schedule rows.
- The match page does not offer manual prediction once kickoff has passed.
- Focused API/provider tests, web lint/build, Python compile, and `git diff --check` pass.
