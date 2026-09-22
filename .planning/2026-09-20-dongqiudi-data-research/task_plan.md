# Dongqiudi Data and Research Activation

## Goal

Implement approved方案 A, push it to GitHub, deploy it to production, and verify
the real MySQL-backed workflows and public routes.

## Current Phase

All phases complete

## Phases

### Phase 1: Provider and storage contracts
- Add bounded Dongqiudi player-detail and transfer mapping.
- Store and read transfers by provider namespace.
- Keep API-Football as a truthful fallback/supplement.
- **Status:** complete

### Phase 2: Local Elo provenance
- Preserve ClubElo preference while labeling deterministic local fallback.
- Keep cutoff-safe completed-match inputs.
- **Status:** complete

### Phase 3: Research thresholds
- Archive an exploratory report from 20 qualified pairs.
- Retain 30 pairs for confirmatory research and model evaluation.
- Expose exploratory and confirmatory archive counts separately.
- **Status:** complete

### Phase 4: Focused verification
- Run directly affected API tests and Web type/lint checks.
- Review diff and preserve unrelated worktree changes.
- **Status:** complete

### Phase 5: Delivery and production verification
- Commit scoped code, push GitHub, run backup/restore deployment gate.
- Verify systemd, public proxy routes, deployed SHA, MySQL rows, and job output.
- **Status:** complete

## Decisions

| Decision | Rationale |
|---|---|
| Dongqiudi primary, API-Football fallback | Avoid current identity/quota gaps without hiding partial coverage |
| Provider-namespaced transfer rows | Dongqiudi and API-Football IDs are different domains |
| 20-pair archive eligibility only for exploratory work | Preserve the 30-pair confirmatory policy |
| Player values remain unavailable | Public fields exist but redisplay authorization is not documented |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `writing-plans` skill is unavailable | 1 | Use this scoped equivalent plan and continue |
| New Elo fixture test omitted required `fixture_date` | 1 | Add the repository-required field and rerun the focused suite |

## Boundaries

- Preserve `.planning/.active_plan`, the prior completed plan, and `.tmp/`.
- Do not activate unlicensed player-value redistribution.
- Do not infer current injury state from historical injuries.
- Pass every displayed/logged player name through `to_chinese_player_name`.
- Keep tests focused on changed contracts.
