# National-Team Fixtures and Source Logos Design

## Scope

Add source-backed national-team fixture coverage to the existing fixture
browser without creating a China-team-only entry point. Fixtures remain
discoverable through competition filters and are grouped separately from club
leagues.

Included:

- Men's senior national teams worldwide.
- Men's U23 teams only in Asian competitions.
- National-team friendlies and invitation matches.
- FIFA World Cup and its confederation qualifiers worldwide.
- AFC Asian Cup, Asian qualifiers, and men's U23 Asian competitions including
  Asian Games football.
- UEFA European Championship and qualifiers, UEFA Nations League, CAF Africa
  Cup of Nations and qualifiers, and CONMEBOL Copa America and qualifiers.

Explicitly excluded:

- All women's competitions and women's national teams.
- CONCACAF Gold Cup.
- OFC Nations Cup / Oceania Cup.
- Men's U23 competitions outside Asia.

When a source does not provide a requested competition or fixture, the system
records the source gap and does not fabricate a row.

## Source and Normalization

Use a versioned national-competition registry as the single normalization layer.
Each definition contains:

- stable internal key;
- confederation and competition type;
- gender and age group;
- provider IDs for TheSportsDB and Dongqiudi when available;
- source-backed logo URL, local cache path, source name, and captured time;
- whether fixtures can enter prediction and simulated-portfolio flows.

TheSportsDB is the primary global source for national-team fixtures, team
badges, and competition badges. Dongqiudi supplements China and Asian fixture
coverage and score refreshes. Provider rows are merged by stable provider IDs,
then by kickoff and normalized teams; ambiguous matches remain separate and
are reported for review.

The provider layer must preserve the original source fields while exposing
Chinese team names through the existing `to_chinese_team_name` contract. A
fixture is eligible only when its normalized gender and age-group metadata
matches the scope above.

## Logo Handling

Replace generated league SVG art in fixture and performance league selectors
with source-backed image assets. Logos are downloaded or copied into a local
static cache during synchronization, with source URL, checksum, and captured
time stored in the registry. The UI renders the cached asset and provides a
neutral text badge only when the source has no image. No provider logo is
hot-linked from the browser at runtime.

Team badges follow the same source-first rule. Existing provider logos remain
valid historical data and are not rewritten retroactively unless a later sync
has a verified source asset.

## UI and API

- Keep the existing competition filter model; do not add a China-only tab.
- Add a national-team competition group/filter that can show all included
  national competitions together or one competition at a time.
- Return normalized competition metadata, source, logo URL/cache key,
  confederation, gender, and age group in fixture list and detail payloads.
- Show an explicit source-gap state when a configured competition has no
  provider data; do not show a fabricated empty fixture as real coverage.
- Preserve existing club league filters, prediction contracts, and historical
  financial records.

National-team fixtures without reliable market odds may be displayed and
predicted, but they must not enter simulated betting unless the existing odds,
data-quality, and risk gates pass.

## Verification

- Provider tests cover competition normalization, men's senior/U23 filtering,
  women's and excluded Gold Cup/Oceania Cup rejection, team badges, and source
  metadata.
- Registry tests cover every included competition key and explicit exclusions.
- API tests verify competition filters and logo metadata in list/detail
  responses.
- Frontend tests/type checks verify image-backed logos and the no-China-tab
  layout.
- Production verification checks MySQL fixture counts, source timestamps,
  public list/detail routes, and that no excluded competition enters the
  synchronized cache.
