"use client";

import Image from "next/image";

import type { RecentMatch } from "@/lib/types";

export interface RecentFormTeam {
  name: string;
  logo?: string | null;
  side: "home" | "away";
}

interface RecentFormCompareProps {
  homeTeam: RecentFormTeam;
  awayTeam: RecentFormTeam;
  recentForm: {
    home: Array<RecentMatch | string>;
    away: Array<RecentMatch | string>;
    home_points_per_game?: number | null;
    away_points_per_game?: number | null;
  };
}

const LEVELS = [
  { key: "W", label: "胜", y: 10 },
  { key: "D", label: "平", y: 48 },
  { key: "L", label: "负", y: 86 },
] as const;

function normalizeMatches(rows: Array<RecentMatch | string>): RecentMatch[] {
  return rows.filter((row): row is RecentMatch => typeof row === "object" && row !== null && Boolean(row.score));
}

function parseScore(score: string): [number, number] | null {
  const match = /(\d+)\s*-\s*(\d+)/.exec(score);
  return match ? [Number(match[1]), Number(match[2])] : null;
}

function FormTrend({ matches }: { matches: RecentMatch[] }) {
  const chronological = [...matches].reverse();
  const width = 320;
  const height = 96;
  const step = chronological.length > 1 ? (width - 40) / (chronological.length - 1) : 0;
  const points = chronological.map((match, index) => {
    const level = LEVELS.find((item) => item.key === match.result) ?? LEVELS[1];
    return { x: 34 + index * step, y: level.y, result: match.result };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = points.length
    ? `34,86 ${line} ${points[points.length - 1].x},86`
    : "";

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="mt-3 w-full"
      role="img"
      aria-label="胜平负走势图"
    >
      {LEVELS.map((level) => (
        <g key={level.key}>
          <text x={6} y={level.y + 4} fontSize={11} fill={level.key === "W" ? "#fbbf24" : level.key === "D" ? "#94a3b8" : "#64748b"}>
            {level.label}
          </text>
          <line x1={24} y1={level.y} x2={width - 6} y2={level.y} stroke="#1e293b" strokeDasharray="3 4" />
        </g>
      ))}
      {points.length > 1 && <polygon points={area} fill="rgba(245,158,11,0.14)" />}
      {points.length > 1 && (
        <polyline points={line} fill="none" stroke="#f59e0b" strokeWidth={2} strokeLinejoin="round" />
      )}
      {points.map((point) => (
        <circle key={`${point.x}-${point.y}`} cx={point.x} cy={point.y} r={3.2} fill="#f59e0b" />
      ))}
    </svg>
  );
}

function RecentFormSide({ team, matches }: { team: RecentFormTeam; matches: RecentMatch[] }) {
  const wins = matches.filter((match) => match.result === "W").length;
  const draws = matches.filter((match) => match.result === "D").length;
  const losses = matches.filter((match) => match.result === "L").length;
  let goalsFor = 0;
  let goalsAgainst = 0;
  for (const match of matches) {
    const parsed = parseScore(match.score);
    if (!parsed) continue;
    const [homeGoals, awayGoals] = parsed;
    const teamIsHome = match.team_is_home ?? match.home === team.name;
    goalsFor += teamIsHome ? homeGoals : awayGoals;
    goalsAgainst += teamIsHome ? awayGoals : homeGoals;
  }
  const hasCompetition = matches.some((match) => match.competition);
  const hasHalfTime = matches.some((match) => match.half_time);
  const columns = [
    hasCompetition ? "3.5rem" : null,
    "5.5rem",
    "minmax(0,1fr)",
    "4.5rem",
    "minmax(0,1fr)",
    hasHalfTime ? "3.5rem" : null,
  ].filter(Boolean) as string[];
  const gridTemplate = columns.join(" ");

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-pitch-950">
      <header className="flex items-center gap-2.5 border-b border-slate-800 bg-pitch-900/60 px-3 py-2.5">
        {team.logo ? (
          <Image src={team.logo} alt="" width={22} height={22} className="h-[22px] w-[22px] object-contain" unoptimized />
        ) : null}
        <strong className="min-w-0 truncate text-sm font-bold text-white">{team.name}</strong>
        <small className="ml-auto shrink-0 text-[11px] text-slate-500">{team.side}</small>
      </header>
      <div role="table" aria-label={`${team.name}近期战绩`}>
        <div
          className="grid gap-2 border-b border-slate-800 bg-pitch-950 px-3 py-2 font-mono text-[11px] font-semibold tracking-wider text-slate-400"
          style={{ gridTemplateColumns: gridTemplate }}
          role="row"
        >
          {hasCompetition && <span>赛事</span>}
          <span>日期</span>
          <span className="text-right">主队</span>
          <span className="text-center">比分</span>
          <span>客队</span>
          {hasHalfTime && <span className="text-right">半场</span>}
        </div>
        {matches.map((match, index) => {
          const trackedIsHome = match.team_is_home ?? match.home === team.name;
          const won = match.result === "W";
          const drew = match.result === "D";
          return (
            <div
              key={`${match.date}-${match.home}-${match.away}-${index}`}
              className="grid items-center gap-2 border-b border-slate-800/60 px-3 py-2 text-xs text-slate-300 last:border-b-0 hover:bg-slate-800/30"
              style={{ gridTemplateColumns: gridTemplate }}
              role="row"
            >
              {hasCompetition && <span className="truncate text-slate-500">{match.competition ?? "—"}</span>}
              <time className="font-mono tabular-nums text-slate-500">{match.date?.slice(5) ?? match.date}</time>
              <span className={`min-w-0 truncate text-right ${won && trackedIsHome ? "font-semibold text-amber-400" : drew ? "text-slate-300" : "text-slate-400"}`}>
                {match.home}
              </span>
              <span className={`text-center font-mono font-bold tabular-nums ${drew ? "text-sky-400" : won ? "text-amber-400" : "text-slate-300"}`}>
                {match.score}
              </span>
              <span className={`min-w-0 truncate ${won && !trackedIsHome ? "font-semibold text-amber-400" : drew ? "text-slate-300" : "text-slate-400"}`}>
                {match.away}
              </span>
              {hasHalfTime && (
                <span className="text-right font-mono tabular-nums text-slate-500">{match.half_time ?? "—"}</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="px-3 pb-2">
        <FormTrend matches={matches} />
        <p className="mt-1 text-[11px] text-slate-500">
          近{matches.length}场，胜 <b className="text-amber-400">{wins}</b> 平{" "}
          <b className="text-slate-300">{draws}</b> 负 <b className="text-slate-400">{losses}</b>；进球{" "}
          <b className="text-emerald-400">{goalsFor}</b> 失球{" "}
          <b className="text-rose-400">{goalsAgainst}</b>
        </p>
      </div>
    </div>
  );
}

export function RecentFormCompare({ homeTeam, awayTeam, recentForm }: RecentFormCompareProps) {
  const homeMatches = normalizeMatches(recentForm.home);
  const awayMatches = normalizeMatches(recentForm.away);
  if (!homeMatches.length && !awayMatches.length) {
    return (
      <p className="rounded-xl border border-slate-800 bg-pitch-950 px-4 py-6 text-center text-sm text-slate-500">
        暂无近期战绩样本
      </p>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <RecentFormSide team={homeTeam} matches={homeMatches} />
      <RecentFormSide team={awayTeam} matches={awayMatches} />
    </div>
  );
}
