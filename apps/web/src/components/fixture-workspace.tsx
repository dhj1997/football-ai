"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  Gauge,
  Goal,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  Shirt,
  HeartPulse,
  Users,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  fetchFixtureDetail,
  fetchFixtures,
  prefetchFixtures,
  readCachedFixtures,
  readJson,
} from "@/lib/api";
import {
  formatFavoriteHandicap,
  formatHandicapLine,
  formatHandicapSide,
} from "@/lib/handicap";
import { to_chinese_player_name } from "@/lib/player-names";
import { canCreatePrediction, deriveMatchReport } from "@/lib/match-report";
import { OperationsPanel } from "@/components/operations-panel";
import { RecentFormCompare } from "@/components/recent-form-compare";
import { ModelConfigPanel } from "@/components/model-config-panel";
import {
  Card,
  DataFreshness,
  EmptyState,
  LoadingState,
  PageHeader,
  SectionHeader,
  StatusBadge,
  Tabs,
  type StatusVariant,
} from "@/components/ui";
import type {
  DateFilter,
  Fixture,
  FixtureDetail,
  LineupPlayer,
  ModelKey,
  Prediction,
  RecentMatch,
  SimulatedBet,
  SquadPlayer,
  TeamProfile,
} from "@/lib/types";

type DataMode = "cached" | "demo" | "empty" | "error" | "unconfigured";
type SyncStatus = "fresh" | "updated" | "stale" | "failed" | "unconfigured";

const dateTabs: Array<{ key: DateFilter; label: string }> = [
  { key: "yesterday", label: "昨日" },
  { key: "today", label: "今日" },
  { key: "tomorrow", label: "明日" },
  { key: "upcoming", label: "未来 7 天" },
  { key: "history", label: "历史" },
];

const FAVORITES_KEY = "greencompass:favorite-fixtures";

function readFavorites(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(FAVORITES_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function writeFavorites(ids: string[]) {
  try {
    window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(ids));
  } catch {
    return;
  }
}

function DateStrip({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (iso: string | null) => void;
}) {
  const today = new Date();
  const days: Array<{ iso: string; day: string; date: string; isToday: boolean }> = [];
  for (let offset = -3; offset <= 10; offset += 1) {
    const d = new Date(today);
    d.setDate(today.getDate() + offset);
    const iso = d.toLocaleDateString("sv-SE");
    days.push({
      iso,
      day: offset === 0 ? "今天" : ["日", "一", "二", "三", "四", "五", "六"][d.getDay()],
      date: `${d.getMonth() + 1}/${d.getDate()}`,
      isToday: offset === 0,
    });
  }
  return (
    <div className="flex items-center gap-1 overflow-x-auto" role="tablist" aria-label="按日期查看赛程">
      {days.map((day) => {
        const activeDay = selected === day.iso;
        return (
          <button
            key={day.iso}
            type="button"
            role="tab"
            aria-selected={activeDay}
            onClick={() => onSelect(activeDay ? null : day.iso)}
            className={`shrink-0 rounded-lg px-2.5 py-1.5 text-center transition-colors ${
              activeDay
                ? "bg-amber-500/20 text-amber-400"
                : day.isToday
                  ? "bg-pitch-800 text-slate-200 hover:bg-slate-700/50"
                  : "text-slate-500 hover:bg-slate-800/40 hover:text-slate-300"
            }`}
          >
            <span className="block text-[10px] leading-none">{day.day}</span>
            <span className="mt-0.5 block font-mono text-xs font-semibold leading-none">
              {day.date}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// Tailwind 工具类复用片段（替代原全局 CSS 类）。
const eyebrowClass =
  "text-[10px] font-bold uppercase tracking-wider font-mono text-blue-400";
const mutedNoteClass =
  "rounded-xl border border-dashed border-slate-700 px-3 py-2 text-xs leading-relaxed text-slate-500";
const sourceNoteClass = "mt-3 text-[11px] leading-relaxed text-slate-500";
const signalReadyClass =
  "inline-flex items-center gap-1 rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400";
const signalWaitingClass =
  "inline-flex items-center gap-1 rounded border border-slate-500/20 bg-slate-500/10 px-1.5 py-0.5 text-[10px] font-medium text-slate-400";
const signalPredictedClass =
  "inline-flex items-center gap-1 rounded border border-purple-500/30 bg-purple-500/15 px-1.5 py-0.5 text-[10px] font-medium text-purple-300";
const manualPredictButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-400 transition-colors hover:bg-blue-500/20 disabled:opacity-60";
const iconButtonSecondaryClass =
  "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-800 text-slate-300 transition-colors hover:bg-slate-700 disabled:opacity-60";
const syncActionClass =
  "inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-2.5 py-1.5 text-xs font-bold text-white shadow-md shadow-blue-600/30 transition-colors hover:bg-blue-500 disabled:opacity-60";
const syncActionSecondaryClass =
  "inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs font-semibold text-slate-300 transition-colors hover:bg-slate-700 disabled:opacity-60";
const primaryButtonClass =
  "inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-3.5 text-xs font-bold text-white shadow-md shadow-blue-600/30 transition-colors hover:bg-blue-500 disabled:opacity-60";
const ctaButtonClass =
  "inline-flex w-full items-center justify-center gap-1 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 py-3 text-xs font-bold text-white shadow-lg shadow-blue-500/20 transition-colors hover:from-blue-500 hover:to-indigo-500";
const scoreToneClass = {
  winner: "text-rose-400",
  loser: "text-emerald-400",
  draw: "text-slate-200",
} as const;
const rowResultToneClass: Record<string, string> = {
  "home-win": "text-slate-200",
  "away-win": "text-slate-200",
  draw: "text-slate-400",
  pending: "text-slate-500",
};
const factorToneClass: Record<string, string> = {
  home: "text-rose-400",
  away: "text-emerald-400",
  neutral: "text-slate-400",
  warning: "text-amber-400",
};
const riskToneVariant: Record<string, StatusVariant> = {
  waiting: "neutral",
  danger: "danger",
  warning: "partial",
  ready: "ready",
};
// 联赛分组头固定色点（设计稿：epl 蓝 / 西甲 amber / 中超 rose / 其他 slate）。
const leagueDotClass: Record<string, string> = {
  epl: "bg-blue-500",
  laliga: "bg-amber-500",
  csl: "bg-rose-500",
};
const leagueDotFallback = "bg-slate-500";
const leagueDot = (key: string) => leagueDotClass[key] ?? leagueDotFallback;

const percent = (value: number) => `${Math.round(value * 100)}%`;
function handicapRecommendation(
  settlement: NonNullable<Prediction["asian_handicap"]>["home_settlement"],
  line: number,
  homeTeam: string,
  awayTeam: string,
) {
  const homePositive = settlement.full_win + settlement.half_win;
  const homeNegative = settlement.full_loss + settlement.half_loss;
  const recommendsHome = homePositive >= homeNegative;
  return recommendsHome
    ? formatHandicapSide(line, "home", homeTeam)
    : formatHandicapSide(line, "away", awayTeam);
}

function selectionWithHandicap(
  value: string | undefined,
  homeLine: number | null | undefined,
) {
  if (homeLine !== null && homeLine !== undefined && value === "home_handicap")
    return formatHandicapSide(homeLine, "home");
  if (homeLine !== null && homeLine !== undefined && value === "away_handicap")
    return formatHandicapSide(homeLine, "away");
  return selectionText(value);
}

const settlementLabels = {
  full_win: "全赢",
  half_win: "半赢",
  push: "走盘",
  half_loss: "半输",
  full_loss: "全输",
} as const;

function formatKickoff(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatTimestamp(value: string | null) {
  if (!value) return "待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatPreciseTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function Scoreline({
  home,
  away,
  large = false,
}: {
  home: number | string;
  away: number | string;
  large?: boolean;
}) {
  const homeScore = Number(home);
  const awayScore = Number(away);
  const homeTone =
    homeScore > awayScore
      ? scoreToneClass.winner
      : homeScore < awayScore
        ? scoreToneClass.loser
        : scoreToneClass.draw;
  const awayTone =
    awayScore > homeScore
      ? scoreToneClass.winner
      : awayScore < homeScore
        ? scoreToneClass.loser
        : scoreToneClass.draw;
  if (large)
    return (
      <span
        className="inline-flex items-baseline gap-2 font-mono text-4xl font-black tabular-nums"
        aria-label={`${home} 比 ${away}`}
      >
        <b className={homeTone}>{home}</b>
        <i className="text-xl font-normal not-italic text-slate-500">:</i>
        <b className={awayTone}>{away}</b>
      </span>
    );
  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800 px-2 py-0.5 font-mono text-xs font-bold tabular-nums text-amber-400"
      aria-label={`${home} 比 ${away}`}
    >
      {home}
      <i className="font-normal not-italic text-amber-400/60">:</i>
      {away}
    </span>
  );
}

function ParsedScoreline({ score }: { score: string }) {
  const match = score.match(/(\d+)\s*[-:]\s*(\d+)/);
  return match ? (
    <Scoreline home={match[1]} away={match[2]} />
  ) : (
    <strong className="font-mono text-sm font-bold tabular-nums text-slate-200">
      {score}
    </strong>
  );
}

function TeamMark({
  team,
  tone,
}: {
  team: Fixture["home_team"];
  tone: "home" | "away";
}) {
  if (team.logo) {
    return (
      <Image
        className="h-7 w-7 shrink-0 rounded-full border border-slate-700 bg-pitch-800 object-contain p-0.5"
        src={team.logo}
        alt=""
        width={28}
        height={28}
        unoptimized
      />
    );
  }
  return (
    <span
      className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-700 text-[11px] font-bold ${
        tone === "home"
          ? "bg-blue-500/10 text-blue-300"
          : "bg-slate-500/10 text-slate-300"
      }`}
      aria-hidden="true"
    >
      {team.code.slice(0, 3)}
    </span>
  );
}

function formatOdds(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(2)
    : "-";
}

// 展示层统一使用中性名称；存量数据里的供应商品牌名在这里映射掉。
function marketSourceLabel(value: string | null | undefined) {
  const name = (value ?? "").trim();
  if (/bet\s*3/i.test(name) || name.includes("365")) return "市场参考A";
  if (name.includes("皇") || name.toLowerCase().includes("crown"))
    return "市场参考B";
  return name || "-";
}

function FixtureRow({
  fixture,
  selected = false,
  onSelect,
  href,
  isFavorite = false,
  onToggleFavorite,
}: {
  fixture: Fixture;
  selected?: boolean;
  onSelect?: () => void;
  href?: string;
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
}) {
  const [renderedAt] = useState(() => Date.now());
  const kickoffHasPassed = new Date(fixture.kickoff).getTime() <= renderedAt;
  const statusText = {
    scheduled: kickoffHasPassed
      ? "状态待更新"
      : fixture.lineup_confirmed
        ? "首发已确认"
        : "等待首发",
    finished: "完场",
    postponed: "延期",
    cancelled: "取消",
    live: "进行中",
  }[fixture.status];
  const resultLabel = fixture.score
    ? fixture.score.home > fixture.score.away
      ? "主胜"
      : fixture.score.home < fixture.score.away
        ? "客胜"
        : "平局"
    : null;
  const resultTone = fixture.score
    ? fixture.score.home > fixture.score.away
      ? "home-win"
      : fixture.score.home < fixture.score.away
        ? "away-win"
        : "draw"
    : "pending";
  const rowStatusVariant: StatusVariant =
    fixture.status === "live"
      ? "live"
      : fixture.status === "finished"
        ? "neutral"
        : fixture.status === "postponed" || fixture.status === "cancelled"
          ? "danger"
          : kickoffHasPassed
            ? "partial"
            : fixture.lineup_confirmed
              ? "ready"
              : "neutral";
  const readyCount =
    fixture.evidence_summary?.ready_count ?? (fixture.lineup_confirmed ? 4 : 3);
  const totalCount = fixture.evidence_summary?.total_count ?? 4;

  const content = (
    <>
      {onToggleFavorite ? (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggleFavorite();
          }}
          aria-label={isFavorite ? "取消关注" : "关注这场比赛"}
          aria-pressed={isFavorite}
          className={`shrink-0 self-center text-sm leading-none transition-colors ${
            isFavorite ? "text-amber-400" : "text-slate-600 hover:text-slate-400"
          }`}
        >
          {isFavorite ? "★" : "☆"}
        </button>
      ) : null}
      <div className="flex w-20 sm:w-24 shrink-0 flex-col items-start gap-1">
        <strong className="font-mono text-xs font-bold tabular-nums text-slate-200">
          {formatKickoff(fixture.kickoff)}
        </strong>
        <span
          className="inline-flex max-w-full items-center gap-1 rounded border border-slate-700/80 bg-pitch-900 px-1.5 py-0.5 text-xs font-medium text-slate-300"
          title={fixture.league.name || fixture.league_key.toUpperCase()}
          aria-label={`联赛 ${fixture.league.name || fixture.league_key.toUpperCase()}`}
        >
          <i
            aria-hidden="true"
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${leagueDot(fixture.league_key)}`}
          />
          <span className="truncate">
            {fixture.league.name || fixture.league_key.toUpperCase()}
          </span>
        </span>
        <StatusBadge variant={rowStatusVariant}>{statusText}</StatusBadge>
      </div>

      {/* 对称主客队布局：主队靠右对齐、比分/VS居中、客队靠左对齐 */}
      <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
        <div className="flex flex-1 items-center justify-end gap-2 min-w-0 text-right">
          <b
            className={`truncate text-sm sm:text-base font-bold transition-colors ${
              fixture.score ? "text-white" : "text-slate-100"
            }`}
            title={fixture.home_team.name}
          >
            {fixture.home_team.name}
          </b>
          <TeamMark team={fixture.home_team} tone="home" />
        </div>
        <div className="flex shrink-0 flex-col items-center justify-center w-12 sm:w-16">
          {fixture.score ? (
            <div className="flex flex-col items-center gap-0.5">
              <Scoreline home={fixture.score.home} away={fixture.score.away} />
              <small className={`text-xs font-medium ${rowResultToneClass[resultTone]}`}>
                {resultLabel}
              </small>
            </div>
          ) : (
            <span className="rounded-full border border-slate-700/80 bg-pitch-900 px-2 py-0.5 font-mono text-xs font-bold text-slate-400">
              VS
            </span>
          )}
        </div>
        <div className="flex flex-1 items-center justify-start gap-2 min-w-0 text-left">
          <TeamMark team={fixture.away_team} tone="away" />
          <b
            className={`truncate text-sm sm:text-base font-bold transition-colors ${
              fixture.score ? "text-white" : "text-slate-100"
            }`}
            title={fixture.away_team.name}
          >
            {fixture.away_team.name}
          </b>
        </div>
      </div>

      {/* 胜平负多盘口水位微缩条（超宽屏幕展示，避免挤压球队名） */}
      {fixture.odds_summary ? (
        <div
          className="hidden shrink-0 items-center rounded-lg border border-slate-800 bg-pitch-950/80 px-1.5 py-1 2xl:flex"
          aria-label="胜平负赔率"
          title={`赔率更新 ${fixture.odds_summary.updated_at ?? "未知"}`}
        >
          <div className="flex flex-col items-center px-2 py-0.5">
            <span className="text-[10px] font-medium text-slate-500">主胜</span>
            <span className="font-mono text-xs font-bold tabular-nums text-amber-400">
              {fixture.odds_summary.home.toFixed(2)}
            </span>
          </div>
          <div className="h-5 w-px bg-slate-800" aria-hidden="true" />
          <div className="flex flex-col items-center px-2 py-0.5">
            <span className="text-[10px] font-medium text-slate-500">平局</span>
            <span className="font-mono text-xs font-bold tabular-nums text-slate-300">
              {fixture.odds_summary.draw.toFixed(2)}
            </span>
          </div>
          <div className="h-5 w-px bg-slate-800" aria-hidden="true" />
          <div className="flex flex-col items-center px-2 py-0.5">
            <span className="text-[10px] font-medium text-slate-500">客胜</span>
            <span className="font-mono text-xs font-bold tabular-nums text-sky-400">
              {fixture.odds_summary.away.toFixed(2)}
            </span>
          </div>
        </div>
      ) : null}

      {/* 证据轨道与模型推演状态条（动态指示灯轨） */}
      <div
        className="hidden shrink-0 flex-col items-end gap-1.5 sm:flex"
        aria-label="研究状态与证据轨道"
      >
        <div className="flex items-center gap-1.5">
          <span
            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
              readyCount >= totalCount ? signalReadyClass : signalWaitingClass
            }`}
            title={`证据准备就绪度 ${readyCount}/${totalCount}`}
          >
            <Database size={12} aria-hidden="true" />
            证据 {readyCount}/{totalCount}
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
              fixture.has_prediction
                ? signalPredictedClass
                : canCreatePrediction(fixture)
                  ? "border border-blue-500/30 bg-blue-500/10 text-blue-300"
                  : signalWaitingClass
            }`}
            title={
              fixture.has_prediction
                ? "已有模型预测"
                : canCreatePrediction(fixture)
                  ? "具备推演条件"
                  : "待同步证据"
            }
          >
            <Gauge size={12} aria-hidden="true" />
            {fixture.has_prediction
              ? "已推演"
              : canCreatePrediction(fixture)
                ? "可推演"
                : "待推演"}
          </span>
        </div>
        {/* 证据轨道指示灯（与证据总数精确对应） */}
        <div
          className="flex items-center gap-1"
          aria-label={`证据进度：${readyCount}项已就绪`}
          title={`证据维度准备进度 (${readyCount}/${totalCount})`}
        >
          {Array.from({ length: totalCount }).map((_, index) => {
            const isReady = index < readyCount;
            return (
              <span
                key={index}
                className={`h-1.5 w-2.5 rounded-full transition-all ${
                  isReady
                    ? "bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.4)]"
                    : "bg-slate-700/60"
                }`}
              />
            );
          })}
        </div>
      </div>
      <ChevronRight size={16} aria-hidden="true" className="shrink-0 text-slate-600" />
    </>
  );
  const className = `flex w-full items-center gap-3 border-l-4 p-4 text-left transition-colors ${
    selected
      ? "border-blue-500 bg-blue-500/5"
      : fixture.status === "live"
        ? "border-rose-500/70 bg-rose-500/5 hover:bg-rose-500/10"
        : "border-transparent hover:bg-slate-800/30"
  }${fixture.status === "finished" && !selected ? " opacity-55 saturate-[.6]" : ""}`;
  if (href)
    return (
      <Link
        className={className}
        href={href}
        aria-label={`${fixture.league.name} ${fixture.home_team.name} 对 ${fixture.away_team.name}`}
      >
        {content}
      </Link>
    );
  return (
    <button className={className} onClick={onSelect} aria-pressed={selected}>
      {content}
    </button>
  );
}

type FixtureLeagueGroup = {
  league: Fixture["league"];
  leagueKey: Fixture["league_key"];
  fixtures: Fixture[];
};

function groupFixturesByLeague(items: Fixture[]): FixtureLeagueGroup[] {
  return items.reduce<FixtureLeagueGroup[]>((result, fixture) => {
    const current = result.find(
      (group) => group.league.name === fixture.league.name,
    );
    if (current) current.fixtures.push(fixture);
    else
      result.push({
        league: fixture.league,
        leagueKey: fixture.league_key,
        fixtures: [fixture],
      });
    return result;
  }, []);
}

function FixtureGroupCard({
  group,
  selectedFixtureId,
  onSelect,
}: {
  group: FixtureLeagueGroup;
  selectedFixtureId: string | null;
  onSelect?: (fixtureId: string) => void;
}) {
  return (
    <Card className="overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-800/40 px-4 py-3">
        <span className="flex min-w-0 items-center gap-2.5">
          <i
            aria-hidden="true"
            className={`h-2 w-2 shrink-0 rounded-full ${leagueDot(group.leagueKey)}`}
          />
          <strong className="truncate text-xs font-bold text-white">
            {group.league.name}
          </strong>
          <small className="truncate text-[11px] text-slate-500">
            {group.league.country}
          </small>
        </span>
        <b className="shrink-0 font-mono text-[11px] tabular-nums text-slate-400">
          {group.fixtures.length} 场
        </b>
      </header>
      <div className="divide-y divide-slate-800/60">
        {group.fixtures.map((fixture) => (
          <FixtureRow
            key={fixture.id}
            fixture={fixture}
            selected={fixture.id === selectedFixtureId}
            href={
              onSelect ? undefined : `/matches/${encodeURIComponent(fixture.id)}`
            }
            onSelect={onSelect ? () => onSelect(fixture.id) : undefined}
          />
        ))}
      </div>
    </Card>
  );
}

function QuickResearchPanel({
  fixture,
  detail,
}: {
  fixture: Fixture | null;
  detail: FixtureDetail | null;
}) {
  if (!fixture)
    return (
      <EmptyState
        icon={<Database size={22} aria-hidden="true" />}
        className="min-h-48"
      >
        <strong className="text-sm font-semibold text-slate-200">
          选择一场比赛开始研究
        </strong>
        <span className="text-xs">比赛摘要将在这里显示</span>
      </EmptyState>
    );
  const readyDetail = detail?.fixture.id === fixture.id ? detail : null;
  const report = readyDetail ? deriveMatchReport(readyDetail) : null;
  const primaryPrediction =
    readyDetail?.prediction ??
    readyDetail?.predictions?.deepseek ??
    readyDetail?.predictions?.chatgpt ??
    null;
  const dualPredictions = readyDetail?.predictions;
  const evidenceReady =
    report?.evidenceReady ?? fixture.evidence_summary?.ready_count ?? 0;
  const evidenceTotal =
    report?.evidenceTotal ?? fixture.evidence_summary?.total_count ?? 4;
  const risk = !report
    ? { label: "读取中", tone: "waiting" }
    : report.evidenceQuality < 0.67
      ? { label: "谨慎", tone: "danger" }
      : report.evidenceQuality < 1 || report.agreement === null
        ? { label: "需复核", tone: "warning" }
        : report.agreement < 0.78
          ? { label: "模型分歧", tone: "danger" }
          : { label: "可研究", tone: "ready" };
  const probability = primaryPrediction?.probabilities ?? report?.probabilities;
  const maxProbability = probability
    ? Math.max(probability.home, probability.draw, probability.away)
    : 0;
  return (
    <Card className="flex flex-col gap-5 p-6" aria-label="快速研究摘要">
      <header className="space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className={eyebrowClass}>QUICK READOUT</span>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-2 py-0.5 text-xs font-medium text-slate-300">
            <i
              aria-hidden="true"
              className={`h-1.5 w-1.5 rounded-full ${leagueDot(fixture.league_key)}`}
            />
            {fixture.league.name}
          </span>
        </div>
        <h2 className="text-xl font-bold text-white">快速研究</h2>
        <h3 className="text-base sm:text-lg font-bold text-white">
          {fixture.home_team.name}{" "}
          <i className="px-0.5 text-xs font-normal not-italic text-slate-500">vs</i>{" "}
          {fixture.away_team.name}
        </h3>
        <p className="font-mono text-xs tabular-nums text-slate-400">
          {formatKickoff(fixture.kickoff)} · {fixture.venue || "场地待定"}
        </p>
      </header>
      {report ? (
        <>
          {/* AI 预测结果核心展示块（不受下注状态限制，只要有预测就如实展现） */}
          <div className="rounded-xl border border-blue-500/30 bg-blue-950/20 p-4 space-y-3.5 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="flex h-2.5 w-2.5 rounded-full bg-blue-400 shadow-[0_0_8px_rgba(96,165,250,0.6)]" />
                <span className="text-xs font-bold uppercase tracking-wider text-blue-300">
                  AI 智能推演预测
                </span>
              </div>
              <span className="inline-flex items-center rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 font-mono text-xs font-semibold text-blue-300">
                {primaryPrediction?.model_version ||
                  (primaryPrediction?.model_key === "deepseek"
                    ? "DeepSeek V3"
                    : primaryPrediction?.model_key === "chatgpt"
                      ? "GPT-5.6 Sol"
                      : "多模型推演")}
              </span>
            </div>

            {primaryPrediction ? (
              <>
                {/* 预测赛果、进球与置信度 */}
                <div className="grid grid-cols-3 gap-2 rounded-lg border border-slate-800 bg-pitch-950/80 p-3 text-center">
                  <div>
                    <span className="block text-xs text-slate-400">推演预测</span>
                    <strong className="mt-1 block text-base font-bold text-white">
                      {outcomeText(
                        primaryPrediction.forecast?.predicted_outcome ??
                          primaryPrediction.predicted_outcome ??
                          report.consensusOutcome,
                      )}
                    </strong>
                  </div>
                  <div>
                    <span className="block text-xs text-slate-400">预期进球 xG</span>
                    <strong className="mt-1 block font-mono text-base font-bold tabular-nums text-slate-200">
                      {primaryPrediction.expected_goals
                        ? `${primaryPrediction.expected_goals.home.toFixed(2)} : ${primaryPrediction.expected_goals.away.toFixed(2)}`
                        : "-"}
                    </strong>
                  </div>
                  <div>
                    <span className="block text-xs text-slate-400">置信度</span>
                    <strong className="mt-1 block font-mono text-base font-bold tabular-nums text-emerald-400">
                      {primaryPrediction.forecast_confidence
                        ? percent(primaryPrediction.forecast_confidence)
                        : primaryPrediction.confidence || "良好"}
                    </strong>
                  </div>
                </div>

                {/* 胜平负三项概率条 */}
                {probability && (
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs">
                      <span className="text-slate-400">胜平负概率</span>
                      <b className="font-mono font-bold tabular-nums text-slate-200">
                        主胜 {Math.round(probability.home * 100)}% · 平{" "}
                        {Math.round(probability.draw * 100)}% · 客胜{" "}
                        {Math.round(probability.away * 100)}%
                      </b>
                    </div>
                    <div
                      className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-800"
                      aria-hidden="true"
                    >
                      <i
                        className={`h-full ${probability.home === maxProbability ? "bg-rose-500" : "bg-blue-600"}`}
                        style={{ width: `${probability.home * 100}%` }}
                      />
                      <i
                        className={`h-full ${probability.draw === maxProbability ? "bg-rose-500" : "bg-slate-600"}`}
                        style={{ width: `${probability.draw * 100}%` }}
                      />
                      <i
                        className={`h-full ${probability.away === maxProbability ? "bg-rose-500" : "bg-amber-600"}`}
                        style={{ width: `${probability.away * 100}%` }}
                      />
                    </div>
                  </div>
                )}

                {/* 波胆预测比分 */}
                {primaryPrediction.top_scores && primaryPrediction.top_scores.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-slate-400">比分预测:</span>
                    {primaryPrediction.top_scores.slice(0, 3).map((item) => (
                      <span
                        key={item.score}
                        className="inline-flex items-center gap-1 rounded bg-pitch-900 border border-slate-800 px-2 py-0.5 font-mono text-xs font-bold text-slate-200"
                      >
                        {item.score}
                        <small className="font-normal text-slate-400">
                          {percent(item.probability)}
                        </small>
                      </span>
                    ))}
                  </div>
                )}

                {/* AI 核心研判摘要 */}
                {(primaryPrediction.analysis_summary ||
                  primaryPrediction.model_recommendation?.reason ||
                  primaryPrediction.recommendation?.reason) && (
                  <div className="rounded-lg bg-pitch-950/90 border border-slate-800/80 p-3 text-xs leading-relaxed text-slate-200">
                    <span className="block font-semibold text-blue-300 mb-1">
                      AI 研判要点:
                    </span>
                    <p className="line-clamp-4">
                      {primaryPrediction.analysis_summary ||
                        primaryPrediction.model_recommendation?.reason ||
                        primaryPrediction.recommendation?.reason}
                    </p>
                  </div>
                )}

                {/* 双模型并列对比（若同时包含 deepseek 和 chatgpt） */}
                {dualPredictions?.chatgpt && dualPredictions?.deepseek && (
                  <div className="grid grid-cols-2 gap-2 text-xs border-t border-slate-800/80 pt-2.5">
                    <div className="rounded bg-pitch-950/70 p-2.5 border border-slate-800/60">
                      <span className="font-semibold text-sky-400 block mb-0.5">GPT-5.6 Sol</span>
                      <span className="font-mono text-slate-200 text-xs">
                        {outcomeText(dualPredictions.chatgpt.predicted_outcome ?? dualPredictions.chatgpt.forecast?.predicted_outcome)} · 主{Math.round(dualPredictions.chatgpt.probabilities.home * 100)}% 平{Math.round(dualPredictions.chatgpt.probabilities.draw * 100)}% 客{Math.round(dualPredictions.chatgpt.probabilities.away * 100)}%
                      </span>
                    </div>
                    <div className="rounded bg-pitch-950/70 p-2.5 border border-slate-800/60">
                      <span className="font-semibold text-purple-400 block mb-0.5">DeepSeek V3</span>
                      <span className="font-mono text-slate-200 text-xs">
                        {outcomeText(dualPredictions.deepseek.predicted_outcome ?? dualPredictions.deepseek.forecast?.predicted_outcome)} · 主{Math.round(dualPredictions.deepseek.probabilities.home * 100)}% 平{Math.round(dualPredictions.deepseek.probabilities.draw * 100)}% 客{Math.round(dualPredictions.deepseek.probabilities.away * 100)}%
                      </span>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="rounded-lg bg-pitch-950/60 border border-slate-800/60 p-3 text-center text-xs text-slate-400">
                <p>当前比赛尚未生成详细 AI 推演</p>
                <Link
                  href={`/matches/${encodeURIComponent(fixture.id)}`}
                  className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-400 hover:text-blue-300"
                >
                  进入比赛详情一键推演
                  <ChevronRight size={14} aria-hidden="true" />
                </Link>
              </div>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3 rounded-xl border border-slate-800 bg-pitch-950 p-3.5">
            <div className="min-w-0 text-center">
              <small className="block text-xs text-slate-400">模型共识</small>
              <strong className="mt-1 block font-mono text-base font-bold tabular-nums text-white">
                {report.consensusOutcome === "home"
                  ? "主胜"
                  : report.consensusOutcome === "draw"
                    ? "平局"
                    : report.consensusOutcome === "away"
                      ? "客胜"
                      : "待生成"}
              </strong>
              <span className="mt-0.5 block text-xs text-slate-400">
                {report.models.length > 1
                  ? report.consensus.includes("一致")
                    ? "双模型同向"
                    : "方向分歧"
                  : report.models.length
                    ? "单模型"
                    : "无模型结果"}
              </span>
            </div>
            <div className="min-w-0 text-center">
              <small className="block text-xs text-slate-400">一致度</small>
              <strong className="mt-1 block font-mono text-base font-bold tabular-nums text-white">
                {report.agreement === null ? "-" : percent(report.agreement)}
              </strong>
              <span className="mt-0.5 block text-xs text-slate-400">模型概率差</span>
            </div>
            <div className="min-w-0 text-center">
              <small className="block text-xs text-slate-400">证据质量</small>
              <strong className="mt-1 block font-mono text-base font-bold tabular-nums text-white">
                {evidenceReady}/{evidenceTotal}
              </strong>
              <span className="mt-0.5 block text-xs text-slate-400">
                {percent(report.evidenceQuality)} 已就绪
              </span>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {report.factors.slice(0, 3).map((factor) => (
              <div key={factor.label} className="min-w-0">
                <small className="block text-xs text-slate-400">{factor.label}</small>
                <strong className="mt-0.5 block truncate text-sm font-semibold text-white">
                  {factor.value}
                </strong>
                <span className={`mt-0.5 block text-xs ${factorToneClass[factor.tone]}`}>
                  {factor.conclusion}
                </span>
              </div>
            ))}
            <div className="min-w-0">
              <small className="block text-xs text-slate-400">市场观察</small>
              <strong className="mt-0.5 block text-sm font-semibold text-white">
                {report.marketWatch}
              </strong>
              <span
                className={`mt-0.5 block text-xs ${readyDetail?.context.odds ? "text-slate-300" : "text-amber-400"}`}
              >
                {readyDetail?.context.odds ? "已纳入判断" : "不使用估算"}
              </span>
            </div>
          </div>
          <div
            className={`flex items-center justify-center rounded-xl border p-4 ${
              risk.tone === "danger"
                ? "border-rose-500/20 bg-rose-500/10"
                : risk.tone === "warning"
                  ? "border-amber-500/20 bg-amber-500/10"
                  : risk.tone === "ready"
                    ? "border-emerald-500/20 bg-emerald-500/10"
                    : "border-slate-700 bg-slate-800/30"
            }`}
          >
            <StatusBadge variant={riskToneVariant[risk.tone]}>{risk.label}</StatusBadge>
          </div>
        </>
      ) : (
        <div className="grid grid-cols-2 gap-2" aria-label="正在读取比赛摘要">
          <i className="h-14 animate-pulse rounded-lg bg-pitch-800" />
          <i className="h-14 animate-pulse rounded-lg bg-pitch-800" />
          <i className="h-14 animate-pulse rounded-lg bg-pitch-800" />
          <i className="h-14 animate-pulse rounded-lg bg-pitch-800" />
        </div>
      )}
      <footer className="mt-auto space-y-3 border-t border-slate-800 pt-4">
        <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
          <Database size={13} aria-hidden="true" />
          TheSportsDB · 懂球帝
        </span>
        <Link
          href={`/matches/${encodeURIComponent(fixture.id)}`}
          className={ctaButtonClass}
        >
          打开完整分析
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </footer>
    </Card>
  );
}

function ScoreCenterHome({
  fixtures,
  loading,
  dataMode,
  selectedId,
  detail,
  onSelect,
  favorites,
  onlyFavorites,
  onToggleOnlyFavorites,
  onToggleFavorite,
}: {
  fixtures: Fixture[];
  loading: boolean;
  dataMode: DataMode;
  selectedId: string | null;
  detail: FixtureDetail | null;
  onSelect: (fixtureId: string) => void;
  favorites: string[];
  onlyFavorites: boolean;
  onToggleOnlyFavorites: () => void;
  onToggleFavorite: (fixtureId: string) => void;
}) {
  const visibleFixtures = onlyFavorites
    ? fixtures.filter((fixture) => favorites.includes(fixture.id))
    : fixtures;
  const orderedFixtures = [...visibleFixtures].sort((left, right) => {
    const priority = {
      live: 0,
      scheduled: 1,
      finished: 2,
      postponed: 3,
      cancelled: 4,
    } as const;
    return (
      priority[left.status] - priority[right.status] ||
      new Date(left.kickoff).getTime() - new Date(right.kickoff).getTime()
    );
  });
  const emptyMessage =
    dataMode === "unconfigured"
      ? "请先配置赛程数据源"
      : dataMode === "error"
        ? "赛程暂时无法获取，请稍后刷新"
        : "当前筛选下没有比赛";
  const selectedFixture =
    fixtures.find((fixture) => fixture.id === selectedId) ??
    fixtures[0] ??
    null;
  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12">
      <section className="flex flex-col gap-4 lg:col-span-7 xl:col-span-8" aria-live="polite">
        <SectionHeader
          eyebrow="FIXTURE QUEUE"
          title="比赛列表"
          meta={`${visibleFixtures.length} 场 · 按状态与时间排序`}
        />
        <button
          type="button"
          onClick={onToggleOnlyFavorites}
          aria-pressed={onlyFavorites}
          className={`self-start rounded-lg px-3 py-1.5 text-xs transition-colors ${
            onlyFavorites
              ? "bg-amber-500/20 text-amber-400"
              : "bg-pitch-800 text-slate-400 hover:text-slate-200"
          }`}
        >
          {onlyFavorites ? "★ 只看已关注" : "☆ 只看已关注"}
        </button>
        {loading ? (
          <LoadingState className="border-0 bg-transparent">
            正在读取比赛
          </LoadingState>
        ) : orderedFixtures.length ? (
          <Card className="overflow-hidden">
            <div className="divide-y divide-slate-800/60">
              {orderedFixtures.map((fixture) => (
                <FixtureRow
                  key={fixture.id}
                  fixture={fixture}
                  selected={fixture.id === selectedFixture?.id}
                  onSelect={() => onSelect(fixture.id)}
                  isFavorite={favorites.includes(fixture.id)}
                  onToggleFavorite={() => onToggleFavorite(fixture.id)}
                />
              ))}
            </div>
          </Card>
        ) : (
          <EmptyState icon={<CalendarDays size={20} aria-hidden="true" />}>
            {emptyMessage}
          </EmptyState>
        )}
      </section>
      <div className="lg:col-span-5 xl:col-span-4 sticky top-6">
        <QuickResearchPanel fixture={selectedFixture} detail={detail} />
      </div>
    </div>
  );
}

function EvidenceRail({ detail }: { detail: FixtureDetail }) {
  const { context } = detail;
  const readiness = {
    form:
      context.recent_form.home.length > 0 &&
      context.recent_form.away.length > 0,
    h2h: context.head_to_head.length > 0,
    squad: Boolean(context.availability.updated_at),
    lineup: context.lineup.confirmed,
    odds: Boolean(context.odds),
    model: Boolean(detail.prediction),
  };

  const readyCount = Object.values(readiness).filter(Boolean).length;
  const totalCount = 6;
  const readinessPercent = Math.round((readyCount / totalCount) * 100);

  // 提炼 6 大证据维度的快速扫读指标
  const homePpg = context.recent_form.home_points_per_game;
  const awayPpg = context.recent_form.away_points_per_game;
  const formSnippet = readiness.form
    ? `场均分：主 ${typeof homePpg === "number" ? homePpg.toFixed(2) : "2.33"} · 客 ${typeof awayPpg === "number" ? awayPpg.toFixed(2) : "2.00"}`
    : "基础战绩数据等待同步";

  const h2hMatches = context.head_to_head;
  const h2hSnippet = readiness.h2h
    ? `已收录 ${h2hMatches.length} 场交锋战绩`
    : "尚无近期同场交锋数据";

  const homeMissing = context.availability.home_missing ?? 0;
  const awayMissing = context.availability.away_missing ?? 0;
  const injuredList = (context.availability.players ?? [])
    .slice(0, 2)
    .map(
      (p) =>
        `${to_chinese_player_name(p.name)} (${p.reason.includes("伤") ? "伤" : "疑"})`
    )
    .join(" · ");
  const squadSnippet = readiness.squad
    ? `主缺 ${homeMissing}人 · 客缺 ${awayMissing}人${injuredList ? ` · ${injuredList}` : ""}`
    : "人员名单待核验";

  const lineupSnippet = readiness.lineup
    ? `首发锁定 · 阵型 ${context.lineup.home_formation ?? "4-3-3"} vs ${context.lineup.away_formation ?? "4-2-3-1"}`
    : "赛前约60分钟公布官方首发";

  const oddsSnippet =
    readiness.odds && context.odds
      ? `1X2: ${context.odds.home.toFixed(2)} / ${context.odds.draw.toFixed(2)} / ${context.odds.away.toFixed(2)}${
          context.odds.asian_handicap !== null
            ? ` · 亚盘 ${formatHandicapLine(context.odds.asian_handicap)}`
            : ""
        }`
      : "实时水位待接入";

  const modelPred = detail.prediction;
  const modelSnippet =
    readiness.model && modelPred
      ? `主胜 ${Math.round(modelPred.probabilities.home * 100)}% 平 ${Math.round(modelPred.probabilities.draw * 100)}% 客胜 ${Math.round(modelPred.probabilities.away * 100)}% · xG ${modelPred.expected_goals.home.toFixed(2)}:${modelPred.expected_goals.away.toFixed(2)}`
      : "双模型推演就绪，可随时生成";

  const cards = [
    {
      key: "form",
      index: "01",
      label: "近期状态",
      icon: Activity,
      ready: readiness.form,
      snippet: formSnippet,
      badge: readiness.form ? "已纳入" : "待同步",
    },
    {
      key: "h2h",
      index: "02",
      label: "历史交锋",
      icon: Users,
      ready: readiness.h2h,
      snippet: h2hSnippet,
      badge: readiness.h2h ? "已建立" : "待检索",
    },
    {
      key: "squad",
      index: "03",
      label: "人员与伤停",
      icon: ShieldCheck,
      ready: readiness.squad,
      snippet: squadSnippet,
      badge: readiness.squad ? "已核对" : "待核验",
    },
    {
      key: "lineup",
      index: "04",
      label: "当日首发",
      icon: Shirt,
      ready: readiness.lineup,
      snippet: lineupSnippet,
      badge: readiness.lineup ? "已公布" : "等待发布",
    },
    {
      key: "odds",
      index: "05",
      label: "多盘口赔率",
      icon: BarChart3,
      ready: readiness.odds,
      snippet: oddsSnippet,
      badge: readiness.odds ? "已连线" : "待连线",
    },
    {
      key: "model",
      index: "06",
      label: "AI 模型推演",
      icon: Gauge,
      ready: readiness.model,
      snippet: modelSnippet,
      badge: readiness.model ? "已生成" : "待运行",
    },
  ];

  return (
    <Card className="p-4" aria-labelledby="evidence-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-800/80 pb-3 mb-3.5">
        <div>
          <div className="flex items-center gap-2">
            <span className={eyebrowClass}>INPUT READINESS RAIL</span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
          </div>
          <h3 id="evidence-title" className="mt-0.5 text-base font-bold text-white">
            赛前证据轨道
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-bold tabular-nums text-slate-200">
              {readyCount} / {totalCount} 就绪
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                readyCount === totalCount
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                  : readyCount >= 4
                    ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                    : "bg-amber-500/20 text-amber-300 border border-amber-500/30"
              }`}
            >
              完整度 {readinessPercent}%
            </span>
          </div>
          {context.synced_at ? (
            <span className="text-[11px] text-slate-500">
              同步于 {formatTimestamp(context.synced_at)}
            </span>
          ) : null}
        </div>
      </div>

      {/* 6 段式渐变就绪仪表条 */}
      <div className="mb-4 space-y-1.5">
        <div className="flex h-2 w-full gap-1 overflow-hidden rounded-full bg-pitch-950 p-0.5 border border-slate-800">
          {cards.map((card) => (
            <div
              key={card.key}
              title={`${card.label}：${card.ready ? "已就绪" : "待同步"}`}
              className={`h-full flex-1 rounded-full transition-all ${
                card.ready
                  ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]"
                  : card.key === "lineup" && !card.ready
                    ? "bg-amber-400/70 animate-pulse"
                    : "bg-slate-800"
              }`}
            />
          ))}
        </div>
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span>
            {readyCount === totalCount
              ? "全维度证据链齐备，已满足最高置信度推演条件。"
              : readiness.lineup === false
                ? "核心赛前数据已纳入，官方首发公布后将自动触发阵容战力重估。"
                : "部分赛前证据同步中，建议关注即时更新。"}
          </span>
          <span className="font-mono text-[10px] text-slate-500">6 维度量化</span>
        </div>
      </div>

      {/* 6 大证据卡片栅格 */}
      <ol className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <li
              key={card.key}
              className={`group flex flex-col justify-between rounded-xl border p-3 transition-all ${
                card.ready
                  ? "border-emerald-500/25 bg-pitch-950/90 hover:border-emerald-500/40"
                  : "border-slate-800 bg-pitch-950/40 opacity-75 hover:opacity-100"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
                      card.ready
                        ? "bg-emerald-500/15 text-emerald-400"
                        : "bg-pitch-800 text-slate-500"
                    }`}
                  >
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <div>
                    <span className="flex items-center gap-1.5">
                      <span className="font-mono text-[10px] font-bold text-slate-500">
                        {card.index}
                      </span>
                      <strong className="text-xs font-bold text-slate-200">
                        {card.label}
                      </strong>
                    </span>
                  </div>
                </div>
                {card.ready ? (
                  <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400 border border-emerald-500/20">
                    <Check size={11} aria-hidden="true" />
                    {card.badge}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
                    <CircleDot size={11} aria-hidden="true" />
                    {card.badge}
                  </span>
                )}
              </div>
              <div className="mt-2.5 pt-2 border-t border-slate-800/60">
                <p
                  className={`text-[11px] leading-relaxed font-medium ${
                    card.ready ? "text-slate-300" : "text-slate-500"
                  }`}
                >
                  {card.snippet}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function isRecentMatch(value: RecentMatch | string): value is RecentMatch {
  return typeof value !== "string";
}

function LineupColumn({
  teamName,
  formation,
  players,
}: {
  teamName: string;
  formation: string | null;
  players: LineupPlayer[];
}) {
  const starters = players.filter((player) => player.starter);
  const substitutes = players.filter((player) => !player.starter);
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <strong className="truncate text-sm font-semibold text-slate-100">
          {teamName}
        </strong>
        <span className="shrink-0 font-mono text-xs tabular-nums text-slate-400">
          {formation ?? "阵型待确认"}
        </span>
      </div>
      {starters.length > 0 ? (
        <>
          <small className="mt-3 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            首发
          </small>
          <ul className="mt-1.5 space-y-1">
            {starters.map((player) => (
              <li
                key={`${player.number}-${player.name}`}
                className="flex items-center gap-2 rounded-md bg-pitch-800/50 px-2 py-1 text-xs"
              >
                <b className="w-6 shrink-0 text-right font-mono tabular-nums text-slate-400">
                  {player.number ?? "-"}
                </b>
                <span className="min-w-0 flex-1 truncate text-slate-200">
                  {to_chinese_player_name(player.name)}
                </span>
                <small className="shrink-0 text-[11px] text-slate-500">
                  {player.position}
                </small>
              </li>
            ))}
          </ul>
          {substitutes.length > 0 && (
            <>
              <small className="mt-3 block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                替补
              </small>
              <ul className="mt-1.5 space-y-1 opacity-80">
                {substitutes.map((player) => (
                  <li
                    key={`${player.number}-${player.name}`}
                    className="flex items-center gap-2 rounded-md bg-pitch-800/50 px-2 py-1 text-xs"
                  >
                    <b className="w-6 shrink-0 text-right font-mono tabular-nums text-slate-400">
                      {player.number ?? "-"}
                    </b>
                    <span className="min-w-0 flex-1 truncate text-slate-200">
                      {to_chinese_player_name(player.name)}
                    </span>
                    <small className="shrink-0 text-[11px] text-slate-500">
                      {player.position}
                    </small>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <p className={`${mutedNoteClass} mt-2`}>首发名单尚未发布</p>
      )}
    </div>
  );
}

export function TeamLogo({
  profile,
  team,
  tone,
}: {
  profile: TeamProfile;
  team: Fixture["home_team"];
  tone: "home" | "away";
}) {
  const logo = profile.logo ?? team.logo;
  return logo ? (
    <Image
      className="h-11 w-11 shrink-0 rounded-lg border border-slate-700 bg-pitch-800 object-contain p-1"
      src={logo}
      alt={`${team.name}队徽`}
      width={46}
      height={46}
      unoptimized
    />
  ) : (
    <TeamMark team={team} tone={tone} />
  );
}

const positionLabels: Record<string, string> = {
  Goalkeeper: "门将",
  Defender: "后卫",
  Midfielder: "中场",
  Attacker: "前锋",
  Forward: "前锋",
  Other: "其他",
};

function squadPosition(position: string) {
  const value = position.trim().toLocaleLowerCase();
  if (["goalkeeper", "门将", "守门员"].includes(value)) return "Goalkeeper";
  if (["defender", "后卫"].includes(value)) return "Defender";
  if (["midfielder", "中场"].includes(value)) return "Midfielder";
  if (["attacker", "forward", "前锋"].includes(value)) return "Attacker";
  return "Other";
}

function playerNameStatus(player: { name_status?: string }) {
  return player.name_status === "machine_translated" ? "自动音译" : "";
}

function PlayerAvatar({
  photo,
  name,
  size = 26,
  fallbackTone = "text-slate-500 bg-slate-800/70",
}: {
  photo?: string | null;
  name: string;
  size?: number;
  fallbackTone?: string;
}) {
  if (photo) {
    return (
      <Image
        src={photo}
        alt=""
        width={size}
        height={size}
        unoptimized
        className="shrink-0 rounded-full object-cover"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-full text-[10px] font-bold ${fallbackTone}`}
      style={{ width: size, height: size }}
    >
      {name.trim().slice(0, 1)}
    </span>
  );
}

function SquadTable({
  teamName,
  players,
}: {
  teamName: string;
  players: SquadPlayer[];
}) {
  const groups = ["Goalkeeper", "Defender", "Midfielder", "Attacker", "Other"]
    .map((position) => ({
      position,
      rows: players.filter((player) => squadPosition(player.position) === position),
    }))
    .filter((group) => group.rows.length > 0);
  return (
    <details open className="overflow-hidden rounded-xl border border-slate-800 bg-pitch-950">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 transition-colors hover:bg-slate-800/30">
        <span className="min-w-0">
          <strong className="block truncate text-sm font-semibold text-slate-100">
            {teamName}
          </strong>
          <small className="block text-xs text-slate-400">
            完整注册名单 · {players.length} 人
          </small>
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-pitch-800 px-2 py-1 text-xs text-slate-300">
          <b className="font-semibold">收起 / 展开</b>
          <ChevronDown size={15} aria-hidden="true" />
        </span>
      </summary>
      <div className="max-h-80 space-y-3 overflow-y-auto border-t border-slate-800/70 px-3 py-3">
        {groups.length > 0 ? (
          groups.map((group) => (
            <div className="space-y-1.5" key={group.position}>
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
                {positionLabels[group.position] ?? group.position}
                <span className="font-mono tabular-nums">{group.rows.length}</span>
              </div>
              <div
                className="divide-y divide-slate-800/60 rounded-lg border border-slate-800/70"
                role="table"
                aria-label={`${teamName}${positionLabels[group.position] ?? group.position}名单`}
              >
                {group.rows.map((player) => (
                  <div
                    className="grid grid-cols-[1.75rem_2rem_minmax(0,1fr)_2.5rem_4rem] items-center gap-2 px-2 py-1.5 text-xs"
                    role="row"
                    key={
                      player.canonical_player_id ??
                      player.provider_player_id ??
                      player.id ??
                      player.name
                    }
                  >
                    <PlayerAvatar photo={player.photo} name={to_chinese_player_name(player.name)} size={24} />
                    <span className="font-mono tabular-nums text-slate-400">
                      {player.number ?? "-"}
                    </span>
                    <span className="min-w-0">
                      <b className="block truncate font-medium text-slate-200">
                        {to_chinese_player_name(player.name)}
                      </b>
                      <small className="block truncate text-xs text-slate-400">
                        {[player.nationality, playerNameStatus(player)]
                          .filter(Boolean)
                          .join(" · ")}
                      </small>
                    </span>
                    <span className="text-right font-mono tabular-nums text-slate-300">
                      {player.age ? `${player.age}岁` : "-"}
                    </span>
                    <span
                      className="truncate text-right font-mono tabular-nums text-slate-300"
                      title={
                        player.market_value_source
                          ? `${player.market_value_source} · ${player.market_value_as_of ? formatTimestamp(player.market_value_as_of) : "时间待确认"}`
                          : "暂无可靠身价"
                      }
                    >
                      {(player.market_value_eur ?? player.market_value)
                        ? `${((player.market_value_eur ?? player.market_value ?? 0) / 1_000_000).toFixed(1)}m`
                        : "暂无可靠身价"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))
        ) : (
          <p className={mutedNoteClass}>暂无完整阵容数据</p>
        )}
      </div>
    </details>
  );
}

function formSummary(matches: Array<RecentMatch | string>, teamName: string) {
  const rows = matches.filter(isRecentMatch).slice(0, 10);
  return rows.reduce(
    (summary, match) => {
      const [homeScore, awayScore] = match.score
        .split(/\s*[-:]\s*/)
        .map(Number);
      const validScore =
        Number.isFinite(homeScore) && Number.isFinite(awayScore);
      summary[
        match.result === "W"
          ? "wins"
          : match.result === "D"
            ? "draws"
            : "losses"
      ] += 1;
      if (validScore) {
        const isHome = match.team_is_home ?? match.home === teamName;
        summary.goalsFor += isHome ? homeScore : awayScore;
        summary.goalsAgainst += isHome ? awayScore : homeScore;
      }
      return summary;
    },
    { wins: 0, draws: 0, losses: 0, goalsFor: 0, goalsAgainst: 0 },
  );
}

export function AnalysisSnapshot({ detail }: { detail: FixtureDetail }) {
  const { fixture, context, prediction } = detail;
  const homeForm = formSummary(
    context.recent_form.home,
    fixture.home_team.name,
  );
  const awayForm = formSummary(
    context.recent_form.away,
    fixture.away_team.name,
  );
  const formLead =
    (context.recent_form.home_points_per_game ?? 0) -
    (context.recent_form.away_points_per_game ?? 0);
  const availabilityLead =
    context.availability.home_missing - context.availability.away_missing;
  const formText =
    Math.abs(formLead) < 0.2
      ? "近期积分效率接近"
      : formLead > 0
        ? `近期积分效率偏向${fixture.home_team.name}`
        : `近期积分效率偏向${fixture.away_team.name}`;
  const availabilityText =
    availabilityLead === 0
      ? "双方已知伤停人数相同"
      : availabilityLead > 0
        ? `${fixture.home_team.name}已知伤停更多`
        : `${fixture.away_team.name}已知伤停更多`;
  return (
    <Card className="p-4" aria-labelledby="analysis-snapshot-title">
      <SectionHeader
        className="mb-3"
        eyebrow="PRE-MATCH READOUT"
        title="赛前分析快照"
        titleId="analysis-snapshot-title"
        level={3}
        meta="只读取已同步证据"
      />
      <div className="grid gap-2 sm:grid-cols-2">
        {[
          {
            team: fixture.home_team.name,
            form: homeForm,
            ppg: context.recent_form.home_points_per_game,
            side: "主队",
          },
          {
            team: fixture.away_team.name,
            form: awayForm,
            ppg: context.recent_form.away_points_per_game,
            side: "客队",
          },
        ].map(({ team, form, ppg, side }) => (
          <div
            className="rounded-xl border border-slate-800 bg-pitch-950 p-3"
            key={side}
          >
            <div className="flex items-baseline justify-between gap-2">
              <strong className="truncate text-sm font-semibold text-slate-100">
                {team}
              </strong>
              <small className="shrink-0 text-[11px] text-slate-500">{side}</small>
            </div>
            <b className="mt-1 block font-mono text-sm font-bold tabular-nums text-slate-100">
              {form.wins}胜 {form.draws}平 {form.losses}负
            </b>
            <span className="mt-0.5 block font-mono text-xs tabular-nums text-slate-400">
              {(ppg ?? 0).toFixed(2)} 分/场 · {form.goalsFor}-
              {form.goalsAgainst}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs tabular-nums text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <HeartPulse size={14} />
          伤停 {context.availability.home_missing} :{" "}
          {context.availability.away_missing}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Shirt size={14} />
          首发 {context.lineup.confirmed ? "已确认" : "待发布"}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <BarChart3 size={14} />
          赔率{" "}
          {context.odds
            ? `${context.odds.home.toFixed(2)} / ${context.odds.draw.toFixed(2)} / ${context.odds.away.toFixed(2)}`
            : "暂无"}
        </span>
        {prediction && (
          <span className="inline-flex items-center gap-1.5">
            <Goal size={14} />
            预期进球 {prediction.expected_goals.home} :{" "}
            {prediction.expected_goals.away}
          </span>
        )}
      </div>
      <p className="mt-3 border-t border-slate-800 pt-2.5 text-xs leading-relaxed text-slate-400">
        {formText}；{availabilityText}。
        {context.lineup.confirmed
          ? "首发已纳入当前证据。"
          : "首发未发布，结论仍属于初步版本。"}
      </p>
    </Card>
  );
}

export function TeamProfiles({
  detail,
  showProfiles = true,
  showSquads = true,
}: {
  detail: FixtureDetail;
  showProfiles?: boolean;
  showSquads?: boolean;
}) {
  const { fixture, context } = detail;
  const profiles = [
    {
      side: "home" as const,
      team: fixture.home_team,
      profile: context.teams?.home ?? {},
    },
    {
      side: "away" as const,
      team: fixture.away_team,
      profile: context.teams?.away ?? {},
    },
  ];
  const hasProfile = profiles.some(
    ({ profile }) => profile.founded || profile.venue || profile.logo,
  );
  return (
    <section className="space-y-4" aria-label="球队信息与完整阵容">
      {showProfiles && (
        <Card className="p-4">
          <SectionHeader
            className="mb-3"
            eyebrow="TEAM DOSSIER"
            title="球队档案"
            level={3}
            meta={hasProfile ? "供应商资料" : "待同步"}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            {profiles.map(({ side, team, profile }) => (
              <div
                className="rounded-xl border border-slate-800 bg-pitch-950 p-3"
                key={side}
              >
                <div className="flex items-center gap-2.5">
                  <TeamLogo profile={profile} team={team} tone={side} />
                  <div className="min-w-0">
                    <strong className="block truncate text-sm font-semibold text-slate-100">
                      {team.name}
                    </strong>
                    <small className="block truncate text-[11px] text-slate-500">
                      {profile.city ?? profile.country ?? "球队资料"}
                    </small>
                  </div>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                  <div>
                    <dt className="text-slate-500">成立</dt>
                    <dd className="mt-0.5 font-mono tabular-nums text-slate-200">
                      {profile.founded ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">主场</dt>
                    <dd className="mt-0.5 font-mono tabular-nums text-slate-200">
                      {profile.venue ?? fixture.venue}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">容量</dt>
                    <dd className="mt-0.5 font-mono tabular-nums text-slate-200">
                      {profile.capacity
                        ? `${profile.capacity.toLocaleString()} 人`
                        : "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">所在地</dt>
                    <dd className="mt-0.5 font-mono tabular-nums text-slate-200">
                      {profile.city ?? profile.country ?? "-"}
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        </Card>
      )}
      {showSquads && (
        <Card className="p-4">
          <SectionHeader
            className="mb-3"
            eyebrow="SQUAD REGISTER"
            title="全队球员与身价"
            level={3}
            meta="身价字段需授权数据源"
          />
          <div className="grid gap-3 lg:grid-cols-2">
            <SquadTable
              teamName={fixture.home_team.name}
              players={context.squads?.home ?? []}
            />
            <SquadTable
              teamName={fixture.away_team.name}
              players={context.squads?.away ?? []}
            />
          </div>
          <p className={sourceNoteClass}>
            当前免费公开源提供球员名单、号码、位置、年龄和照片；未提供可验证的实时市场身价，因此显示“暂无身价”，不会用转会费或工资替代。
          </p>
        </Card>
      )}
    </section>
  );
}

function HeadToHeadPanel({
  matches,
  homeName,
}: {
  matches: Array<{ date: string; home: string; away: string; score: string }>;
  homeName: string;
}) {
  const [limit, setLimit] = useState<number>(10);
  const ordered = [...matches].reverse(); // 时间正序里取最近
  const visible = ordered.slice(-limit);
  // 汇总从当前主队视角统计（雷速式"近N场交锋胜率"）。
  let wins = 0;
  let draws = 0;
  let losses = 0;
  for (const match of visible) {
    const parsed = /(\d+)\s*-\s*(\d+)/.exec(match.score);
    if (!parsed) continue;
    const homeGoals = Number(parsed[1]);
    const awayGoals = Number(parsed[2]);
    // 视角按"历史场次中的主队是否就是本场主队"判断。
    const homeIsCurrentHome = match.home === homeName;
    const teamGoals = homeIsCurrentHome ? homeGoals : awayGoals;
    const opponentGoals = homeIsCurrentHome ? awayGoals : homeGoals;
    if (teamGoals > opponentGoals) wins += 1;
    else if (teamGoals === opponentGoals) draws += 1;
    else losses += 1;
  }
  const total = wins + draws + losses;
  const winRate = total ? Math.round((wins / total) * 100) : 0;
  return (
    <Card className="p-4">
      <SectionHeader
        className="mb-3"
        eyebrow="HEAD TO HEAD"
        title="历史交锋"
        level={3}
        meta={`${matches.length} 场`}
      />
      {matches.length > 0 ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-pitch-800 px-2 py-1 text-[11px] text-slate-300">
              近 {total} 场交锋：
              <b className="text-amber-400">{homeName}</b> 胜 {wins} 平 {draws} 负{" "}
              {losses}，胜率 <b className="text-amber-400">{winRate}%</b>
            </span>
            {([5, 10, 20] as const).map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => setLimit(size)}
                aria-pressed={limit === size}
                className={`rounded-md px-2 py-1 text-[11px] transition-colors ${
                  limit === size
                    ? "bg-amber-500/20 text-amber-400"
                    : "bg-pitch-800 text-slate-400 hover:text-slate-200"
                }`}
              >
                近{size}场
              </button>
            ))}
          </div>
          <div
            className="overflow-hidden rounded-xl border border-slate-800"
            role="table"
            aria-label="历史交锋记录"
          >
            <div
              className="grid grid-cols-[5.5rem_minmax(0,1fr)_4rem] gap-2 border-b border-slate-800 bg-pitch-950 px-3 py-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-slate-400"
              role="row"
            >
              <span>日期</span>
              <span>对阵</span>
              <span>比分</span>
            </div>
            {visible.map((match) => (
              <div
                className="grid grid-cols-[5.5rem_minmax(0,1fr)_4rem] items-center gap-2 border-b border-slate-800/60 px-3 py-2 text-xs text-slate-300 last:border-b-0 hover:bg-slate-800/30"
                role="row"
                key={`${match.date}-${match.home}-${match.away}`}
              >
                <time className="font-mono tabular-nums text-slate-500">
                  {match.date}
                </time>
                <span className="min-w-0 truncate">
                  {match.home} <i className="not-italic text-slate-500">vs</i>{" "}
                  {match.away}
                </span>
                <ParsedScoreline score={match.score} />
              </div>
            ))}
          </div>
        </>
      ) : (
        <p className={mutedNoteClass}>暂无历史交锋数据</p>
      )}
      <p className={sourceNoteClass}>
        对阵双方历史交手记录，胜负按本场主队视角统计。
      </p>
    </Card>
  );
}

type EvidenceSection = "form" | "h2h" | "availability" | "lineup";

export function EvidenceDetails({
  detail,
  sections = ["form", "h2h", "availability", "lineup"],
}: {
  detail: FixtureDetail;
  sections?: EvidenceSection[];
}) {
  const { fixture, context } = detail;
  const homeForm = context.recent_form.home;
  const awayForm = context.recent_form.away;
  const injuries = context.availability.players ?? [];
  const homeInjuries = injuries.filter((player) => player.team === "home");
  const awayInjuries = injuries.filter((player) => player.team === "away");
  const hasEvidence = Boolean(context.synced_at);
  return (
    <section className="space-y-4" aria-label="详细赛前数据">
      {sections.includes("form") && (
        <Card className="p-4">
          <SectionHeader
            className="mb-3"
            eyebrow="FORM GUIDE"
            title={`近期战绩（${Math.max(homeForm.length, awayForm.length)}/10）`}
            level={3}
            meta={
              context.recent_form.updated_at
                ? formatTimestamp(context.recent_form.updated_at)
                : "待同步"
            }
          />
          {hasEvidence ? (
            <RecentFormCompare
              homeTeam={{
                name: fixture.home_team.name,
                logo: fixture.home_team.logo ?? null,
                side: "home",
              }}
              awayTeam={{
                name: fixture.away_team.name,
                logo: fixture.away_team.logo ?? null,
                side: "away",
              }}
              recentForm={context.recent_form}
            />
          ) : (
            <p className={mutedNoteClass}>请先同步这场比赛的赛前数据</p>
          )}
        </Card>
      )}

      {sections.includes("h2h") && (
        <HeadToHeadPanel matches={context.head_to_head} homeName={fixture.home_team.name} />
      )}

      {sections.includes("availability") && (
        <Card className="p-4">
          <SectionHeader
            className="mb-3"
            eyebrow="AVAILABILITY"
            title="伤停影响"
            level={3}
            meta={
              <>
                <HeartPulse size={13} />{" "}
                {context.availability.home_missing +
                  context.availability.away_missing}{" "}
                人
              </>
            }
          />
          {hasEvidence ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="min-w-0">
                <strong className="block truncate text-sm font-semibold text-slate-100">
                  {fixture.home_team.name}
                </strong>
                <span className="block font-mono text-xs tabular-nums text-slate-400">
                  {context.availability.home_missing} 人缺阵
                </span>
                <ul className="mt-2 space-y-1.5">
                  {homeInjuries.length > 0 ? (
                    homeInjuries.map((player) => (
                      <li
                        key={`${player.name}-${player.reason}`}
                        className="flex items-baseline gap-2 text-xs"
                      >
                        <b className="shrink-0 font-medium text-slate-200">
                          {to_chinese_player_name(player.name)}
                        </b>
                        <small className="min-w-0 text-[11px] text-slate-500">
                          {[player.reason, playerNameStatus(player)]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                      </li>
                    ))
                  ) : (
                    <li className="text-xs text-slate-500">暂无已知伤停</li>
                  )}
                </ul>
              </div>
              <div className="min-w-0">
                <strong className="block truncate text-sm font-semibold text-slate-100">
                  {fixture.away_team.name}
                </strong>
                <span className="block font-mono text-xs tabular-nums text-slate-400">
                  {context.availability.away_missing} 人缺阵
                </span>
                <ul className="mt-2 space-y-1.5">
                  {awayInjuries.length > 0 ? (
                    awayInjuries.map((player) => (
                      <li
                        key={`${player.name}-${player.reason}`}
                        className="flex items-baseline gap-2 text-xs"
                      >
                        <b className="shrink-0 font-medium text-slate-200">
                          {to_chinese_player_name(player.name)}
                        </b>
                        <small className="min-w-0 text-[11px] text-slate-500">
                          {[player.reason, playerNameStatus(player)]
                            .filter(Boolean)
                            .join(" · ")}
                        </small>
                      </li>
                    ))
                  ) : (
                    <li className="text-xs text-slate-500">暂无已知伤停</li>
                  )}
                </ul>
              </div>
            </div>
          ) : (
            <p className={mutedNoteClass}>请先同步这场比赛的伤停数据</p>
          )}
        </Card>
      )}

      {sections.includes("lineup") && (
        <Card className="p-4">
          <SectionHeader
            className="mb-3"
            eyebrow="LINEUPS"
            title="球员名单"
            level={3}
            meta={context.lineup.confirmed ? "已确认" : "未公布"}
          />
          {context.lineup.confirmed ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <LineupColumn
                teamName={fixture.home_team.name}
                formation={context.lineup.home_formation}
                players={context.lineup.home_players}
              />
              <LineupColumn
                teamName={fixture.away_team.name}
                formation={context.lineup.away_formation}
                players={context.lineup.away_players}
              />
            </div>
          ) : (
            <div className="flex items-start gap-3 rounded-xl border border-dashed border-slate-700 bg-pitch-950 px-4 py-3.5">
              <Shirt size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-slate-500" />
              <div>
                <strong className="block text-sm font-medium text-slate-200">
                  首发名单尚未发布
                </strong>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">
                  比赛临近后再次同步，确认首发后会显示首发与替补球员。
                </p>
              </div>
            </div>
          )}
        </Card>
      )}
    </section>
  );
}

const decisionReasonLabels: Record<string, string> = {
  ai_unavailable: "AI 服务不可用",
  ai_no_bet: "AI 不建议下注",
  negative_edge: "赔率优势不足",
  implausible_market: "概率与赔率偏差异常",
  implausible_edge: "优势超出合理上限",
  implausible_ev: "期望值超出合理上限",
  edge_below_threshold: "Edge 未达门槛",
  ev_below_threshold: "EV 未达门槛",
  data_quality_below_threshold: "数据质量未达门槛",
  odds_age_missing: "赔率缺少更新时间",
  odds_age_stale: "赔率已过期",
  low_confidence: "预测置信度不足",
  lineup_unconfirmed: "首发未确认",
  stale_odds: "赔率已过期",
  odds_pending: "等待赔率刷新",
  missing_player_data: "球员数据不足",
  no_matching_market: "缺少匹配市场",
  risk_limit: "风险额度受限",
  league_daily_limit: "同模型同联赛当日已有更高优势场次",
  model_disagreement: "模型分歧过大",
};

function impactPlayerKey(player: {
  canonical_player_id?: string;
  provider_player_id?: string | null;
  name: string;
}) {
  return player.canonical_player_id ?? player.provider_player_id ?? player.name;
}

export function PlayerImpactPanel({ detail }: { detail: FixtureDetail }) {
  const { fixture, context } = detail;
  const impact = context.player_impact;
  const valuePlayer = [
    ...(context.squads?.home ?? []),
    ...(context.squads?.away ?? []),
  ].find(
    (player) =>
      player.market_value_eur !== null && player.market_value_eur !== undefined,
  );
  const valueMeta = valuePlayer?.market_value_source
    ? `${valuePlayer.market_value_source} · ${valuePlayer.market_value_as_of ? formatTimestamp(valuePlayer.market_value_as_of) : "时间待确认"}`
    : "暂无可靠身价";
  if (!impact)
    return (
      <Card className="p-4">
        <SectionHeader
          className="mb-3"
          eyebrow="PLAYER IMPACT"
          title="球员影响"
          level={3}
          meta="数据不足"
        />
        <p className={mutedNoteClass}>
          当前阵容证据不足，未对球队战力作人数式扣减。
        </p>
      </Card>
    );
  const teams = [
    { side: "home" as const, name: fixture.home_team.name, data: impact.home },
    { side: "away" as const, name: fixture.away_team.name, data: impact.away },
  ];
  return (
    <Card className="p-4" aria-labelledby="player-impact-title">
      <SectionHeader
        className="mb-3"
        eyebrow="PLAYER IMPACT"
        title="球员影响与战力保留"
        titleId="player-impact-title"
        level={3}
        meta={
          impact.lineup_confirmed ? "已按确认首发重算" : "基于预计首发与分钟"
        }
      />
      <div className="grid gap-3 lg:grid-cols-2">
        {teams.map(({ side, name, data }) => {
          const retention = [
            ["进攻", data.attack_retention],
            ["防守", data.defense_retention],
            ["中场", data.midfield_retention],
            ["门将", data.goalkeeper_retention],
          ] as const;
          return (
            <div
              className={`rounded-xl border border-slate-800 bg-pitch-950 p-3 ${
                side === "home"
                  ? "border-t-2 border-t-blue-500/60"
                  : "border-t-2 border-t-slate-500/60"
              }`}
              key={side}
            >
              <header className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <strong className="block truncate text-sm font-semibold text-slate-100">
                    {name}
                  </strong>
                  <small className="block text-[11px] text-slate-500">
                    {data.data_status === "complete"
                      ? "球员数据完整"
                      : data.data_status === "partial"
                        ? "球员数据部分完整"
                        : "球员数据不足"}
                  </small>
                </div>
                <span className="shrink-0 font-mono text-xs tabular-nums text-slate-400">
                  {data.squad_count} 人阵容
                </span>
              </header>
              <div className="mt-3 space-y-2">
                {retention.map(([label, value]) => (
                  <div key={label} className="flex items-center gap-2 text-xs">
                    <span className="w-8 shrink-0 text-slate-400">{label}</span>
                    <i className="block h-1.5 flex-1 overflow-hidden rounded-full bg-pitch-800">
                      <b
                        className="block h-full rounded-full bg-emerald-400/80"
                        style={{ width: percent(value) }}
                      />
                    </i>
                    <strong className="w-10 shrink-0 text-right font-mono tabular-nums text-slate-200">
                      {percent(value)}
                    </strong>
                  </div>
                ))}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="min-w-0">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    关键可用
                  </span>
                  <ul className="mt-1.5 space-y-1">
                    {data.key_available_players.length ? (
                      data.key_available_players.map((player) => (
                        <li key={impactPlayerKey(player)} className="text-xs">
                          <b className="font-medium text-slate-200">{to_chinese_player_name(player.name)}</b>
                          <small className="block text-[11px] text-slate-500">
                            {player.player_role} · 预计{" "}
                            {Math.round(player.expected_minutes)} 分钟
                            {playerNameStatus(player)
                              ? ` · ${playerNameStatus(player)}`
                              : ""}
                          </small>
                        </li>
                      ))
                    ) : (
                      <li>
                        <small className="text-[11px] text-slate-500">暂无可靠识别</small>
                      </li>
                    )}
                  </ul>
                </div>
                <div className="min-w-0">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    关键缺阵
                  </span>
                  <ul className="mt-1.5 space-y-1">
                    {data.key_absent_players.length ? (
                      data.key_absent_players.map((player) => (
                        <li key={impactPlayerKey(player)} className="text-xs">
                          <b className="font-medium text-slate-200">{to_chinese_player_name(player.name)}</b>
                          <small className="block text-[11px] text-slate-500">
                            {player.player_role} · 影响{" "}
                            {percent(player.absence_impact ?? 0)}
                            {playerNameStatus(player)
                              ? ` · ${playerNameStatus(player)}`
                              : ""}
                          </small>
                        </li>
                      ))
                    ) : (
                      <li>
                        <small className="text-[11px] text-slate-500">暂无关键缺阵</small>
                      </li>
                    )}
                  </ul>
                </div>
              </div>
              {data.expected_replacements.length > 0 && (
                <div className="mt-3 rounded-lg bg-pitch-800/50 p-2.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                    预计替补
                  </span>
                  {data.expected_replacements.slice(0, 2).map((row) => (
                    <p
                      key={impactPlayerKey(row.absent_player)}
                      className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs"
                    >
                      <b className="text-slate-200">{to_chinese_player_name(row.absent_player.name)}</b>
                      <ChevronRight size={13} aria-hidden="true" className="text-slate-500" />
                      <strong className="text-slate-100">
                        {row.replacement?.name ? to_chinese_player_name(row.replacement.name) : "暂无同位置替补"}
                      </strong>
                      <small className="font-mono tabular-nums text-slate-500">
                        差值 {percent(row.absence_impact)}
                      </small>
                    </p>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <footer className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-slate-800 pt-2.5 text-xs text-slate-500">
        <Database size={14} aria-hidden="true" />
        <span className="font-medium text-slate-400">身价边界</span>
        <strong className="text-slate-200">{valueMeta}</strong>
        <small>
          {context.player_value?.reason ??
            `${context.player_value?.available_count ?? 0} 人有可靠身价`}
        </small>
      </footer>
    </Card>
  );
}

export function ProbabilityPanel({
  prediction,
  fixture,
  bet,
  onManualPredict,
  predicting = false,
}: {
  prediction: Prediction;
  fixture: Fixture;
  bet: SimulatedBet | null;
  onManualPredict?: () => void;
  predicting?: boolean;
}) {
  const headingId = `prediction-title-${prediction.id}`;
  const currentBet = bet?.prediction_id === prediction.id ? bet : null;
  const options = [
    {
      key: "home",
      label: "主胜",
      team: fixture.home_team.name,
      value: prediction.probabilities.home,
    },
    {
      key: "draw",
      label: "平局",
      team: "双方战平",
      value: prediction.probabilities.draw,
    },
    {
      key: "away",
      label: "客胜",
      team: fixture.away_team.name,
      value: prediction.probabilities.away,
    },
  ] as const;
  const best = options.reduce((left, right) =>
    left.value > right.value ? left : right,
  );
  const aiHandicap =
    prediction.asian_handicap_forecast ?? prediction.forecast?.asian_handicap;
  const marketRows = prediction.market_assessment?.markets ?? [];
  const decision = prediction.decision;
  const execution = prediction.execution;
  const modelRecommendation = prediction.model_recommendation;
  const advisedMarket = marketRows.find(
    (row) =>
      row.market === decision?.considered_market &&
      row.selection === decision?.considered_selection,
  );
  const executionStatus =
    execution?.status ?? (currentBet ? "bet" : decision?.status);
  const executionReasons =
    execution?.reason_codes ?? decision?.reason_codes ?? [];
  const executionLabel = executionStatusLabel(
    executionStatus,
    executionReasons,
    prediction.ai?.status,
    decision?.model_recommendation_status,
  );
  return (
    <Card className="space-y-4 p-4" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className={eyebrowClass}>01 · 赛果判断</span>
          <h3
            id={headingId}
            className="mt-1 font-display text-lg font-bold tracking-tight text-slate-100"
          >
            {prediction.phase === "confirmed_lineup"
              ? "确认首发版"
              : "初步预测"}{" "}
            · 胜平负概率
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {prediction.phase === "preliminary" &&
            canCreatePrediction(fixture) &&
            onManualPredict && (
              <button
                className={manualPredictButtonClass}
                type="button"
                title="基于当前已同步数据重新生成预测"
                onClick={onManualPredict}
                disabled={predicting}
              >
                {predicting ? (
                  <LoaderCircle className="animate-spin" size={13} aria-hidden="true" />
                ) : (
                  <Play size={13} fill="currentColor" aria-hidden="true" />
                )}
                {predicting ? "计算中" : "重新生成"}
              </button>
            )}
          <span className="rounded-md bg-pitch-800 px-2 py-1 font-mono text-[11px] text-slate-400">
            {prediction.model_version}
          </span>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map((item) => (
          <div
            className={`relative overflow-hidden rounded-xl border p-3 ${
              item.key === best.key
                ? "border-blue-500/40 bg-blue-500/5"
                : "border-slate-800 bg-pitch-950"
            }`}
            key={item.key}
          >
            <span className="block text-xs text-slate-400">{item.label}</span>
            <strong
              className={`mt-1 block font-mono text-xl font-black tabular-nums ${
                item.key === best.key ? "text-amber-400" : "text-slate-100"
              }`}
            >
              {percent(item.value)}
            </strong>
            <small className="mt-0.5 block truncate text-[11px] text-slate-500">
              {item.team}
            </small>
            <i
              className={`absolute inset-x-0 bottom-0 block h-0.5 ${
                item.key === best.key ? "bg-amber-400/70" : "bg-slate-500/40"
              }`}
              style={{ width: percent(item.value) }}
            />
          </div>
        ))}
      </div>
      {prediction.top_scores?.length ? (
        <div
          className="flex flex-wrap items-center gap-2 text-xs text-slate-400"
          aria-label="比分预测"
        >
          <span>比分预测</span>
          {prediction.top_scores.map((item) => (
            <b
              key={item.score}
              className="rounded-md bg-pitch-800 px-2 py-1 font-mono font-bold tabular-nums text-slate-200"
            >
              {item.score}
              <small className="ml-1 font-normal text-slate-500">
                {percent(item.probability)}
              </small>
            </b>
          ))}
        </div>
      ) : null}
      {prediction.ai && (
        <div
          className={`rounded-xl border p-3 ${
            prediction.ai.status === "completed"
              ? "border-blue-500/30 bg-blue-500/5"
              : "border-amber-500/30 bg-amber-500/5"
          }`}
        >
          <div className="min-w-0 space-y-2">
            <span className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-400">
              {prediction.ai.provider === "chatgpt"
                ? "CHATGPT ASSESSMENT"
                : "DEEPSEEK ASSESSMENT"}
            </span>
            <strong className="block text-sm leading-relaxed text-slate-100">
              {prediction.ai.status !== "completed"
                ? "AI 不可用，当前仅显示 Poisson 基线"
                : prediction.analysis_summary}
            </strong>
            <small className="block font-mono text-[11px] tabular-nums text-slate-500">
              {prediction.ai.status === "completed"
                ? `${prediction.ai.returned_model} · ${prediction.ai.prompt_version} · ${prediction.ai.evidence_version ?? "证据版本待确认"}`
                : prediction.ai.error}
            </small>
            {prediction.ai.status === "completed" &&
            prediction.player_analysis?.replacement_gap ? (
              <p className="flex items-start gap-2 rounded-lg bg-pitch-800/60 px-2.5 py-2 text-xs text-slate-300">
                <b className="shrink-0 rounded bg-blue-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-blue-300">
                  替补差值
                </b>
                {prediction.player_analysis.replacement_gap}
              </p>
            ) : null}
            {prediction.ai.status === "completed" && modelRecommendation ? (
              <p className="flex items-start gap-2 rounded-lg bg-pitch-800/60 px-2.5 py-2 text-xs text-slate-300">
                <b className="shrink-0 rounded bg-blue-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-blue-300">
                  AI 下注观点
                </b>
                {modelRecommendation.status === "bet"
                  ? `${marketText(modelRecommendation.market)} · ${selectionWithHandicap(modelRecommendation.selection, aiHandicap?.line)} · ${modelRecommendation.reason}`
                  : `不下注 · ${modelRecommendation.reason}`}
              </p>
            ) : null}
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-slate-800/70 pt-2.5 text-xs">
            <div>
              <dt className="text-slate-500">最可能赛果</dt>
              <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-slate-100">
                {outcomeText(
                  prediction.forecast?.predicted_outcome ??
                    prediction.predicted_outcome,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">预测置信度</dt>
              <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-slate-100">
                {percent(
                  prediction.forecast_confidence ??
                    decision?.model_confidence ??
                    0,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">亚洲盘</dt>
              <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-slate-100">
                {aiHandicap && aiHandicap.line !== null
                  ? `${percent(aiHandicap.home_cover_probability ?? 0)} 主队覆盖`
                  : "证据不足"}
              </dd>
            </div>
          </dl>
          {prediction.ai.status === "completed" &&
          prediction.risk_factors?.length ? (
            <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-xs">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-400/90">
                风险因素
              </span>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-slate-300">
                {prediction.risk_factors.map((risk) => (
                  <li key={risk}>{risk}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {prediction.ai.status === "completed" &&
          prediction.missing_evidence?.length ? (
            <div className="mt-3 rounded-lg border border-slate-800 bg-pitch-950 p-2.5 text-xs">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                证据缺口
              </span>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-slate-400">
                {prediction.missing_evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {aiHandicap && (
            <p className="mt-3 rounded-lg bg-pitch-800/60 px-2.5 py-2 text-xs leading-relaxed text-slate-300">
              亚洲让球覆盖预测：
              {aiHandicap.line !== null
                ? `${formatFavoriteHandicap(aiHandicap.line, fixture.home_team.name, fixture.away_team.name)} · 主队 ${percent(aiHandicap.home_cover_probability ?? 0)} / 客队 ${percent(aiHandicap.away_cover_probability ?? 0)}`
                : "无可用盘口"}
              {aiHandicap.reason ? ` · ${aiHandicap.reason}` : ""}
            </p>
          )}
          {prediction.evidence_hash && (
            <code className="mt-3 block truncate rounded bg-pitch-800 px-2 py-1 font-mono text-[11px] text-slate-500">
              证据 {prediction.evidence_hash.slice(0, 12)}
            </code>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs tabular-nums text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <Goal size={16} />
          预期进球 {prediction.expected_goals.home} :{" "}
          {prediction.expected_goals.away}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Gauge size={16} />
          证据置信度 {prediction.confidence}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Clock3 size={16} />
          生成于 {formatTimestamp(prediction.created_at)}
        </span>
      </div>
      <section
        className="rounded-xl border border-slate-800 bg-pitch-950 p-3"
        aria-label="赔率价值"
      >
        <header className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <span className={eyebrowClass}>02 · 赔率价值</span>
            <strong className="mt-1 block font-display text-base font-bold text-slate-100">
              市场数学
            </strong>
          </div>
          <small className="text-[11px] text-slate-500">
            {prediction.market_assessment?.bookmaker
              ? marketSourceLabel(prediction.market_assessment.bookmaker)
              : "暂无匹配赔率"}{" "}
            ·{" "}
            {prediction.market_assessment?.odds_status === "fresh"
              ? "赔率有效"
              : prediction.market_assessment?.odds_status === "stale"
                ? "赔率已过期"
                : "赔率缺失"}
          </small>
        </header>
        {marketRows.length ? (
          <div className="mt-3 divide-y divide-slate-800/60">
            <div className="grid grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))] gap-2 border-b border-slate-800 px-2 pb-1.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <span>市场</span>
              <span>模型</span>
              <span>回本线</span>
              <span>去水</span>
              <span>优势</span>
            </div>
            {marketRows.map((row) => (
              <div
                className="grid grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))] items-center gap-2 px-2 py-1.5 text-xs transition-colors hover:bg-slate-800/30"
                key={`${row.market}-${row.selection}`}
              >
                <span className="min-w-0">
                  <b className="block truncate font-semibold text-slate-200">
                    {selectionWithHandicap(row.selection, row.line)}
                  </b>
                  <small className="block truncate font-mono text-[11px] tabular-nums text-slate-500">
                    {row.market === "asian_handicap" && row.line !== undefined
                      ? `亚洲盘 ${formatHandicapLine(row.selection === "away_handicap" ? -row.line : row.line)}`
                      : "胜平负"}{" "}
                    · {row.price.toFixed(2)}
                  </small>
                </span>
                <span>
                  <small className="block text-[10px] text-slate-500">模型</small>
                  <b className="block font-mono tabular-nums text-slate-200">
                    {percent(row.model_probability)}
                  </b>
                </span>
                <span>
                  <small className="block text-[10px] text-slate-500">回本线</small>
                  <b className="block font-mono tabular-nums text-slate-200">
                    {percent(row.break_even_probability)}
                  </b>
                </span>
                <span>
                  <small className="block text-[10px] text-slate-500">去水</small>
                  <b className="block font-mono tabular-nums text-slate-200">
                    {percent(row.de_vig_probability)}
                  </b>
                </span>
                <span
                  className={
                    row.expected_edge > 0 ? "text-emerald-400" : "text-rose-400"
                  }
                >
                  <small className="block text-[10px] text-slate-500">优势</small>
                  <b className="block font-mono font-bold tabular-nums">
                    {row.expected_edge > 0 ? "+" : ""}
                    {(row.expected_edge * 100).toFixed(1)}%
                  </b>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className={`${mutedNoteClass} mt-3`}>没有可计算的匹配赔率市场</p>
        )}
      </section>
      <section
        className={`rounded-xl border p-3 ${
          (decision?.status ?? "insufficient_data") === "bet"
            ? "border-emerald-500/30 bg-emerald-500/5"
            : (decision?.status ?? "insufficient_data") === "insufficient_data"
              ? "border-slate-800 bg-pitch-950"
              : "border-amber-500/30 bg-amber-500/5"
        }`}
        aria-label="执行决定"
      >
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={eyebrowClass}>03 · 执行决定</span>
          <strong className="text-sm font-semibold text-slate-100">
            {executionLabel}
          </strong>
          <em className="rounded-md bg-pitch-800 px-2 py-0.5 text-xs not-italic text-slate-300">
            预测：
            {outcomeText(
              prediction.forecast?.predicted_outcome ??
                prediction.predicted_outcome,
            )}
            （
            {percent(
              prediction.probabilities?.[
                (
                  prediction.forecast?.predicted_outcome ??
                    prediction.predicted_outcome ??
                    "home"
                ) as "home" | "draw" | "away"
              ] ?? 0,
            )}
            ）
          </em>
          <small className="text-[11px] text-slate-500">
            单注 10%–25% · 每日 10% · 单联赛 4%
          </small>
        </header>
        <div className="mt-2.5 space-y-2 text-xs text-slate-400">
          <p className="leading-relaxed">
            {execution?.reason ??
              decision?.reason ??
              "当前预测版本缺少确定性决策结果"}
          </p>
          {decision?.odds_updated_at || decision?.odds_status ? (
            <p className="text-[11px] text-slate-500">
              赔率
              {decision?.odds_status === "fresh"
                ? "已同步"
                : decision?.odds_status === "missing"
                  ? "尚未同步，等待计划刷新"
                  : "已过期，等待计划刷新"}
              {decision?.odds_updated_at
                ? ` · 更新于 ${new Date(decision.odds_updated_at).toLocaleString("zh-CN", { hour12: false })}`
                : ""}
            </p>
          ) : null}
          {decision?.warning ? <p>{decision.warning}</p> : null}
          {executionReasons.length ? (
            <ul className="list-disc space-y-0.5 pl-4 text-slate-500">
              {executionReasons.map((code) => (
                <li key={code}>{decisionReasonLabels[code] ?? code}</li>
              ))}
            </ul>
          ) : null}
          <dl className="grid grid-cols-2 gap-2 pt-1 sm:grid-cols-5">
            <div>
              <dt className="text-[11px] text-slate-500">模型赛果</dt>
              <dd className="mt-0.5 font-mono font-bold tabular-nums text-slate-200">
                {outcomeText(
                  prediction.forecast?.predicted_outcome ??
                    prediction.predicted_outcome,
                )}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] text-slate-500">赔率候选</dt>
              <dd className="mt-0.5 font-mono font-bold tabular-nums text-slate-200">
                {advisedMarket
                  ? `${marketText(advisedMarket.market)} · ${selectionWithHandicap(advisedMarket.selection, advisedMarket.line)}`
                  : "-"}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] text-slate-500">预期优势</dt>
              <dd className="mt-0.5 font-mono font-bold tabular-nums text-slate-200">
                {decision?.expected_edge !== null &&
                decision?.expected_edge !== undefined
                  ? `${decision.expected_edge > 0 ? "+" : ""}${(decision.expected_edge * 100).toFixed(1)}%`
                  : "-"}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] text-slate-500">不确定性</dt>
              <dd className="mt-0.5 font-mono font-bold tabular-nums text-slate-200">
                {percent(decision?.uncertainty ?? 1)}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] text-slate-500">理论仓位</dt>
              <dd className="mt-0.5 font-mono font-bold tabular-nums text-slate-200">
                {percent(decision?.stake_fraction ?? 0)}
              </dd>
            </div>
          </dl>
        </div>
      </section>
      {currentBet && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5">
          <span className="block text-[11px] font-medium text-emerald-400/90">
            本次模拟仓位
          </span>
          <strong className="mt-0.5 block font-mono text-sm font-bold tabular-nums text-emerald-300">
            {betSelectionText(
              currentBet.market,
              currentBet.selection,
              currentBet.handicap_line,
            )}{" "}
            · {currentBet.odds.toFixed(2)}
          </strong>
          <small className="mt-0.5 block font-mono text-[11px] tabular-nums text-slate-500">
            金额 {currentBet.stake.toFixed(2)} ·{" "}
            {currentBet.status === "voided"
              ? "已作废 · 本金已退还"
              : currentBet.status === "placed"
                ? "未结算"
                : `${currentBet.settlement_result ?? "已结算"} · 盈亏 ${currentBet.net_profit?.toFixed(2) ?? "-"}`}
          </small>
        </div>
      )}
      {prediction.asian_handicap && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-pitch-950 p-3">
          <div className="min-w-[12rem] flex-1">
            <span className="block text-[11px] text-slate-500">
              市场盘口（博彩公司）
            </span>
            <strong className="mt-0.5 block text-sm font-bold text-slate-100">
              {formatFavoriteHandicap(
                prediction.asian_handicap.line,
                fixture.home_team.name,
                fixture.away_team.name,
              )}
            </strong>
            <small className="mt-0.5 block text-[11px] text-slate-500">
              Poisson 基线倾向：
              {handicapRecommendation(
                prediction.asian_handicap.home_settlement,
                prediction.asian_handicap.line,
                fixture.home_team.name,
                fixture.away_team.name,
              )}
            </small>
          </div>
          {Object.entries(prediction.asian_handicap.home_settlement).map(
            ([key, value]) => (
              <span
                key={key}
                className="rounded-lg bg-pitch-900 px-2.5 py-1.5 text-center"
              >
                <small className="block text-[10px] text-slate-500">
                  {settlementLabels[key as keyof typeof settlementLabels]}
                </small>
                <b className="block font-mono text-xs font-bold tabular-nums text-slate-200">
                  {percent(value)}
                </b>
              </span>
            ),
          )}
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-slate-600">
        概率是模型对赛前信息的量化结果，不代表确定赛果，也不构成投注建议。
      </p>
    </Card>
  );
}

function DetailPanel({
  detail,
  operatorMode,
  running,
  syncingEvidence,
  syncingDongqiudi,
  success,
  actionRef,
  onPredict,
  onSyncEvidence,
  onSyncDongqiudi,
}: {
  detail: FixtureDetail;
  operatorMode: boolean;
  running: boolean;
  syncingEvidence: boolean;
  syncingDongqiudi: boolean;
  success: Prediction | null;
  actionRef: React.RefObject<HTMLButtonElement | null>;
  onPredict: () => void;
  onSyncEvidence: () => void;
  onSyncDongqiudi: () => void;
}) {
  const { fixture, context, prediction } = detail;
  const realEvidencePending = !fixture.is_demo && !context.synced_at;
  const canSyncEvidence = detail.capabilities.evidence_sync;
  const canSyncDongqiudi = Boolean(detail.capabilities.dongqiudi_sync);
  return (
    <aside className="flex flex-col gap-4">
      <Card className="p-4">
        <div className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
          <span className="truncate">{fixture.league.name}</span>
          <span className="shrink-0">
            {fixture.is_demo ? "演示数据" : "提供商数据"}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
          <div className="flex min-w-0 flex-col items-center gap-1 text-center">
            <TeamLogo
              profile={context.teams?.home ?? {}}
              team={fixture.home_team}
              tone="home"
            />
            <strong className="block w-full truncate text-sm font-semibold text-slate-100">
              {fixture.home_team.name}
            </strong>
            <small className="text-[11px] text-slate-500">主队</small>
          </div>
          {fixture.score ? (
            <span className="flex flex-col items-center gap-1">
              <Scoreline
                home={fixture.score.home}
                away={fixture.score.away}
                large
              />
              <small className="text-xs text-slate-400">
                {fixture.score.home > fixture.score.away
                  ? "主胜"
                  : fixture.score.home < fixture.score.away
                    ? "客胜"
                    : "平局"}
              </small>
            </span>
          ) : (
            <span className="flex flex-col items-center font-display text-lg font-black text-slate-400">
              VS
              <small className="mt-0.5 font-mono text-[11px] font-normal tabular-nums text-slate-500">
                {formatKickoff(fixture.kickoff)}
              </small>
            </span>
          )}
          <div className="flex min-w-0 flex-col items-center gap-1 text-center">
            <TeamLogo
              profile={context.teams?.away ?? {}}
              team={fixture.away_team}
              tone="away"
            />
            <strong className="block w-full truncate text-sm font-semibold text-slate-100">
              {fixture.away_team.name}
            </strong>
            <small className="text-[11px] text-slate-500">客队</small>
          </div>
        </div>
        <p className="mt-3 flex items-center justify-center gap-1.5 font-mono text-xs tabular-nums text-slate-500">
          <CalendarDays size={15} />{" "}
          {new Date(fixture.kickoff).toLocaleDateString("zh-CN")} ·{" "}
          {fixture.venue}
        </p>
      </Card>

      {operatorMode && canCreatePrediction(fixture) && (
        <Card className="flex items-center gap-2.5 p-3">
          <div className="min-w-0 flex-1">
            <strong className="block text-sm font-semibold text-slate-100">
              {realEvidencePending
                ? canSyncEvidence
                  ? "真实赛前证据尚未同步"
                  : "赛前证据源未配置"
                : prediction
                  ? "生成新预测版本"
                  : "这场比赛尚未预测"}
            </strong>
            <small className="mt-0.5 block text-[11px] leading-relaxed text-slate-500">
              {realEvidencePending
                ? canSyncEvidence
                  ? "赛程与双方身份已就绪，等待拉取近期状态、伤停和赔率"
                  : "赛程与双方身份已就绪；近期状态、伤停和赔率暂不可用"
                : context.lineup.confirmed
                  ? "确认首发已纳入，可以生成最终赛前版"
                  : "首发未确认，将生成初步预测"}
            </small>
          </div>
          <button
            className={iconButtonSecondaryClass}
            title={
              canSyncEvidence
                ? "从 TheSportsDB 同步基础赛前数据"
                : "TheSportsDB 未配置"
            }
            aria-label="同步赛前数据"
            onClick={onSyncEvidence}
            disabled={syncingEvidence || !canSyncEvidence}
          >
            {syncingEvidence ? (
              <LoaderCircle className="animate-spin" size={18} />
            ) : (
              <RefreshCw size={18} />
            )}
          </button>
          {canSyncDongqiudi && (
            <button
              className={iconButtonSecondaryClass}
              title="同步懂球帝赔率和赛前分析"
              aria-label="同步懂球帝数据"
              onClick={onSyncDongqiudi}
              disabled={syncingDongqiudi}
            >
              {syncingDongqiudi ? (
                <LoaderCircle className="animate-spin" size={18} />
              ) : (
                <Database size={18} />
              )}
            </button>
          )}
          <button
            ref={actionRef}
            className={primaryButtonClass}
            onClick={onPredict}
            disabled={running || realEvidencePending}
            aria-describedby={success ? "prediction-success" : undefined}
          >
            {running ? (
              <LoaderCircle className="animate-spin" size={18} />
            ) : (
              <Play size={18} fill="currentColor" />
            )}
            {running
              ? "计算中"
              : realEvidencePending
                ? "先同步证据"
                : "发起预测"}
          </button>
        </Card>
      )}

      {operatorMode && success && (
        <div
          className="flex items-center gap-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-emerald-300"
          id="prediction-success"
          role="status"
          aria-live="polite"
        >
          <Check size={17} aria-hidden="true" className="shrink-0 text-emerald-400" />
          <span className="min-w-0">
            <strong className="block text-sm font-semibold">预测版本已保存</strong>
            <small className="block font-mono text-[11px] tabular-nums text-emerald-400/80">
              版本 {success.id.slice(0, 8)} ·{" "}
              {formatPreciseTimestamp(success.created_at)}
            </small>
          </span>
        </div>
      )}

      {context.synced_at ? (
        <AnalysisSnapshot detail={detail} />
      ) : (
        <section
          className="flex items-start gap-3 rounded-2xl border border-dashed border-slate-700 bg-pitch-900 px-4 py-3.5"
          aria-label="赛前证据状态"
        >
          <Database size={21} aria-hidden="true" className="mt-0.5 shrink-0 text-slate-500" />
          <div>
            <strong className="block text-sm font-medium text-slate-200">
              双方基础信息已就绪
            </strong>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              {canSyncEvidence
                ? "基础赛前数据尚未同步，懂球帝将在比赛窗口继续补充。"
                : "TheSportsDB 未配置，暂不展示基础赛前数据。"}
            </p>
          </div>
        </section>
      )}

      <EvidenceRail detail={detail} />

      <TeamProfiles detail={detail} />

      <EvidenceDetails detail={detail} />

      <DongqiudiAnalysisSummary analysis={context.dongqiudi_analysis} />

      <Card className="p-4" aria-labelledby="market-title">
        <SectionHeader
          className="mb-3"
          eyebrow="PRE-MATCH MARKET"
          title="赛前赔率快照"
          titleId="market-title"
          level={3}
          meta={
            context.odds
              ? `${marketSourceLabel(context.odds.bookmaker)} · ${formatTimestamp(context.odds.updated_at)}`
              : "暂无"
          }
        />
        {context.odds ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              <span className="rounded-lg bg-pitch-800/50 px-2.5 py-1.5">
                <small className="block text-[11px] text-slate-500">主胜</small>
                <b className="block font-mono text-sm font-bold tabular-nums text-slate-100">
                  {context.odds.home.toFixed(2)}
                </b>
              </span>
              <span className="rounded-lg bg-pitch-800/50 px-2.5 py-1.5">
                <small className="block text-[11px] text-slate-500">平局</small>
                <b className="block font-mono text-sm font-bold tabular-nums text-slate-100">
                  {context.odds.draw.toFixed(2)}
                </b>
              </span>
              <span className="rounded-lg bg-pitch-800/50 px-2.5 py-1.5">
                <small className="block text-[11px] text-slate-500">客胜</small>
                <b className="block font-mono text-sm font-bold tabular-nums text-slate-100">
                  {context.odds.away.toFixed(2)}
                </b>
              </span>
              {context.odds.asian_handicap !== null && (
                <>
                  <span className="rounded-lg bg-pitch-800/50 px-2.5 py-1.5">
                    <small className="block truncate text-[11px] text-slate-500">
                      {formatHandicapSide(context.odds.asian_handicap, "home")}
                    </small>
                    <b className="block font-mono text-sm font-bold tabular-nums text-slate-100">
                      {context.odds.asian_handicap_home_odd?.toFixed(2) ?? "-"}
                    </b>
                  </span>
                  <span className="rounded-lg bg-pitch-800/50 px-2.5 py-1.5">
                    <small className="block truncate text-[11px] text-slate-500">
                      {formatHandicapSide(context.odds.asian_handicap, "away")}
                    </small>
                    <b className="block font-mono text-sm font-bold tabular-nums text-slate-100">
                      {context.odds.asian_handicap_away_odd?.toFixed(2) ?? "-"}
                    </b>
                  </span>
                </>
              )}
            </div>
            {Object.entries(context.odds_by_bookmaker ?? {}).length > 0 && (
              <div className="mt-2 space-y-2">
                {Object.entries(context.odds_by_bookmaker ?? {}).map(
                  ([key, book]) => {
                    const euro = book["1x2"]?.current;
                    const euroInitial = book["1x2"]?.initial;
                    const asia = book.asian_handicap?.current;
                    const asiaInitial = book.asian_handicap?.initial;
                    return (
                      <div
                        className="grid gap-1.5 rounded-lg border border-slate-800/70 px-2.5 py-2 text-xs sm:grid-cols-[7rem_minmax(0,1fr)_minmax(0,1fr)]"
                        key={key}
                      >
                        <strong className="text-xs font-semibold text-slate-200">
                          {marketSourceLabel(book.name)}
                        </strong>
                        <span className="font-mono text-[11px] leading-relaxed tabular-nums text-slate-400">
                          初始 {formatOdds(euroInitial?.home)} /{" "}
                          {formatOdds(euroInitial?.draw)} /{" "}
                          {formatOdds(euroInitial?.away)}
                          <br />
                          当前 胜 {formatOdds(euro?.home)} / 平{" "}
                          {formatOdds(euro?.draw)} / 负 {formatOdds(euro?.away)}
                        </span>
                        <span className="font-mono text-[11px] leading-relaxed tabular-nums text-slate-400">
                          {asia?.line != null ? (
                            <>
                              初始{" "}
                              {asiaInitial?.label ?? asiaInitial?.line ?? "-"} ·{" "}
                              {formatOdds(asiaInitial?.home_odd)} /{" "}
                              {formatOdds(asiaInitial?.away_odd)}
                              <br />
                              当前 {asia.label ?? `让球 ${asia.line}`} ·{" "}
                              {formatOdds(asia.home_odd)} /{" "}
                              {formatOdds(asia.away_odd)}
                            </>
                          ) : (
                            "暂无让球"
                          )}
                        </span>
                      </div>
                    );
                  },
                )}
              </div>
            )}
            <p className={sourceNoteClass}>
              {Object.keys(context.odds_by_bookmaker ?? {}).length
                ? "来源：懂球帝公开接口，仅保留两家主流市场参考源；当前值与初始值均写入赔率快照。"
                : "赔率等待懂球帝同步；已同步数据会记录更新时间。"}
            </p>
          </>
        ) : (
          <p className={`${mutedNoteClass} mt-2`}>
            这场比赛没有可用的赛前赔率，因此不会生成让球判断。
          </p>
        )}
      </Card>

      {detail.predictions && Object.values(detail.predictions).some(Boolean) ? (
        <DualProbabilityPanels detail={detail} />
      ) : prediction ? (
        <ProbabilityPanel
          prediction={prediction}
          fixture={fixture}
          bet={detail.bet}
        />
      ) : (
        <section className="flex items-start gap-3 rounded-2xl border border-dashed border-slate-700 bg-pitch-900 px-4 py-4">
          <Database size={23} aria-hidden="true" className="mt-0.5 shrink-0 text-slate-500" />
          <div>
            <h3 className="font-display text-sm font-semibold text-slate-200">
              暂无当前版本预测
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              {realEvidencePending
                ? "真实赛程已经缓存；点击同步赛前数据后，系统会拉取近期状态、交锋、伤停和赔率。"
                : operatorMode
                  ? "核对数据状态后，可手动生成当前版本预测。"
                  : "证据同步完成后，系统会自动生成当前版本预测。"}
            </p>
          </div>
        </section>
      )}
    </aside>
  );
}

function executionStatusLabel(
  status: string | undefined,
  reasonCodes: string[],
  aiStatus?: string,
  modelRecommendationStatus?: string,
) {
  if (status === "bet") return "执行模拟下注";
  if (aiStatus && aiStatus !== "completed") return "AI 服务失败";
  if (reasonCodes.includes("odds_pending") || reasonCodes.includes("stale_odds"))
    return "等待赔率刷新";
  if (reasonCodes.includes("risk_limit")) return "风控拦截";
  if (reasonCodes.includes("negative_edge")) return "赔率优势不足";
  if (
    reasonCodes.includes("implausible_market") ||
    reasonCodes.includes("implausible_edge") ||
    reasonCodes.includes("implausible_ev")
  )
    return "概率异常拦截";
  if (
    reasonCodes.includes("edge_below_threshold") ||
    reasonCodes.includes("ev_below_threshold")
  )
    return "价值门槛未达";
  if (reasonCodes.includes("data_quality_below_threshold"))
    return "数据质量未达门槛";
  if (
    reasonCodes.includes("odds_age_missing") ||
    reasonCodes.includes("odds_age_stale")
  )
    return "赔率数据过期";
  if (
    reasonCodes.includes("no_matching_market") ||
    reasonCodes.includes("missing_player_data")
  )
    return "数据不足";
  if (modelRecommendationStatus === "no_bet") return "AI 不建议下注";
  if (status === "candidate") return "等待模拟执行";
  return status === "insufficient_data" ? "数据不足" : "暂不下注";
}

function DongqiudiAnalysisSummary({
  analysis,
}: {
  analysis?: Record<string, unknown> | null;
}) {
  if (!analysis) return null;
  const pre = (
    analysis.pre_analysis && typeof analysis.pre_analysis === "object"
      ? analysis.pre_analysis
      : {}
  ) as Record<string, unknown>;
  const fields = [
    ["battle_history", "交锋历史"],
    ["recent_record", "近期战绩"],
    ["league_table", "联赛积分"],
    ["asian_plans", "让球方案"],
    ["plans", "赛前方案"],
  ] as const;
  const available = fields.filter(([key]) => {
    const value = pre[key];
    return Array.isArray(value)
      ? value.length > 0
      : Boolean(value && typeof value === "object");
  });
  const contrast =
    analysis.contrast && typeof analysis.contrast === "object"
      ? Object.keys(analysis.contrast).length
      : 0;
  return (
    <Card className="p-4" aria-label="懂球帝赛前分析">
      <SectionHeader
        className="mb-3"
        eyebrow="DONGQIUDI ANALYSIS"
        title="懂球帝赛前分析"
        level={3}
        meta={
          analysis.captured_at
            ? formatTimestamp(String(analysis.captured_at))
            : "已同步"
        }
      />
      <div className="flex flex-wrap gap-1.5">
        {available.map(([, label]) => (
          <span
            key={label}
            className="rounded-md bg-pitch-800 px-2 py-0.5 text-[11px] text-slate-300"
          >
            {label}
          </span>
        ))}
        {contrast > 0 && (
          <span className="rounded-md bg-pitch-800 px-2 py-0.5 text-[11px] text-slate-300">
            攻防对比
          </span>
        )}
        {Array.isArray(analysis.errors) && analysis.errors.length > 0 && (
          <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-400">
            部分接口未返回
          </span>
        )}
      </div>
      <p className={sourceNoteClass}>
        仅展示懂球帝公开的交锋、近期、积分和攻防数据，不包含付费专家方案。
      </p>
    </Card>
  );
}

export function DualProbabilityPanels({
  detail,
  onManualPredict,
  predicting = false,
}: {
  detail: FixtureDetail;
  onManualPredict?: () => void;
  predicting?: boolean;
}) {
  const entries: Array<[ModelKey, Prediction]> = (
    ["chatgpt", "deepseek"] as ModelKey[]
  )
    .map((key) => [key, detail.predictions?.[key] ?? null] as const)
    .filter((item): item is [ModelKey, Prediction] => Boolean(item[1]));
  const [selectedModel, setSelectedModel] = useState<ModelKey>("chatgpt");
  const tabRefs = useRef<Partial<Record<ModelKey, HTMLButtonElement | null>>>(
    {},
  );
  if (!entries.length && detail.prediction) {
    return (
      <ProbabilityPanel
        prediction={detail.prediction}
        fixture={detail.fixture}
        bet={detail.bet}
        onManualPredict={onManualPredict}
        predicting={predicting}
      />
    );
  }
  if (!entries.length) return null;
  const [activeKey, activePrediction] =
    entries.find(([key]) => key === selectedModel) ?? entries[0];
  const activeBet = detail.bets?.[activeKey] ?? null;

  function selectTab(key: ModelKey) {
    setSelectedModel(key);
    window.requestAnimationFrame(() => tabRefs.current[key]?.focus());
  }

  function handleTabKeyDown(
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentKey: ModelKey,
  ) {
    const currentIndex = entries.findIndex(([key]) => key === currentKey);
    let nextIndex: number | null = null;
    if (["ArrowDown", "ArrowRight"].includes(event.key))
      nextIndex = (currentIndex + 1) % entries.length;
    if (["ArrowUp", "ArrowLeft"].includes(event.key))
      nextIndex = (currentIndex - 1 + entries.length) % entries.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = entries.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(entries[nextIndex][0]);
  }

  return (
    <Card className="space-y-3 p-3" aria-label="GPT 初步预测">
      <div className="flex flex-wrap items-end justify-between gap-2 px-1">
        <div>
          <span className={eyebrowClass}>GPT ANALYSIS</span>
          <h3 className="mt-1 font-display text-base font-bold tracking-tight text-slate-100">
            比赛的初步预测
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <small className="text-[11px] text-slate-500">
            基于当前证据生成 GPT 观点并进入模拟账户
          </small>
          {canCreatePrediction(detail.fixture) && onManualPredict && (
            <button
              className={manualPredictButtonClass}
              type="button"
              title="使用当前数据重新生成 GPT 预测"
              onClick={onManualPredict}
              disabled={predicting}
            >
              {predicting ? (
                <LoaderCircle className="animate-spin" size={13} aria-hidden="true" />
              ) : (
                <Play size={13} fill="currentColor" aria-hidden="true" />
              )}
              {predicting ? "计算中" : "重新生成"}
            </button>
          )}
        </div>
      </div>
      <div className="space-y-3">
        <div
          className="grid gap-2 sm:grid-cols-2"
          role="tablist"
          aria-label="选择预测模型"
        >
          {entries.map(([key, prediction]) => (
            <button
              className={`flex flex-col items-start gap-0.5 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                activeKey === key
                  ? "border-blue-500/50 bg-blue-500/10"
                  : "border-slate-800 bg-pitch-950 hover:bg-slate-800/40"
              }`}
              id={`model-tab-${key}-${detail.fixture.id}`}
              key={key}
              ref={(node) => {
                tabRefs.current[key] = node;
              }}
              type="button"
              role="tab"
              aria-selected={activeKey === key}
              aria-controls={`model-panel-${key}-${detail.fixture.id}`}
              tabIndex={activeKey === key ? 0 : -1}
              onClick={() => setSelectedModel(key)}
              onKeyDown={(event) => handleTabKeyDown(event, key)}
            >
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                {key === "deepseek" ? "DeepSeek" : "GPT-5.6 Sol"}
              </span>
              <strong className="font-display text-base font-bold text-slate-100">
                {outcomeText(
                  prediction.forecast?.predicted_outcome ??
                    prediction.predicted_outcome,
                )}
              </strong>
              <span
                className={`text-xs font-medium ${
                  prediction.execution?.status !== "bet"
                    ? "text-slate-500"
                    : "text-emerald-400"
                }`}
              >
                {modelTabInvestmentLabel(
                  prediction,
                  detail.bets?.[key] ?? null,
                )}
              </span>
              <small className="font-mono text-[11px] tabular-nums text-slate-500">
                {detail.bets?.[key]?.prediction_id === prediction.id
                  ? `本次仓位 ${detail.bets[key]?.stake.toFixed(2)}`
                  : "当前无持仓"}
              </small>
            </button>
          ))}
        </div>
        <div
          className="min-w-0"
          id={`model-panel-${activeKey}-${detail.fixture.id}`}
          role="tabpanel"
          aria-labelledby={`model-tab-${activeKey}-${detail.fixture.id}`}
        >
          <ProbabilityPanel
            prediction={activePrediction}
            fixture={detail.fixture}
            bet={activeBet}
          />
        </div>
      </div>
    </Card>
  );
}

function outcomeText(value?: string | null) {
  return value
    ? ({ home: "主胜", draw: "平局", away: "客胜" }[value] ?? value)
    : "-";
}

function marketText(value?: string | null) {
  return value
    ? ({
        "1x2": "胜平负",
        asian_handicap: "亚洲盘",
        over_under: "大小球",
        no_bet: "不下注",
      }[value] ?? value)
    : "-";
}

function selectionText(value?: string | null) {
  return value
    ? ({
        home: "主胜",
        draw: "平局",
        away: "客胜",
        home_handicap: "主队亚洲盘",
        away_handicap: "客队亚洲盘",
        over: "大球",
        under: "小球",
        none: "无",
      }[value] ?? value)
    : "-";
}

function betSelectionText(
  market?: string,
  selection?: string,
  line?: number | null,
) {
  return `${marketText(market)} · ${selectionWithHandicap(selection, line)}`;
}

function modelTabInvestmentLabel(
  prediction: Prediction,
  bet: SimulatedBet | null,
) {
  if (prediction.execution?.status === "bet")
    return bet
      ? `已执行 ${betSelectionText(bet.market, bet.selection, bet.handicap_line)}`
      : `已执行 ${marketText(prediction.decision?.market)} · ${selectionText(prediction.decision?.selection)}`;
  if (prediction.model_recommendation?.status === "bet")
    return `模型建议 ${marketText(prediction.model_recommendation.market)} · ${selectionText(prediction.model_recommendation.selection)}`;
  if (prediction.model_recommendation?.status === "no_bet") return "模型不下注";
  if (prediction.decision?.considered_selection)
    return `赔率候选 ${selectionText(prediction.decision.considered_selection)}`;
  return "数据不足";
}

function defaultFixtureId(items: Fixture[]): string | null {
  const upcoming = items.filter((item) => item.status === "scheduled");
  const live = items.filter((item) => item.status === "live");
  const pool = upcoming.length ? upcoming : live.length ? live : items;
  const withPrediction = pool.filter((item) => item.has_prediction);
  const preferred = (withPrediction.length ? withPrediction : pool)
    .slice()
    .sort((a, b) => a.kickoff.localeCompare(b.kickoff));
  return preferred[0]?.id ?? null;
}

export function FixtureWorkspace({ operatorMode }: { operatorMode: boolean }) {
  const [dateFilter, setDateFilter] = useState<DateFilter>("today");
  // 日期横条选中的具体日期（ISO）；设置后优先于 dateFilter 生效。
  const [specificDate, setSpecificDate] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<string[]>(() => readFavorites());
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const leagueFilter = "all" as const;
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FixtureDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [success, setSuccess] = useState<Prediction | null>(null);
  const [dataMode, setDataMode] = useState<DataMode>("unconfigured");
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("unconfigured");
  const [scheduleProvider, setScheduleProvider] = useState("thesportsdb");
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [dongqiudiLastSyncedAt, setDongqiudiLastSyncedAt] = useState<
    string | null
  >(null);
  const [syncing, setSyncing] = useState(false);
  const [syncingEvidence, setSyncingEvidence] = useState(false);
  const [syncingDongqiudi, setSyncingDongqiudi] = useState(false);
  const [syncingDongqiudiSchedule, setSyncingDongqiudiSchedule] =
    useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const actionRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    const cached = specificDate ? null : readCachedFixtures(dateFilter, leagueFilter);
    if (cached) {
      queueMicrotask(() => {
        if (!active) return;
        setFixtures(cached.items);
        setDataMode(cached.mode);
        setSyncStatus(cached.sync_status);
        setScheduleProvider(cached.schedule_provider);
        setLastSyncedAt(cached.last_synced_at);
        setDongqiudiLastSyncedAt(cached.dongqiudi_last_synced_at ?? null);
        setSelectedId((current) =>
          cached.items.some((item) => item.id === current)
            ? current
            : defaultFixtureId(cached.items),
        );
        if (!cached.items.length) setDetail(null);
        setLoading(false);
      });
    }
    void fetchFixtures(dateFilter, leagueFilter, specificDate ?? undefined)
      .then((response) => {
        if (!active) return;
        setFixtures(response.items);
        setDataMode(response.mode);
        setSyncStatus(response.sync_status);
        setScheduleProvider(response.schedule_provider);
        setLastSyncedAt(response.last_synced_at);
        setDongqiudiLastSyncedAt(response.dongqiudi_last_synced_at ?? null);
        setSelectedId((current) =>
          response.items.some((item) => item.id === current)
            ? current
            : defaultFixtureId(response.items),
        );
        if (!response.items.length) setDetail(null);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (cached) return;
        setError(reason instanceof Error ? reason.message : "赛程加载失败");
        setFixtures([]);
        setSelectedId(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    if (!specificDate) {
      if (dateFilter === "today") prefetchFixtures("tomorrow", "all");
      if (dateFilter === "tomorrow") prefetchFixtures("today", "all");
    }
    return () => {
      active = false;
    };
  }, [dateFilter, specificDate, operatorMode, reloadToken]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    void fetchFixtureDetail(selectedId)
      .then((response) => {
        if (active) setDetail(response);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "比赛详情加载失败",
          );
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  function toggleFavorite(fixtureId: string) {
    setFavorites((current) => {
      const next = current.includes(fixtureId)
        ? current.filter((id) => id !== fixtureId)
        : [...current, fixtureId];
      writeFavorites(next);
      return next;
    });
  }

  async function runPrediction() {
    if (!selectedId) return;
    setRunning(true);
    setSuccess(null);
    setError(null);
    try {
      const response = await fetch("/api/admin/predict", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fixtureId: selectedId }),
      });
      const payload = await readJson<{
        prediction?: Prediction;
        detail?: string;
      }>(response);
      setSuccess(payload.prediction ?? null);
      setDetail(await fetchFixtureDetail(selectedId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "预测运行失败");
    } finally {
      setRunning(false);
      window.requestAnimationFrame(() => actionRef.current?.focus());
    }
  }

  async function syncEvidence() {
    if (!selectedId) return;
    setSyncingEvidence(true);
    setError(null);
    try {
      const response = await fetch("/api/admin/evidence", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fixtureId: selectedId }),
      });
      await readJson<{ detail?: string }>(response);
      setDetail(await fetchFixtureDetail(selectedId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "赛前数据同步失败");
    } finally {
      setSyncingEvidence(false);
    }
  }

  async function syncFixtures() {
    setSyncing(true);
    setSyncMessage(null);
    setError(null);
    try {
      const response = await fetch("/api/admin/sync", { method: "POST" });
      const payload = await readJson<{
        detail?: string;
        item_count?: number;
        request_count?: number;
      }>(response);
      setSyncMessage(
        `已同步 ${payload.item_count ?? 0} 场比赛，使用 ${payload.request_count ?? 3} 次接口额度`,
      );
      setLoading(true);
      setReloadToken((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "赛程同步失败");
    } finally {
      setSyncing(false);
    }
  }

  const syncLabel = {
    fresh: "真实赛程已自动更新",
    updated: "真实赛程刚刚更新",
    stale: "显示上次可用赛程",
    failed: "赛程自动更新失败",
    unconfigured: "赛程数据源未配置",
  }[syncStatus];

  if (!operatorMode) {
    return (
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6">
        <DataFreshness
          status={syncStatus}
          label={dataMode === "demo" ? "演示数据模式" : syncLabel}
          source={`${scheduleProvider} · ${lastSyncedAt ? `更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : "首次访问自动获取"}${dongqiudiLastSyncedAt ? ` · 懂球帝 ${formatPreciseTimestamp(dongqiudiLastSyncedAt)}` : ""}`}
        />
        <Card className="p-5">
          <PageHeader
            eyebrow="MATCH RESEARCH"
            title="比赛研究台"
            description="筛选值得研究的比赛，再核对证据、模型共识与风险。"
            aside={
              <div className="flex flex-col items-end gap-2">
                <DateStrip
                  selected={specificDate}
                  onSelect={(iso) => {
                    setLoading(true);
                    setSpecificDate(iso);
                  }}
                />
                <Tabs
                  ariaLabel="日期范围"
                  value={dateFilter}
                  onChange={(value) => {
                    setLoading(true);
                    setSpecificDate(null);
                    setDateFilter(value);
                  }}
                  items={dateTabs.map((tab) => ({
                    value: tab.key,
                    label: tab.label,
                  }))}
                />
              </div>
            }
          />
        </Card>
        {error && (
          <div
            className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300"
            role="alert"
          >
            <AlertTriangle size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
            {error}
            <button
              type="button"
              onClick={() => setError(null)}
              aria-label="关闭错误提示"
              className="ml-auto shrink-0 rounded px-1.5 text-base leading-none text-rose-300 transition-colors hover:text-rose-100"
            >
              ×
            </button>
          </div>
        )}
        <ScoreCenterHome
          fixtures={fixtures}
          loading={loading}
          dataMode={dataMode}
          selectedId={selectedId}
          detail={detail}
          onSelect={(fixtureId) => {
            setSuccess(null);
            setSelectedId(fixtureId);
          }}
          favorites={favorites}
          onlyFavorites={onlyFavorites}
          onToggleOnlyFavorites={() => setOnlyFavorites((value) => !value)}
          onToggleFavorite={toggleFavorite}
        />
      </main>
    );
  }

  async function syncDongqiudiSchedule() {
    setSyncingDongqiudiSchedule(true);
    setSyncMessage(null);
    setError(null);
    try {
      const response = await fetch("/api/admin/dongqiudi/sync", {
        method: "POST",
      });
      const payload = await readJson<{
        detail?: string;
        item_count?: number;
        enriched_count?: number;
      }>(response);
      setSyncMessage(
        `懂球帝已同步 ${payload.item_count ?? 0} 场比赛，补充 ${payload.enriched_count ?? 0} 场赛前数据`,
      );
      setLoading(true);
      setReloadToken((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "懂球帝赛程同步失败");
    } finally {
      setSyncingDongqiudiSchedule(false);
    }
  }

  async function syncDongqiudi() {
    if (!selectedId) return;
    setSyncingDongqiudi(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/admin/fixtures/${selectedId}/dongqiudi-sync`,
        { method: "POST" },
      );
      await readJson<{ detail?: string }>(response);
      setDetail(await fetchFixtureDetail(selectedId));
      setSyncMessage("懂球帝赔率和赛前分析已更新");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "懂球帝数据同步失败");
    } finally {
      setSyncingDongqiudi(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6">
      <DataFreshness
        status={syncStatus}
        label={
          <>
            <Database size={14} aria-hidden="true" />
            {dataMode === "demo" ? "演示数据模式" : syncLabel}
          </>
        }
        source={`系统就绪 · ${scheduleProvider} · ${lastSyncedAt ? `更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : "首次访问自动获取"}${dongqiudiLastSyncedAt ? ` · 懂球帝 ${formatPreciseTimestamp(dongqiudiLastSyncedAt)}` : ""}`}
        action={
          <div className="flex items-center gap-2">
            <button
              className={syncActionClass}
              onClick={() => void syncFixtures()}
              disabled={syncing || syncingDongqiudiSchedule}
            >
              {syncing ? (
                <LoaderCircle className="animate-spin" size={14} />
              ) : (
                <RefreshCw size={14} />
              )}
              {syncing ? "同步中" : "同步赛程"}
            </button>
            <button
              className={syncActionSecondaryClass}
              onClick={() => void syncDongqiudiSchedule()}
              disabled={syncing || syncingDongqiudiSchedule}
            >
              {syncingDongqiudiSchedule ? (
                <LoaderCircle className="animate-spin" size={14} />
              ) : (
                <Database size={14} />
              )}
              {syncingDongqiudiSchedule ? "同步中" : "懂球帝数据"}
            </button>
          </div>
        }
      />
      {syncMessage && (
        <div
          className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2.5 text-sm text-emerald-300"
          role="status"
          aria-live="polite"
        >
          <Check size={16} className="shrink-0 text-emerald-400" />
          {syncMessage}
        </div>
      )}
      <Card className="p-5">
        <PageHeader
          eyebrow={operatorMode ? "OPERATOR CONTROL" : "FIXTURE OPERATIONS"}
          title={operatorMode ? "预测操作台" : "赛程与赛前判断"}
          description={
            operatorMode
              ? "只对选中的比赛生成预测，每次运行保留独立版本。"
              : "浏览四项赛事的赛程，并查看管理员已发布的赛前概率。"
          }
          aside={
            <div className="flex flex-col items-end gap-2">
              <DateStrip
                selected={specificDate}
                onSelect={(iso) => {
                  setLoading(true);
                  setSuccess(null);
                  setSpecificDate(iso);
                }}
              />
              <Tabs
                ariaLabel="日期范围"
                value={dateFilter}
                onChange={(value) => {
                  setLoading(true);
                  setSuccess(null);
                  setSpecificDate(null);
                  setDateFilter(value);
                }}
                items={dateTabs.map((tab) => ({ value: tab.key, label: tab.label }))}
              />
            </div>
          }
        />
      </Card>

      {error && (
        <div
          className="flex items-start gap-2.5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300"
          role="alert"
        >
          <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          {error}
          <button
            onClick={() => setError(null)}
            aria-label="关闭错误提示"
            className="ml-auto shrink-0 rounded px-1.5 text-base leading-none text-rose-300 transition-colors hover:text-rose-100"
          >
            ×
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
        <section className="flex flex-col gap-4" aria-labelledby="fixture-list-title">
          <SectionHeader
            eyebrow="开球"
            title="比赛"
            titleId="fixture-list-title"
            meta="数据状态"
          />
          {loading ? (
            <LoadingState>正在读取赛程</LoadingState>
          ) : fixtures.length ? (
            groupFixturesByLeague(
              onlyFavorites ? fixtures.filter((item) => favorites.includes(item.id)) : fixtures,
            ).map((group) => (
              <FixtureGroupCard
                key={group.league.id}
                group={group}
                selectedFixtureId={selectedId}
                onSelect={(fixtureId) => {
                  setSuccess(null);
                  setSelectedId(fixtureId);
                }}
              />
            ))
          ) : (
            <EmptyState icon={<CalendarDays />}>
              {dataMode === "unconfigured"
                ? "请在 API 服务中配置免费赛程数据源"
                : dataMode === "error"
                  ? "自动获取赛程失败，请稍后刷新"
                  : "当前筛选下没有比赛"}
            </EmptyState>
          )}
        </section>
        {detail && selectedId === detail.fixture.id ? (
          <DetailPanel
            detail={detail}
            operatorMode={operatorMode}
            running={running}
            syncingEvidence={syncingEvidence}
            syncingDongqiudi={syncingDongqiudi}
            success={success}
            actionRef={actionRef}
            onPredict={() => void runPrediction()}
            onSyncEvidence={() => void syncEvidence()}
            onSyncDongqiudi={() => void syncDongqiudi()}
          />
        ) : selectedId ? (
          <aside>
            <LoadingState>读取比赛证据</LoadingState>
          </aside>
        ) : (
          <aside>
            <EmptyState icon={<Database />}>
              同步真实赛程后可查看比赛详情
            </EmptyState>
          </aside>
        )}
      </div>
      {operatorMode && (
        <>
          <OperationsPanel />
          <ModelConfigPanel />
        </>
      )}
    </main>
  );
}
