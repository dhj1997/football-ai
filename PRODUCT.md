# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated through the approved design: Next.js and TypeScript for the web application, Python and FastAPI for the API and model runtime, PostgreSQL in production, and SQLite as the zero-setup local development database.

## Users

Football readers compare fixtures and inspect published pre-match probability analysis. An authenticated operator selects individual fixtures, refreshes known pre-match inputs, runs the model, and publishes a reviewed prediction.

## Product Purpose

The product displays current and historical fixtures for the Chinese Super League, La Liga, and Premier League. It creates an auditable prediction only when an operator requests one, using information known before kickoff: recent matches, head-to-head results, squad availability, confirmed lineups when available, and the latest pre-match odds.

## Positioning

Every published probability is attached to a timestamped evidence snapshot and model version. The product distinguishes preliminary analysis from confirmed-lineup analysis instead of presenting undated automated tips.

## Operating Context

Visitors scan today, tomorrow, and historical fixtures, then open published analyses. Operators work shortly before kickoff, when confirmed lineups and updated pre-match odds may become available, and can regenerate a prediction without overwriting its earlier version.

## Capabilities and Constraints

- Target leagues are the Chinese Super League, La Liga, and Premier League.
- Predictions are initiated manually and cover 1X2 and Asian handicap settlement probabilities.
- The MVP does not fetch or display in-play odds and does not accept wagers or payments.
- API-Football is the initial external provider; availability varies by fixture and league-season coverage.
- The free provider allowance is protected through server-side caching, idempotent runs, and operator-only refresh actions.
- Missing confirmed lineups produce a clearly labeled preliminary prediction.
- Missing handicap odds never produce an invented handicap market.
- Demonstration fixtures and predictions are labeled as sample data until a provider key is configured.

## Evidence on Hand

The approved development design is stored at `D:\Work\足球AI比赛预测网站-开发设计.md`. No customer claims, performance claims, production model artifacts, brand assets, or licensed team imagery have been supplied and none may be fabricated.

## Product Principles

- Show when every input was known.
- Keep browsing separate from operator-controlled prediction runs.
- Express uncertainty as calibrated probability, never certainty.
- Degrade explicitly when lineup, injury, or odds data is missing.
- Prefer a small, inspectable model pipeline over opaque generated advice.

## Accessibility & Inclusion

The web application targets WCAG 2.2 AA for keyboard access, focus visibility, color contrast, responsive layouts, and reduced-motion preferences. Probabilities must never rely on color alone.
