# Football AI Design System

## Design Principle
Use a restrained sports-data aesthetic. The primary visual hierarchy comes from typography, spacing, alignment and information grouping—not gradients or large decorative backgrounds.

## Color Tokens
Use the existing project token mechanism when available. Do not introduce a second styling system.

Suggested semantic values:

| Token | Value |
|---|---|
| primary | `#2563EB` |
| primary-hover | `#1D4ED8` |
| background | `#F8FAFC` |
| surface | `#FFFFFF` |
| surface-subtle | `#F1F5F9` |
| border | `#E2E8F0` |
| text-primary | `#0F172A` |
| text-secondary | `#475569` |
| text-muted | `#94A3B8` |
| success | `#10B981` |
| warning | `#F59E0B` |
| danger | `#EF4444` |

## Typography
- Page title: 32–40px, bold
- Section title: 18–24px, semibold
- Card metric: 24–32px, bold
- Body: 14–16px
- Metadata: 12–13px
- Avoid excessive uppercase labels.

## Spacing
Use a small consistent scale:
`4, 8, 12, 16, 20, 24, 32, 40, 48`

Default page rhythm:
- page horizontal padding: 24–40px desktop
- section gap: 24px
- card padding: 16–24px
- dense table row: 48–56px

## Shape and Elevation
- small radius: 8px
- card radius: 12px
- large container: 16px
- border first, shadow second
- use subtle elevation only for hover or important floating controls

## Status Semantics
Use consistent badges:
- Ready / complete: success
- Partial / waiting: warning
- Failed / missing critical data: danger
- Informational / scheduled: neutral or primary

Never use color as the only indicator. Include text or icon.

## Information Density
The application is analytical. Avoid oversized empty hero sections. Important metrics should be visible above the fold, but each card must have one clear purpose.

## Accessibility
- minimum readable contrast
- visible keyboard focus
- semantic button/link behavior
- tooltips for icon-only controls
- responsive tables must remain understandable
