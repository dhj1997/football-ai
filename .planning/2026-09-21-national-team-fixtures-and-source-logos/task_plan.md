# Task Plan: National-Team Fixtures and Source Logos

## Goal

Add source-backed men's national-team fixtures and competition/team logos,
while preserving club competitions and excluding women's football, Gold Cup,
Oceania Cup, and non-Asian men's U23 competitions.

## Current Phase

Phase 1: Registry and provider contracts

## Phases

### Phase 1: Registry and provider contracts
- [ ] Add normalized national competition definitions and explicit exclusions
- [ ] Add source/logo metadata contract
- [ ] Add focused registry/provider regression tests
- **Status:** in progress

### Phase 2: Schedule and logo synchronization
- [ ] Extend TheSportsDB national-team competition IDs and mapping
- [ ] Extend Dongqiudi normalization for eligible Asian competitions
- [ ] Merge national fixtures without ambiguous cross-provider matches
- [ ] Cache verified competition/team logos with source metadata
- **Status:** pending

### Phase 3: API and frontend
- [ ] Return national competition metadata in list/detail payloads
- [ ] Replace generated league SVGs with cached source-backed images
- [ ] Keep competition filters and add a national-competition grouping
- [ ] Preserve no-China-only-tab layout
- **Status:** pending

### Phase 4: Verification and delivery
- [ ] Run focused API/provider/frontend checks
- [ ] Verify excluded competitions and women's rows never enter cache
- [ ] Commit, push, deploy with MySQL backup verification
- [ ] Verify public routes, source timestamps, and production counts
- **Status:** pending

## Constraints

- Do not modify `.planning/.active_plan` or unrelated dirty files.
- Do not fabricate fixtures or logos when providers have no source row.
- Preserve existing club fixtures and historical predictions/bets.
- Use Chinese team names through `to_chinese_team_name`.
- National fixtures without valid odds may be displayed/predicted but not
  forced into simulated betting.
