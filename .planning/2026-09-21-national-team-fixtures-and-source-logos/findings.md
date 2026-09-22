# Findings: National-Team Fixtures and Source Logos

## Source probes

- Dongqiudi public `match_list` returned 225 current football matches and
  real team logo fields, but competition logo was empty in the sampled rows.
- TheSportsDB team search returned stable IDs: China senior `134579` and
  China U23 `150660`.
- TheSportsDB returned next fixtures for both: China vs Maldives in
  International Friendlies and China U23 vs United Arab Emirates U23 in Asian
  Games Soccer.
- TheSportsDB `lookupleague.php` returned real badge/logo URLs for EPL,
  LaLiga, CSL, China FA Cup, UCL, World Cup, International Friendlies,
  Asian Games Soccer, and AFC World Cup Qualifying.

## Existing code gaps

- `TheSportsDbProvider.LEAGUE_IDS` only covers EPL, LaLiga, CSL, CFA Cup,
  UCL, and World Cup even though broader normalized keys already exist.
- `LeagueIcon` in the frontend is generated SVG art and does not read source
  logo metadata.
- `DongqiudiProvider` recognizes several international competition labels but
  has no gender/age-group eligibility contract.
- The fixture API currently returns league/team fields but no normalized logo
  source/cache metadata.

## Scope decisions

- No China-only UI tab.
- Men's senior worldwide; men's U23 Asia only.
- Exclude all women's competitions, CONCACAF Gold Cup, and OFC Nations Cup.
- Keep source gaps explicit; never synthesize missing fixtures or logos.
