# ESPN Evidence Fallback Design

## Goal

Use ESPN public soccer data as the second evidence source when API-Football is unavailable because of quota, rate limits, transport errors, or a missing fixture ID. Keep TheSportsDB as the final partial-data fallback.

## Architecture

The existing API-Football adapter remains primary. `EspnEvidenceProvider` discovers an event from an ESPN external ID when present, otherwise from the kickoff date and normalized home/away names. It fetches the ESPN event summary and team roster endpoints and maps the result into the existing evidence contract. `EvidenceProviderChain` records bounded provider failures and tries API-Football, ESPN, then TheSportsDB partial evidence.

## Data Mapping

ESPN `lastFiveGames` maps to recent form, `seasonseries` maps to H2H, summary `rosters` maps to starters/substitutes, team roster athletes map to squads and any supplied injuries, and summary odds convert American moneylines to decimal odds while retaining the spread as the available handicap line. Missing fields remain empty and are reflected in evidence completeness.

## Configuration and Failure Handling

ESPN reuses `ESPN_BASE_URL` and requires no additional key. Optional roster requests are best-effort; a failed summary or event discovery falls through to TheSportsDB. All successful contexts retain their source and bounded upstream failure metadata. Existing evidence preservation, immutable snapshots, predictions, bets, and settlements are unchanged.

## Verification

Unit tests cover event matching, form/H2H/lineup/squad/odds mapping, provider order after a simulated API-Football quota error, and final fallback. The full API suite plus web lint/build and live health checks must pass.
