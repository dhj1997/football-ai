# Responsive Rules

## Breakpoints
Use the project's existing breakpoint system. Suggested intent:
- desktop: >= 1280
- tablet: 768–1279
- mobile: < 768

## Desktop
Optimize for analytical scanning:
- multi-column layouts
- persistent context
- dense tables
- comparison views

## Tablet
- collapse secondary rails below primary content
- preserve major metric groups
- keep tabs horizontally scrollable if necessary

## Mobile
Do not simply shrink desktop tables.

Preferred transformations:
- tables -> horizontally scrollable when column relationships matter
- dense comparison -> stacked cards when relationships remain understandable
- sidebar/secondary summary -> below main content
- reduce page padding, not text readability

## Acceptance
Test at:
- 1440px
- 1024px
- 768px
- 390px

No horizontal overflow except intentional data-table scrolling.
