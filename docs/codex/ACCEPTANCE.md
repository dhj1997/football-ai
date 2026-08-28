# UI Redesign Acceptance Checklist

## Functional
- [ ] Existing routes still work
- [ ] Existing filters still work
- [ ] Existing API contracts unchanged
- [ ] No fabricated football data
- [ ] Missing/partial evidence remains explicit
- [ ] Model outputs remain auditable
- [ ] Simulation behavior unchanged
- [ ] Admin security behavior unchanged

## Visual
- [ ] Consistent spacing
- [ ] Consistent card system
- [ ] Clear page hierarchy
- [ ] Status semantics consistent
- [ ] No unnecessary gradients/decorative noise
- [ ] Important data visible above the fold

## Responsive
- [ ] 1440px
- [ ] 1024px
- [ ] 768px
- [ ] 390px
- [ ] No accidental horizontal overflow

## Quality
- [ ] Relevant lint passes
- [ ] Relevant type checks pass
- [ ] Production build passes
- [ ] Existing automated tests still pass where applicable

## Final Report
Codex must report:
1. changed files
2. components added/changed
3. commands run
4. verification results
5. known limitations
