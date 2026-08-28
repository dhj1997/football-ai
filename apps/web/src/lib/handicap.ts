export type HandicapSide = "home" | "away";

export function handicapLineForSide(homeLine: number, side: HandicapSide) {
  const line = side === "home" ? homeLine : -homeLine;
  return Object.is(line, -0) ? 0 : line;
}

export function formatHandicapLine(line: number) {
  const normalized = Object.is(line, -0) ? 0 : line;
  return normalized > 0 ? `+${normalized}` : `${normalized}`;
}

export function formatHandicapSide(homeLine: number, side: HandicapSide, teamLabel?: string) {
  const line = handicapLineForSide(homeLine, side);
  const label = teamLabel ?? (side === "home" ? "主队" : "客队");
  const role = line < 0 ? "让球" : line > 0 ? "受让" : "平手";
  return `${label}${role} ${formatHandicapLine(line)}`;
}

export function formatFavoriteHandicap(homeLine: number, homeTeam: string, awayTeam: string) {
  if (homeLine < 0) return formatHandicapSide(homeLine, "home", homeTeam);
  if (homeLine > 0) return formatHandicapSide(homeLine, "away", awayTeam);
  return "双方平手 0";
}
