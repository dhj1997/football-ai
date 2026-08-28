# Football AI UI Redesign Documentation

## Purpose
This documentation defines a UI/UX redesign for the existing Football AI application without changing its core product behavior.

The project currently provides:
- Schedule and pre-match analysis for Chinese Super League, La Liga, and Premier League
- Match evidence readiness
- Parallel DeepSeek and GPT predictions
- Prediction snapshots and auditability
- Simulation bankroll and performance tracking
- League standings
- Automation and job administration

## Design Goal
Transform the interface from a traditional admin-style data page into a professional **Football Intelligence Platform**.

The product should feel:
- analytical, not decorative
- dense but easy to scan
- trustworthy and auditable
- modern and premium
- optimized for desktop first, usable on mobile

## Source of Truth
Before implementation, Codex must read:
1. `AGENTS.md`
2. `PRODUCT.md`
3. `DESIGN.md`
4. this directory
5. the existing implementation under `apps/web`

If existing project instructions conflict with this document, existing project instructions win.

## Scope
UI/UX only unless a task explicitly says otherwise.

Do not change:
- API contracts
- FastAPI behavior
- database schema
- prediction algorithms
- evidence semantics
- automation semantics
- routes
- simulation settlement rules

## Execution Order
1. Foundation
2. Shared components
3. Schedule
4. Match detail and analysis
5. Performance
6. Standings
7. Admin
8. Responsive and QA
