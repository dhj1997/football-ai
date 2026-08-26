# Score Center UI Redesign

## Decision

Replace the dashboard-like public interface with a professional football score center. The existing API contracts, prediction workflow, data sources, and routes remain intact; the web client changes presentation and navigation only.

## Information Architecture

- The home page is the score center: date and status filters, league-grouped match rows, then a compact side rail on desktop.
- Selecting a match opens an independent match detail route. The page begins with the score/state header and uses tabs for overview, AI analysis, head-to-head, squads, and odds.
- Standings, team, and performance pages reuse the same neutral shell, dense tables, active-tab treatment, and status language.

## Visual System

- Bright neutral background with white data surfaces, thin gray separators, dark charcoal text, and compact typography.
- Blue is the primary interaction color; green marks live/positive states, amber marks pending states, and red remains reserved for warnings and negative results.
- Team crests are the primary visual assets. Remove decorative English eyebrows, large dashboard cards, and nested surface treatments.

## Responsive Behavior

- Desktop: wide score list with a modest secondary rail; data tables can scroll within their own container.
- Mobile: one-column match stream, horizontally scrollable filters, sticky detail tabs, and no document-level horizontal overflow.

## Verification

- Keep existing API behavior unchanged.
- Run web lint and production build.
- Verify desktop and mobile views in a browser, including fixture selection, match-detail navigation, tabs, and table scrolling.
