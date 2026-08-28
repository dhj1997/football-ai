# Player Impact and Decision Verification

Date: 2026-08-27

## Runtime

- Web: `http://127.0.0.1:3002/matches/sportsdb-2506175`
- API: `http://127.0.0.1:8001`
- Fixture: 皇家马德里 vs 皇家社会
- Evidence source: `api-football-single-fixture+espn-evidence`

## Real Fixture Evidence

- Stable identity: 53 resolved player references, 3 explicitly unresolved away-team references.
- Public payload `original_name` count: 0.
- Key available home players include 裘德·贝林厄姆、阿尔达·居勒尔、蒂博·库尔图瓦、基利安·姆巴佩、维尼修斯 and 邓弗里斯.
- Key home absences include 费兰·门迪、埃德尔·米利唐、劳尔·阿森西奥 and 奥雷利安·琼阿梅尼.
- Home attack/defense retention: 100% / 100%; squad depth prevents a count-based injury penalty.
- Market value status: unavailable. No authorized, redisplay-approved source covering all three leagues was connected.

## Forecast and Decision

- DeepSeek cached forecast: home 78%; home break-even 83.33%; home edge -6.4%; deterministic `no_bet`; stake 0.
- GPT cached forecast: home 81%; home break-even 83.33%; home edge -2.8%; deterministic `no_bet`; stake 0.
- Both cached forecasts use legacy v2 prompts. The page labels their explanations as historical, retains their probabilities, and blocks new execution because they lack `fixture-evidence-v3` player evidence.
- A stale handicap distribution is never reused when the current Asian line differs from the forecast line.

## Browser QA

- Desktop 1440x1000: document width 1440, no horizontal overflow, no page errors.
- Mobile 390x844: document/body width 390, no horizontal overflow, no page errors.
- Both model tabs render `本场不下注`; the GPT tab was switched interactively and its panel/model state matched.
- API fixture requests returned HTTP 200 from port 8001.

Screenshots:

- `real-madrid-desktop.png`
- `real-madrid-mobile.png`

## Automated Verification

- API: 105 passed; one existing Starlette/httpx deprecation warning.
- Frontend lint: passed.
- TypeScript `--noEmit`: passed.
- Next.js production build: passed; 10 routes generated.
