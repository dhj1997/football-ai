# Dongqiudi Data and Research Gates Design

Date: 2026-09-20

## Scope

This amendment completes the currently actionable external-data work without
weakening the project's strict no-ML and point-in-time rules. It covers:

- Dongqiudi-backed team identities and transfer evidence;
- a deterministic local Elo fallback fed by stored match results;
- a 20-pair exploratory research archive while retaining the 30-pair
  confirmatory threshold;
- explicit deferral of player-value activation until redisplay authorization
  is documented.

It does not change prediction formulas, promote a model, infer current injury
status from injury history, or treat standings, rankings, squad value, or
Sofifa ability as Elo.

## Provider Boundaries

### Dongqiudi Identities

Dongqiudi team and player identifiers form their own provider namespace. Team
page IDs, canonical `500xxxxx` IDs, and player IDs are retained together with
the normalized Chinese display name. A team identity is accepted only when the
fixture/team-page evidence resolves to one unambiguous team. Names displayed or
logged by the integration pass through `to_chinese_player_name` or the existing
team-name normalizer.

The existing team-page request chain remains authoritative:

1. load `/api/data/v1/detail/team/{team_id}`;
2. load `/sport-data/soccer/biz/dqd/v1/team/member_v2/{team_id}?app=dqd`;
3. retry the roster with the profile's canonical team ID only when needed;
4. reject an empty or name-mismatched roster.

### Transfers

Dongqiudi becomes the primary transfer source for supported upcoming teams.
The sync reads the current roster, then reads each required player's public
detail response and maps `transfer_info` into the existing transfer evidence
shape. Player detail calls are bounded, paced, cached, and limited to stale
upcoming teams. Existing API-Football transfer ingestion remains a fallback for
teams that cannot be resolved or fetched from Dongqiudi.

Each stored record keeps the provider player ID, transfer date, type, fee text,
from/to provider team IDs, normalized Chinese player/team names, source, and
capture time. The current 45-day prediction window remains unchanged. Empty
responses, missing identities, upstream failures, and successful zero-record
responses remain distinct outcomes.

### Player Values and Injuries

Dongqiudi player detail responses contain numeric historical market values with
`record_date`, but the public web endpoints do not document redisplay rights,
rate limits, or a stability contract. The production player-value provider
therefore remains unavailable until redisplay authorization is supplied. The
implementation must not mark Dongqiudi as licensed or set
`redisplay_authorized=true` without that evidence.

Historical injury records are audit context only. They must not be converted
into current availability. Current match availability continues to come from
cutoff-safe pre-match `sideline` evidence and confirmed lineups.

## Elo Data Flow

ClubElo remains an optional external snapshot and preserves its last valid
snapshot during outages. The operational fallback is the existing deterministic
local Elo calculation over stored, completed fixtures. Dongqiudi contributes
only source-attributed match results to that fixture history.

The resulting rating provenance is reported as local Elo derived from match
results. No Dongqiudi field is labeled as ClubElo, and team rank, standings,
market value, or player ability cannot enter the Elo slot.

## Research Thresholds

The statistical policy keeps these states:

- fewer than 20 paired samples: no automated research archive;
- 20 to 29 paired samples: persist an exploratory, low-confidence early report;
- 30 to 99 paired samples: allow the pre-registered confirmatory comparison and
  label it low confidence;
- 100 or more paired samples: adequate sample.

The existing 30-sample model evaluation and confirmatory gates remain intact.
The 20-sample automation uses a distinct exploratory hypothesis and job ID,
does not claim confirmation, does not promote a model, and remains visibly
separate from the later confirmatory run. Content-addressed run IDs preserve
idempotency when automation repeats.

The administration surface reports both archived exploratory runs and completed
confirmatory runs instead of treating the absence of a confirmatory run as an
empty feature.

## Failure Handling

- Missing Dongqiudi identity: record `provider_id_missing` and try the existing
  fallback; never guess an identifier.
- Partial player-detail fetch: store only validated records and report the
  failed player/team counts.
- Rate limiting or transport failure: stop the bounded run, preserve last good
  data, and expose the upstream error category.
- Missing transfer date or direction: reject that record rather than attaching
  it to a prediction window.
- Insufficient research pairs: report the exact sample count and next threshold
  without persisting a conclusive result.
- Leakage or point-in-time audit failure: fail closed for both exploratory and
  confirmatory research.

## Verification

Focused tests cover:

- Dongqiudi public/canonical team ID resolution and ambiguous identity rejection;
- transfer mapping, Chinese-name normalization, pacing boundaries, fallback,
  and idempotent persistence;
- local Elo provenance without relabeling it as ClubElo;
- 19/20/29/30-sample research transitions and separate exploratory versus
  confirmatory job identities;
- preservation of the player-value authorization gate and historical-injury
  non-inference.

Production verification requires the deployed Git SHA, active API/Web systemd
services, public proxy routes, successful MySQL reads/writes, provider job
telemetry, stored transfer coverage, and the expected research archive status.
