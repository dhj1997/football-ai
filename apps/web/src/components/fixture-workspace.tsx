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

import { fetchFixtureDetail, fetchFixtures } from "@/lib/api";
import { formatFavoriteHandicap, formatHandicapLine, formatHandicapSide } from "@/lib/handicap";
import { OperationsPanel } from "@/components/operations-panel";
import { DataFreshness, PageHeader, SectionHeader, Tabs } from "@/components/ui";
import type { DateFilter, Fixture, FixtureDetail, LeagueFilter, LineupPlayer, ModelKey, Prediction, RecentMatch, SimulatedBet, SquadPlayer, TeamProfile } from "@/lib/types";

type DataMode = "cached" | "demo" | "empty" | "error" | "unconfigured";
type SyncStatus = "fresh" | "updated" | "stale" | "failed" | "unconfigured";

const dateTabs: Array<{ key: DateFilter; label: string }> = [
  { key: "today", label: "今日" },
  { key: "tomorrow", label: "明日" },
  { key: "history", label: "历史" },
];

const leagueTabs: Array<{ key: LeagueFilter; label: string }> = [
  { key: "all", label: "全部联赛" },
  { key: "csl", label: "中超" },
  { key: "laliga", label: "西甲" },
  { key: "epl", label: "英超" },
];

const evidenceMeta = [
  { key: "form", label: "近期状态", icon: Activity },
  { key: "h2h", label: "历史交锋", icon: Users },
  { key: "squad", label: "可用阵容", icon: ShieldCheck },
  { key: "lineup", label: "当日首发", icon: Shirt },
  { key: "odds", label: "赛前赔率", icon: BarChart3 },
  { key: "model", label: "模型结果", icon: Gauge },
] as const;

const percent = (value: number) => `${Math.round(value * 100)}%`;
function handicapRecommendation(settlement: NonNullable<Prediction["asian_handicap"]>["home_settlement"], line: number, homeTeam: string, awayTeam: string) {
  const homePositive = settlement.full_win + settlement.half_win;
  const homeNegative = settlement.full_loss + settlement.half_loss;
  const recommendsHome = homePositive >= homeNegative;
  return recommendsHome ? formatHandicapSide(line, "home", homeTeam) : formatHandicapSide(line, "away", awayTeam);
}

function selectionWithHandicap(value: string | undefined, homeLine: number | null | undefined) {
  if (homeLine !== null && homeLine !== undefined && value === "home_handicap") return formatHandicapSide(homeLine, "home");
  if (homeLine !== null && homeLine !== undefined && value === "away_handicap") return formatHandicapSide(homeLine, "away");
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

export function Scoreline({ home, away, large = false }: { home: number | string; away: number | string; large?: boolean }) {
  const homeScore = Number(home);
  const awayScore = Number(away);
  const homeTone = homeScore > awayScore ? "score-winner" : homeScore < awayScore ? "score-loser" : "score-draw";
  const awayTone = awayScore > homeScore ? "score-winner" : awayScore < homeScore ? "score-loser" : "score-draw";
  return <span className={`scoreline${large ? " scoreline-large" : ""}`} aria-label={`${home} 比 ${away}`}><b className={homeTone}>{home}</b><i>:</i><b className={awayTone}>{away}</b></span>;
}

function ParsedScoreline({ score }: { score: string }) {
  const match = score.match(/(\d+)\s*[-:]\s*(\d+)/);
  return match ? <Scoreline home={match[1]} away={match[2]} /> : <strong>{score}</strong>;
}

function TeamMark({ team, tone }: { team: Fixture["home_team"]; tone: "home" | "away" }) {
  if (team.logo) {
    return <Image className={`team-mark team-badge ${tone}`} src={team.logo} alt="" width={28} height={28} unoptimized />;
  }
  return <span className={`team-mark ${tone}`} aria-hidden="true">{team.code.slice(0, 3)}</span>;
}

function FixtureRow({ fixture, selected = false, onSelect, href }: { fixture: Fixture; selected?: boolean; onSelect?: () => void; href?: string }) {
  const [renderedAt] = useState(() => Date.now());
  const kickoffHasPassed = new Date(fixture.kickoff).getTime() <= renderedAt;
  const statusText = {
    scheduled: kickoffHasPassed ? "状态待更新" : fixture.lineup_confirmed ? "首发已确认" : "等待首发",
    finished: "完场",
    postponed: "延期",
    cancelled: "取消",
    live: "进行中",
  }[fixture.status];
  const resultLabel = fixture.score ? fixture.score.home > fixture.score.away ? "主胜" : fixture.score.home < fixture.score.away ? "客胜" : "平局" : null;
  const resultTone = fixture.score ? fixture.score.home > fixture.score.away ? "home-win" : fixture.score.home < fixture.score.away ? "away-win" : "draw" : "pending";
  const content = <>
      <span className="fixture-time">
        <strong>{fixture.status === "finished" ? "完场" : formatKickoff(fixture.kickoff)}</strong>
        <small>{fixture.league.name}</small>
      </span>
      <span className="fixture-teams">
        <span><TeamMark team={fixture.home_team} tone="home" /><b>{fixture.home_team.name}</b></span>
        <span><TeamMark team={fixture.away_team} tone="away" /><b>{fixture.away_team.name}</b></span>
      </span>
      <span className={`fixture-state ${resultTone}`}>
        {fixture.score ? <span className="fixture-score"><Scoreline home={fixture.score.home} away={fixture.score.away} /><small>{resultLabel}</small></span> : <em className={fixture.lineup_confirmed ? "state-ready" : ""}>{statusText}</em>}
        <ChevronRight size={18} aria-hidden="true" />
      </span>
    </>;
  const className = `fixture-row ${selected ? "selected" : ""}`;
  if (href) return <Link className={className} href={href} aria-label={`${fixture.league.name} ${fixture.home_team.name} 对 ${fixture.away_team.name}`}>{content}</Link>;
  return <button className={className} onClick={onSelect} aria-pressed={selected}>{content}</button>;
}

function ScoreCenterSidebar({ fixtures, syncStatus, freshnessLabel, scheduleProvider, lastSyncedAt }: { fixtures: Fixture[]; syncStatus: SyncStatus; freshnessLabel: string; scheduleProvider: string; lastSyncedAt: string | null }) {
  const counts = fixtures.reduce<Record<string, number>>((result, fixture) => {
    result[fixture.league.name] = (result[fixture.league.name] ?? 0) + 1;
    return result;
  }, {});
  return <aside className="score-center-sidebar" aria-label="赛程概览">
    <section>
      <div className="score-center-side-heading"><span>FOOTBALL TODAY</span><h2>赛事概览</h2></div>
      <dl className="score-center-stats"><div><dt>比赛</dt><dd>{fixtures.length}</dd></div><div><dt>联赛</dt><dd>{Object.keys(counts).length}</dd></div><div><dt>进行中</dt><dd>{fixtures.filter((item) => item.status === "live").length}</dd></div><div><dt>首发确认</dt><dd>{fixtures.filter((item) => item.status === "scheduled" && item.lineup_confirmed).length}</dd></div></dl>
    </section>
    <section>
      <div className="score-center-side-heading"><span>COMPETITIONS</span><h2>联赛</h2></div>
      <ul className="competition-list">{Object.entries(counts).map(([league, count]) => <li key={league}><span>{league}</span><b>{count}</b></li>)}</ul>
    </section>
    <section className="score-center-freshness">
      <div className="score-center-side-heading"><span>DATA FRESHNESS</span><h2>数据新鲜度</h2></div>
      <DataFreshness status={syncStatus} label={freshnessLabel} source={`${scheduleProvider} · ${lastSyncedAt ? `更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : "等待首次同步"}`} />
    </section>
    <section className="score-center-note"><ShieldCheck size={18} aria-hidden="true" /><div><strong>赛前数据持续更新</strong><p>临近开球时自动补充近期战绩、交锋、伤停与首发信息。</p></div></section>
  </aside>;
}

function ScoreCenterHome({ fixtures, loading, dataMode, syncStatus, freshnessLabel, scheduleProvider, lastSyncedAt }: { fixtures: Fixture[]; loading: boolean; dataMode: DataMode; syncStatus: SyncStatus; freshnessLabel: string; scheduleProvider: string; lastSyncedAt: string | null }) {
  const groups = fixtures.reduce<Array<{ league: Fixture["league"]; fixtures: Fixture[] }>>((result, fixture) => {
    const current = result.find((group) => group.league.name === fixture.league.name);
    if (current) current.fixtures.push(fixture);
    else result.push({ league: fixture.league, fixtures: [fixture] });
    return result;
  }, []);
  const emptyMessage = dataMode === "unconfigured" ? "请先配置赛程数据源" : dataMode === "error" ? "赛程暂时无法获取，请稍后刷新" : "当前筛选下没有比赛";
  return <div className="score-center-layout">
    <section className="score-center-list" aria-live="polite">
      {loading ? <div className="score-center-loading"><LoaderCircle className="spin" size={20} aria-hidden="true" />正在读取比赛</div> : groups.length ? groups.map((group) => <section className="competition-group" key={group.league.id}>
        <header><span className="competition-mark">{group.league.mark}</span><div><strong>{group.league.name}</strong><small>{group.league.country}</small></div><b>{group.fixtures.length} 场</b></header>
        <div>{group.fixtures.map((fixture) => <FixtureRow key={fixture.id} fixture={fixture} href={`/matches/${encodeURIComponent(fixture.id)}`} />)}</div>
      </section>) : <div className="score-center-loading"><CalendarDays size={20} aria-hidden="true" />{emptyMessage}</div>}
    </section>
    <ScoreCenterSidebar fixtures={fixtures} syncStatus={syncStatus} freshnessLabel={freshnessLabel} scheduleProvider={scheduleProvider} lastSyncedAt={lastSyncedAt} />
  </div>;
}

function EvidenceRail({ detail }: { detail: FixtureDetail }) {
  const context = detail.context;
  const readiness = {
    form: context.recent_form.home.length > 0 && context.recent_form.away.length > 0,
    h2h: context.head_to_head.length > 0,
    squad: Boolean(context.availability.updated_at),
    lineup: context.lineup.confirmed,
    odds: Boolean(context.odds),
    model: Boolean(detail.prediction),
  };
  return (
    <section className="evidence-section" aria-labelledby="evidence-title">
      <SectionHeader className="section-heading" eyebrow="INPUT READINESS" title="赛前证据轨道" titleId="evidence-title" level={3} meta={`${Object.values(readiness).filter(Boolean).length} / 6 就绪`} />
      <ol className="evidence-rail">
        {evidenceMeta.map(({ key, label, icon: Icon }, index) => (
          <li key={key} className={readiness[key] ? "ready" : "waiting"}>
            <span className="rail-index">{String(index + 1).padStart(2, "0")}</span>
            <span className="rail-icon"><Icon size={17} aria-hidden="true" /></span>
            <span className="rail-label"><b>{label}</b><small>{readiness[key] ? "已纳入" : key === "lineup" ? "尚未公布" : "等待运行"}</small></span>
            {readiness[key] ? <Check size={16} aria-label="就绪" /> : <CircleDot size={16} aria-label="等待" />}
          </li>
        ))}
      </ol>
    </section>
  );
}

function isRecentMatch(value: RecentMatch | string): value is RecentMatch {
  return typeof value !== "string";
}

function RecentFormColumn({
  teamName,
  matches,
  pointsPerGame,
}: {
  teamName: string;
  matches: Array<RecentMatch | string>;
  pointsPerGame: number;
}) {
  const rows = matches.filter(isRecentMatch);
  const summary = matches.find((match): match is string => typeof match === "string");
  return (
    <div className="recent-form-column">
      <div className="data-column-heading"><strong>{teamName}</strong><span>{pointsPerGame.toFixed(2)} 分/场</span></div>
      {rows.length > 0 ? (
        <ul className="recent-match-list">
          {rows.slice(0, 5).map((match) => (
            <li key={`${match.date}-${match.home}-${match.away}`}>
              <time>{match.date.slice(5)}</time>
              <span>{match.home} <i>vs</i> {match.away}</span>
              <b className={`result-${match.result.toLowerCase()}`}>{match.result}</b>
              <ParsedScoreline score={match.score} />
            </li>
          ))}
        </ul>
      ) : summary ? (
        <p className="data-empty">供应商只返回近况摘要：{summary}</p>
      ) : (
        <p className="data-empty">暂无可用的近 5 场比赛</p>
      )}
    </div>
  );
}

function LineupColumn({ teamName, formation, players }: { teamName: string; formation: string | null; players: LineupPlayer[] }) {
  const starters = players.filter((player) => player.starter);
  const substitutes = players.filter((player) => !player.starter);
  return (
    <div className="lineup-column">
      <div className="data-column-heading"><strong>{teamName}</strong><span>{formation ?? "阵型待确认"}</span></div>
      {starters.length > 0 ? (
        <>
          <small className="list-label">首发</small>
          <ul className="player-list">
            {starters.map((player) => <li key={`${player.number}-${player.name}`}><b>{player.number ?? "-"}</b><span>{player.name}</span><small>{player.position}</small></li>)}
          </ul>
          {substitutes.length > 0 && <><small className="list-label">替补</small><ul className="player-list substitutes">{substitutes.map((player) => <li key={`${player.number}-${player.name}`}><b>{player.number ?? "-"}</b><span>{player.name}</span><small>{player.position}</small></li>)}</ul></>}
        </>
      ) : <p className="data-empty">首发名单尚未发布</p>}
    </div>
  );
}

export function TeamLogo({ profile, team, tone }: { profile: TeamProfile; team: Fixture["home_team"]; tone: "home" | "away" }) {
  const logo = profile.logo ?? team.logo;
  return logo ? <Image className={`team-logo ${tone}`} src={logo} alt={`${team.name}队徽`} width={46} height={46} unoptimized /> : <TeamMark team={team} tone={tone} />;
}

const positionLabels: Record<string, string> = {
  Goalkeeper: "门将",
  Defender: "后卫",
  Midfielder: "中场",
  Attacker: "前锋",
  Forward: "前锋",
};

function playerNameStatus(player: { name_status?: string }) {
  return player.name_status === "machine_translated" ? "自动音译" : "";
}

function SquadTable({ teamName, players }: { teamName: string; players: SquadPlayer[] }) {
  const groups = ["Goalkeeper", "Defender", "Midfielder", "Attacker", "Forward"]
    .map((position) => ({ position, rows: players.filter((player) => player.position === position) }))
    .filter((group) => group.rows.length > 0);
  return (
    <details className="squad-column">
      <summary className="squad-summary">
        <span><strong>{teamName}</strong><small>完整注册名单 · {players.length} 人</small></span>
        <span className="squad-count"><b>查看</b><ChevronDown size={15} aria-hidden="true" /></span>
      </summary>
      <div className="squad-scroll">
        {groups.length > 0 ? groups.map((group) => (
          <div className="squad-group" key={group.position}>
            <div className="squad-group-label">{positionLabels[group.position] ?? group.position}<span>{group.rows.length}</span></div>
            <div className="squad-table" role="table" aria-label={`${teamName}${positionLabels[group.position] ?? group.position}名单`}>
              {group.rows.map((player) => <div className="squad-row" role="row" key={player.canonical_player_id ?? player.provider_player_id ?? player.id ?? player.name}>
                <span className="squad-number">{player.number ?? "-"}</span>
                <span className="squad-player-name"><b>{player.name}</b><small>{[player.nationality, playerNameStatus(player)].filter(Boolean).join(" · ")}</small></span>
                <span className="squad-age">{player.age ? `${player.age}岁` : "-"}</span>
                <span className="squad-value" title={player.market_value_source ? `${player.market_value_source} · ${player.market_value_as_of ? formatTimestamp(player.market_value_as_of) : "时间待确认"}` : "暂无可靠身价"}>{player.market_value_eur ?? player.market_value ? `${((player.market_value_eur ?? player.market_value ?? 0) / 1_000_000).toFixed(1)}m` : "暂无可靠身价"}</span>
              </div>)}
            </div>
          </div>
        )) : <p className="data-empty">暂无完整阵容数据</p>}
      </div>
    </details>
  );
}

function formSummary(matches: Array<RecentMatch | string>, teamName: string) {
  const rows = matches.filter(isRecentMatch).slice(0, 5);
  return rows.reduce(
    (summary, match) => {
      const [homeScore, awayScore] = match.score.split(/\s*[-:]\s*/).map(Number);
      const validScore = Number.isFinite(homeScore) && Number.isFinite(awayScore);
      summary[match.result === "W" ? "wins" : match.result === "D" ? "draws" : "losses"] += 1;
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
  const homeForm = formSummary(context.recent_form.home, fixture.home_team.name);
  const awayForm = formSummary(context.recent_form.away, fixture.away_team.name);
  const formLead = context.recent_form.home_points_per_game - context.recent_form.away_points_per_game;
  const availabilityLead = context.availability.home_missing - context.availability.away_missing;
  const formText = Math.abs(formLead) < 0.2 ? "近期积分效率接近" : formLead > 0 ? `近期积分效率偏向${fixture.home_team.name}` : `近期积分效率偏向${fixture.away_team.name}`;
  const availabilityText = availabilityLead === 0 ? "双方已知伤停人数相同" : availabilityLead > 0 ? `${fixture.home_team.name}已知伤停更多` : `${fixture.away_team.name}已知伤停更多`;
  return (
    <section className="analysis-snapshot" aria-labelledby="analysis-snapshot-title">
      <SectionHeader className="section-heading" eyebrow="PRE-MATCH READOUT" title="赛前分析快照" titleId="analysis-snapshot-title" level={3} meta="只读取已同步证据" />
      <div className="analysis-compare">
        {[{ team: fixture.home_team.name, form: homeForm, ppg: context.recent_form.home_points_per_game, side: "主队" }, { team: fixture.away_team.name, form: awayForm, ppg: context.recent_form.away_points_per_game, side: "客队" }].map(({ team, form, ppg, side }) => (
          <div className="analysis-team" key={side}>
            <div><strong>{team}</strong><small>{side}</small></div>
            <b>{form.wins}胜 {form.draws}平 {form.losses}负</b>
            <span>{ppg.toFixed(2)} 分/场 · {form.goalsFor}-{form.goalsAgainst}</span>
          </div>
        ))}
      </div>
      <div className="analysis-facts">
        <span><HeartPulse size={14} />伤停 {context.availability.home_missing} : {context.availability.away_missing}</span>
        <span><Shirt size={14} />首发 {context.lineup.confirmed ? "已确认" : "待发布"}</span>
        <span><BarChart3 size={14} />赔率 {context.odds ? `${context.odds.home.toFixed(2)} / ${context.odds.draw.toFixed(2)} / ${context.odds.away.toFixed(2)}` : "暂无"}</span>
        {prediction && <span><Goal size={14} />预期进球 {prediction.expected_goals.home} : {prediction.expected_goals.away}</span>}
      </div>
      <p className="analysis-note">{formText}；{availabilityText}。{context.lineup.confirmed ? "首发已纳入当前证据。" : "首发未发布，结论仍属于初步版本。"}</p>
    </section>
  );
}

export function TeamProfiles({ detail, showProfiles = true, showSquads = true }: { detail: FixtureDetail; showProfiles?: boolean; showSquads?: boolean }) {
  const { fixture, context } = detail;
  const profiles = [
    { side: "home" as const, team: fixture.home_team, profile: context.teams?.home ?? {} },
    { side: "away" as const, team: fixture.away_team, profile: context.teams?.away ?? {} },
  ];
  const hasProfile = profiles.some(({ profile }) => profile.founded || profile.venue || profile.logo);
  return (
    <section className="team-information" aria-label="球队信息与完整阵容">
      {showProfiles && <div className="detail-data-block team-profile-block">
        <SectionHeader className="section-heading" eyebrow="TEAM DOSSIER" title="球队档案" level={3} meta={hasProfile ? "供应商资料" : "待同步"} />
        <div className="team-profile-grid">
          {profiles.map(({ side, team, profile }) => <div className="team-profile" key={side}><div className="team-profile-top"><TeamLogo profile={profile} team={team} tone={side} /><div><strong>{team.name}</strong><small>{profile.city ?? profile.country ?? "球队资料"}</small></div></div><dl><div><dt>成立</dt><dd>{profile.founded ?? "-"}</dd></div><div><dt>主场</dt><dd>{profile.venue ?? fixture.venue}</dd></div><div><dt>容量</dt><dd>{profile.capacity ? `${profile.capacity.toLocaleString()} 人` : "-"}</dd></div><div><dt>所在地</dt><dd>{profile.city ?? profile.country ?? "-"}</dd></div></dl></div>)}
        </div>
      </div>}
      {showSquads && <div className="detail-data-block squad-block">
        <SectionHeader className="section-heading" eyebrow="SQUAD REGISTER" title="全队球员与身价" level={3} meta="身价字段需授权数据源" />
        <div className="squad-grid"><SquadTable teamName={fixture.home_team.name} players={context.squads?.home ?? []} /><SquadTable teamName={fixture.away_team.name} players={context.squads?.away ?? []} /></div>
        <p className="data-source-note">当前免费公开源提供球员名单、号码、位置、年龄和照片；未提供可验证的实时市场身价，因此显示“暂无身价”，不会用转会费或工资替代。</p>
      </div>}
    </section>
  );
}

type EvidenceSection = "form" | "h2h" | "availability" | "lineup";

export function EvidenceDetails({ detail, sections = ["form", "h2h", "availability", "lineup"] }: { detail: FixtureDetail; sections?: EvidenceSection[] }) {
  const { fixture, context } = detail;
  const homeForm = context.recent_form.home;
  const awayForm = context.recent_form.away;
  const injuries = context.availability.players ?? [];
  const homeInjuries = injuries.filter((player) => player.team === "home");
  const awayInjuries = injuries.filter((player) => player.team === "away");
  const hasEvidence = Boolean(context.synced_at);
  return (
    <section className="evidence-details" aria-label="详细赛前数据">
      {sections.includes("form") && <div className="detail-data-block">
        <SectionHeader className="section-heading" eyebrow="FORM GUIDE" title={`近期战绩（${Math.max(homeForm.length, awayForm.length)}/5）`} level={3} meta={context.recent_form.updated_at ? formatTimestamp(context.recent_form.updated_at) : "待同步"} />
        {hasEvidence ? <div className="recent-form-grid"><RecentFormColumn teamName={fixture.home_team.name} matches={homeForm} pointsPerGame={context.recent_form.home_points_per_game} /><RecentFormColumn teamName={fixture.away_team.name} matches={awayForm} pointsPerGame={context.recent_form.away_points_per_game} /></div> : <p className="data-empty">请先同步这场比赛的赛前数据</p>}
      </div>}

      {sections.includes("h2h") && <div className="detail-data-block">
        <SectionHeader className="section-heading" eyebrow="HEAD TO HEAD" title="历史交锋" level={3} meta={`${context.head_to_head.length} 场`} />
        {context.head_to_head.length > 0 ? <div className="h2h-table" role="table" aria-label="历史交锋记录"><div className="h2h-row h2h-header" role="row"><span>日期</span><span>对阵</span><span>比分</span></div>{context.head_to_head.map((match) => <div className="h2h-row" role="row" key={`${match.date}-${match.home}-${match.away}`}><time>{match.date}</time><span>{match.home} <i>vs</i> {match.away}</span><ParsedScoreline score={match.score} /></div>)}</div> : <p className="data-empty">暂无历史交锋数据</p>}
      </div>}

      {sections.includes("availability") && <div className="detail-data-block">
        <SectionHeader className="section-heading" eyebrow="AVAILABILITY" title="伤停影响" level={3} meta={<><HeartPulse size={13} /> {context.availability.home_missing + context.availability.away_missing} 人</>} />
        {hasEvidence ? <div className="availability-grid"><div><strong>{fixture.home_team.name}</strong><span>{context.availability.home_missing} 人缺阵</span><ul className="absence-list">{homeInjuries.length > 0 ? homeInjuries.map((player) => <li key={`${player.name}-${player.reason}`}><b>{player.name}</b><small>{[player.reason, playerNameStatus(player)].filter(Boolean).join(" · ")}</small></li>) : <li className="absence-empty">暂无已知伤停</li>}</ul></div><div><strong>{fixture.away_team.name}</strong><span>{context.availability.away_missing} 人缺阵</span><ul className="absence-list">{awayInjuries.length > 0 ? awayInjuries.map((player) => <li key={`${player.name}-${player.reason}`}><b>{player.name}</b><small>{[player.reason, playerNameStatus(player)].filter(Boolean).join(" · ")}</small></li>) : <li className="absence-empty">暂无已知伤停</li>}</ul></div></div> : <p className="data-empty">请先同步这场比赛的伤停数据</p>}
      </div>}

      {sections.includes("lineup") && <div className="detail-data-block">
        <SectionHeader className="section-heading" eyebrow="LINEUPS" title="球员名单" level={3} meta={context.lineup.confirmed ? "已确认" : "未公布"} />
        {context.lineup.confirmed ? <div className="lineup-grid"><LineupColumn teamName={fixture.home_team.name} formation={context.lineup.home_formation} players={context.lineup.home_players} /><LineupColumn teamName={fixture.away_team.name} formation={context.lineup.away_formation} players={context.lineup.away_players} /></div> : <div className="lineup-pending"><Shirt size={18} /><div><strong>首发名单尚未发布</strong><p>比赛临近后再次同步，确认首发后会显示首发与替补球员。</p></div></div>}
      </div>}
    </section>
  );
}

const decisionReasonLabels: Record<string, string> = {
  ai_no_bet: "AI 不建议下注",
  negative_edge: "赔率优势不足",
  low_confidence: "预测置信度不足",
  lineup_unconfirmed: "首发未确认",
  stale_odds: "赔率已过期",
  missing_player_data: "球员数据不足",
  no_matching_market: "缺少匹配市场",
  risk_limit: "风险额度受限",
  league_daily_limit: "同模型同联赛当日已有更高优势场次",
  model_disagreement: "模型分歧过大",
};

function impactPlayerKey(player: { canonical_player_id?: string; provider_player_id?: string | null; name: string }) {
  return player.canonical_player_id ?? player.provider_player_id ?? player.name;
}

export function PlayerImpactPanel({ detail }: { detail: FixtureDetail }) {
  const { fixture, context } = detail;
  const impact = context.player_impact;
  const valuePlayer = [...(context.squads?.home ?? []), ...(context.squads?.away ?? [])].find((player) => player.market_value_eur !== null && player.market_value_eur !== undefined);
  const valueMeta = valuePlayer?.market_value_source
    ? `${valuePlayer.market_value_source} · ${valuePlayer.market_value_as_of ? formatTimestamp(valuePlayer.market_value_as_of) : "时间待确认"}`
    : "暂无可靠身价";
  if (!impact) return <section className="player-impact-panel"><SectionHeader eyebrow="PLAYER IMPACT" title="球员影响" level={3} meta="数据不足" /><p className="data-empty">当前阵容证据不足，未对球队战力作人数式扣减。</p></section>;
  const teams = [
    { side: "home" as const, name: fixture.home_team.name, data: impact.home },
    { side: "away" as const, name: fixture.away_team.name, data: impact.away },
  ];
  return <section className="player-impact-panel" aria-labelledby="player-impact-title">
    <SectionHeader className="section-heading" eyebrow="PLAYER IMPACT" title="球员影响与战力保留" titleId="player-impact-title" level={3} meta={impact.lineup_confirmed ? "已按确认首发重算" : "基于预计首发与分钟"} />
    <div className="player-impact-grid">
      {teams.map(({ side, name, data }) => {
        const retention = [
          ["进攻", data.attack_retention],
          ["防守", data.defense_retention],
          ["中场", data.midfield_retention],
          ["门将", data.goalkeeper_retention],
        ] as const;
        return <div className={`player-impact-team ${side}`} key={side}>
          <header><div><strong>{name}</strong><small>{data.data_status === "complete" ? "球员数据完整" : data.data_status === "partial" ? "球员数据部分完整" : "球员数据不足"}</small></div><span>{data.squad_count} 人阵容</span></header>
          <div className="retention-list">{retention.map(([label, value]) => <div key={label}><span>{label}</span><i><b style={{ "--retention": percent(value) } as React.CSSProperties} /></i><strong>{percent(value)}</strong></div>)}</div>
          <div className="impact-player-groups">
            <div><span>关键可用</span><ul>{data.key_available_players.length ? data.key_available_players.map((player) => <li key={impactPlayerKey(player)}><b>{player.name}</b><small>{player.player_role} · 预计 {Math.round(player.expected_minutes)} 分钟{playerNameStatus(player) ? ` · ${playerNameStatus(player)}` : ""}</small></li>) : <li><small>暂无可靠识别</small></li>}</ul></div>
            <div><span>关键缺阵</span><ul>{data.key_absent_players.length ? data.key_absent_players.map((player) => <li key={impactPlayerKey(player)}><b>{player.name}</b><small>{player.player_role} · 影响 {percent(player.absence_impact ?? 0)}{playerNameStatus(player) ? ` · ${playerNameStatus(player)}` : ""}</small></li>) : <li><small>暂无关键缺阵</small></li>}</ul></div>
          </div>
          {data.expected_replacements.length > 0 && <div className="replacement-line"><span>预计替补</span>{data.expected_replacements.slice(0, 2).map((row) => <p key={impactPlayerKey(row.absent_player)}><b>{row.absent_player.name}</b><ChevronRight size={13} aria-hidden="true" /><strong>{row.replacement?.name ?? "暂无同位置替补"}</strong><small>差值 {percent(row.absence_impact)}</small></p>)}</div>}
        </div>;
      })}
    </div>
    <footer className="player-value-provenance"><Database size={14} aria-hidden="true" /><span>身价边界</span><strong>{valueMeta}</strong><small>{context.player_value?.reason ?? `${context.player_value?.available_count ?? 0} 人有可靠身价`}</small></footer>
  </section>;
}

export function ProbabilityPanel({ prediction, fixture, bet, onManualPredict, predicting = false }: { prediction: Prediction; fixture: Fixture; bet: SimulatedBet | null; onManualPredict?: () => void; predicting?: boolean }) {
  const headingId = `prediction-title-${prediction.id}`;
  const currentBet = bet?.prediction_id === prediction.id ? bet : null;
  const options = [
    { key: "home", label: "主胜", team: fixture.home_team.name, value: prediction.probabilities.home },
    { key: "draw", label: "平局", team: "双方战平", value: prediction.probabilities.draw },
    { key: "away", label: "客胜", team: fixture.away_team.name, value: prediction.probabilities.away },
  ] as const;
  const best = options.reduce((left, right) => (left.value > right.value ? left : right));
  const aiHandicap = prediction.asian_handicap_forecast ?? prediction.forecast?.asian_handicap;
  const marketRows = prediction.market_assessment?.markets ?? [];
  const decision = prediction.decision;
  const execution = prediction.execution;
  const modelRecommendation = prediction.model_recommendation;
  const advisedMarket = marketRows.find((row) => row.market === decision?.considered_market && row.selection === decision?.considered_selection);
  const executionStatus = execution?.status ?? (currentBet ? "bet" : decision?.status);
  const executionLabel = executionStatus === "bet" ? "执行模拟下注" : executionStatus === "no_bet" ? "本场不执行" : "数据不足，不执行";
  const executionReasons = execution?.reason_codes ?? decision?.reason_codes ?? [];
  return (
    <section className="prediction-panel" aria-labelledby={headingId}>
      <div className="prediction-header">
        <div>
          <span>01 · 赛果判断</span>
          <h3 id={headingId}>{prediction.phase === "confirmed_lineup" ? "确认首发版" : "初步预测"} · 胜平负概率</h3>
        </div>
        <div className="prediction-actions">
          {prediction.phase === "preliminary" && fixture.status === "scheduled" && onManualPredict && <button className="manual-predict-button" type="button" title="基于当前已同步赛前数据重新生成初步预测" onClick={onManualPredict} disabled={predicting}>{predicting ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : <Play size={13} fill="currentColor" aria-hidden="true" />}{predicting ? "计算中" : "重新生成"}</button>}
          <span className="model-tag">{prediction.model_version}</span>
        </div>
      </div>
      <div className="probability-grid">
        {options.map((item) => (
          <div className={item.key === best.key ? "probability winner" : "probability"} key={item.key}>
            <span>{item.label}</span><strong>{percent(item.value)}</strong><small>{item.team}</small>
            <i style={{ "--probability": percent(item.value) } as React.CSSProperties} />
          </div>
        ))}
      </div>
      {prediction.ai && (
        <div className={`ai-assessment ai-${prediction.ai.status}`}>
          <div className="ai-assessment-copy">
            <span>{prediction.ai.provider === "chatgpt" ? "CHATGPT ASSESSMENT" : "DEEPSEEK ASSESSMENT"}</span>
            <strong>{prediction.ai.status !== "completed" ? "AI 不可用，当前仅显示 Poisson 基线" : prediction.analysis_summary}</strong>
            <small>{prediction.ai.status === "completed" ? `${prediction.ai.returned_model} · ${prediction.ai.prompt_version} · ${prediction.ai.evidence_version ?? "证据版本待确认"}` : prediction.ai.error}</small>
            {prediction.ai.status === "completed" && prediction.player_analysis?.replacement_gap ? <p className="ai-thesis"><b>替补差值</b>{prediction.player_analysis.replacement_gap}</p> : null}
            {prediction.ai.status === "completed" && modelRecommendation ? <p className="ai-thesis"><b>AI 下注观点</b>{modelRecommendation.status === "bet" ? `${selectionWithHandicap(modelRecommendation.selection, aiHandicap?.line)} · ${modelRecommendation.reason}` : `不下注 · ${modelRecommendation.reason}`}</p> : null}
          </div>
          <dl>
            <div><dt>最可能赛果</dt><dd>{outcomeText(prediction.forecast?.predicted_outcome ?? prediction.predicted_outcome)}</dd></div>
            <div><dt>预测置信度</dt><dd>{percent(prediction.forecast_confidence ?? decision?.model_confidence ?? 0)}</dd></div>
            <div><dt>亚洲盘</dt><dd>{aiHandicap && aiHandicap.line !== null ? `${percent(aiHandicap.home_cover_probability ?? 0)} 主队覆盖` : "证据不足"}</dd></div>
          </dl>
          {prediction.ai.status === "completed" && prediction.risk_factors?.length ? <div className="ai-risk-factors"><span>风险因素</span><ul>{prediction.risk_factors.map((risk) => <li key={risk}>{risk}</li>)}</ul></div> : null}
          {prediction.ai.status === "completed" && prediction.missing_evidence?.length ? <div className="ai-caveats"><span>证据缺口</span><ul>{prediction.missing_evidence.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
          {aiHandicap && <p className="ai-handicap-note">亚洲让球覆盖预测：{aiHandicap.line !== null ? `${formatFavoriteHandicap(aiHandicap.line, fixture.home_team.name, fixture.away_team.name)} · 主队 ${percent(aiHandicap.home_cover_probability ?? 0)} / 客队 ${percent(aiHandicap.away_cover_probability ?? 0)}` : "无可用盘口"}{aiHandicap.reason ? ` · ${aiHandicap.reason}` : ""}</p>}
          {prediction.evidence_hash && <code>证据 {prediction.evidence_hash.slice(0, 12)}</code>}
        </div>
      )}
      <div className="prediction-facts">
        <span><Goal size={16} />预期进球 {prediction.expected_goals.home} : {prediction.expected_goals.away}</span>
        <span><Gauge size={16} />证据置信度 {prediction.confidence}</span>
        <span><Clock3 size={16} />生成于 {formatTimestamp(prediction.created_at)}</span>
      </div>
      <section className="market-value-layer" aria-label="赔率价值">
        <header><div><span>02 · 赔率价值</span><strong>市场数学</strong></div><small>{prediction.market_assessment?.bookmaker ?? "暂无匹配赔率"} · {prediction.market_assessment?.odds_status === "fresh" ? "赔率有效" : prediction.market_assessment?.odds_status === "stale" ? "赔率已过期" : "赔率缺失"}</small></header>
        {marketRows.length ? <div className="market-value-table"><div className="market-value-head"><span>市场</span><span>模型</span><span>回本线</span><span>去水</span><span>优势</span></div>{marketRows.map((row) => <div className="market-value-row" key={`${row.market}-${row.selection}`}><span className="market-value-name"><b>{selectionWithHandicap(row.selection, row.line)}</b><small>{row.market === "asian_handicap" && row.line !== undefined ? `亚洲盘 ${formatHandicapLine(row.selection === "away_handicap" ? -row.line : row.line)}` : "胜平负"} · {row.price.toFixed(2)}</small></span><span><small>模型</small><b>{percent(row.model_probability)}</b></span><span><small>回本线</small><b>{percent(row.break_even_probability)}</b></span><span><small>去水</small><b>{percent(row.de_vig_probability)}</b></span><span className={row.expected_edge > 0 ? "edge-positive" : "edge-negative"}><small>优势</small><b>{row.expected_edge > 0 ? "+" : ""}{(row.expected_edge * 100).toFixed(1)}%</b></span></div>)}</div> : <p className="data-empty">没有可计算的匹配赔率市场</p>}
      </section>
      <section className={`execution-layer execution-${decision?.status ?? "insufficient_data"}`} aria-label="执行决定">
        <header><span>03 · 执行决定</span><strong>{executionLabel}</strong><small>单注 10%–25% · 每日 50% · 每联赛 1 场</small></header>
        <div><p>{execution?.reason ?? decision?.reason ?? "当前预测版本缺少确定性决策结果"}</p>{decision?.warning ? <p>{decision.warning}</p> : null}{executionReasons.length ? <ul>{executionReasons.map((code) => <li key={code}>{decisionReasonLabels[code] ?? code}</li>)}</ul> : null}<dl><div><dt>建议方向</dt><dd>{advisedMarket ? `${marketText(advisedMarket.market)} · ${selectionWithHandicap(advisedMarket.selection, advisedMarket.line)}` : outcomeText(prediction.forecast?.predicted_outcome ?? prediction.predicted_outcome)}</dd></div><div><dt>预期优势</dt><dd>{decision?.expected_edge !== null && decision?.expected_edge !== undefined ? `${decision.expected_edge > 0 ? "+" : ""}${(decision.expected_edge * 100).toFixed(1)}%` : "-"}</dd></div><div><dt>不确定性</dt><dd>{percent(decision?.uncertainty ?? 1)}</dd></div><div><dt>理论仓位</dt><dd>{percent(decision?.stake_fraction ?? 0)}</dd></div></dl></div>
      </section>
      {currentBet && (
        <div className="simulated-position">
          <span>本次模拟仓位</span>
          <strong>{selectionWithHandicap(currentBet.selection, currentBet.handicap_line)} · {currentBet.odds.toFixed(2)}</strong>
          <small>金额 {currentBet.stake.toFixed(2)} · {currentBet.status === "placed" ? "未结算" : `${currentBet.settlement_result ?? "已结算"} · 盈亏 ${currentBet.net_profit?.toFixed(2) ?? "-"}`}</small>
        </div>
      )}
      {prediction.asian_handicap && (
        <div className="handicap-block">
          <div><span>市场盘口（博彩公司）</span><strong>{formatFavoriteHandicap(prediction.asian_handicap.line, fixture.home_team.name, fixture.away_team.name)}</strong><small>Poisson 基线倾向：{handicapRecommendation(prediction.asian_handicap.home_settlement, prediction.asian_handicap.line, fixture.home_team.name, fixture.away_team.name)}</small></div>
          {Object.entries(prediction.asian_handicap.home_settlement).map(([key, value]) => (
            <span key={key}><small>{settlementLabels[key as keyof typeof settlementLabels]}</small><b>{percent(value)}</b></span>
          ))}
        </div>
      )}
      <p className="disclaimer">概率是模型对赛前信息的量化结果，不代表确定赛果，也不构成投注建议。</p>
    </section>
  );
}

function DetailPanel({ detail, operatorMode, running, syncingEvidence, success, actionRef, onPredict, onSyncEvidence }: { detail: FixtureDetail; operatorMode: boolean; running: boolean; syncingEvidence: boolean; success: Prediction | null; actionRef: React.RefObject<HTMLButtonElement | null>; onPredict: () => void; onSyncEvidence: () => void }) {
  const { fixture, context, prediction } = detail;
  const realEvidencePending = !fixture.is_demo && !context.synced_at;
  const canSyncEvidence = detail.capabilities.evidence_sync;
  return (
    <aside className="detail-panel">
      <div className="match-summary">
        <div className="detail-kicker"><span>{fixture.league.name}</span><span>{fixture.is_demo ? "演示数据" : "提供商数据"}</span></div>
        <div className="match-teams">
          <div><TeamLogo profile={context.teams?.home ?? {}} team={fixture.home_team} tone="home" /><strong>{fixture.home_team.name}</strong><small>主队</small></div>
          {fixture.score ? <span className="versus score-versus"><Scoreline home={fixture.score.home} away={fixture.score.away} large /><small>{fixture.score.home > fixture.score.away ? "主胜" : fixture.score.home < fixture.score.away ? "客胜" : "平局"}</small></span> : <span className="versus">VS<small>{formatKickoff(fixture.kickoff)}</small></span>}
          <div><TeamLogo profile={context.teams?.away ?? {}} team={fixture.away_team} tone="away" /><strong>{fixture.away_team.name}</strong><small>客队</small></div>
        </div>
        <p><CalendarDays size={15} /> {new Date(fixture.kickoff).toLocaleDateString("zh-CN")} · {fixture.venue}</p>
      </div>

      {operatorMode && fixture.status !== "finished" && (
        <div className="operator-actions">
          <div><strong>{realEvidencePending ? canSyncEvidence ? "真实赛前证据尚未同步" : "赛前证据源未配置" : prediction ? "生成新预测版本" : "这场比赛尚未预测"}</strong><small>{realEvidencePending ? canSyncEvidence ? "赛程与双方身份已就绪，等待拉取近期状态、伤停和赔率" : "赛程与双方身份已就绪；近期状态、伤停和赔率暂不可用" : context.lineup.confirmed ? "确认首发已纳入，可以生成最终赛前版" : "首发未确认，将生成初步预测"}</small></div>
          <button className="icon-button secondary" title={canSyncEvidence ? "同步这场比赛的赛前数据" : "请先配置 API-Football"} aria-label="同步赛前数据" onClick={onSyncEvidence} disabled={syncingEvidence || !canSyncEvidence}>{syncingEvidence ? <LoaderCircle className="spin" size={18} /> : <RefreshCw size={18} />}</button>
          <button ref={actionRef} className="primary-action" onClick={onPredict} disabled={running || realEvidencePending} aria-describedby={success ? "prediction-success" : undefined}>
            {running ? <LoaderCircle className="spin" size={18} /> : <Play size={18} fill="currentColor" />}
            {running ? "计算中" : realEvidencePending ? "先同步证据" : "发起预测"}
          </button>
        </div>
      )}

      {operatorMode && success && (
        <div className="prediction-success" id="prediction-success" role="status" aria-live="polite">
          <Check size={17} aria-hidden="true" />
          <span><strong>预测版本已保存</strong><small>版本 {success.id.slice(0, 8)} · {formatPreciseTimestamp(success.created_at)}</small></span>
        </div>
      )}

      {context.synced_at ? <AnalysisSnapshot detail={detail} /> : (
        <section className="analysis-snapshot evidence-pending" aria-label="赛前证据状态">
          <Database size={21} aria-hidden="true" />
          <div>
            <strong>双方基础信息已就绪</strong>
            <p>{canSyncEvidence ? "赛前证据尚未同步，暂不计算近期表现、伤停影响或概率。" : "API-Football 未配置，暂不展示近期表现、伤停影响或概率。"}</p>
          </div>
        </section>
      )}

      <EvidenceRail detail={detail} />

      <TeamProfiles detail={detail} />

      <EvidenceDetails detail={detail} />

      <section className="market-section" aria-labelledby="market-title">
        <SectionHeader className="section-heading" eyebrow="PRE-MATCH MARKET" title="赛前赔率快照" titleId="market-title" level={3} meta={context.odds ? `${context.odds.bookmaker} · ${formatTimestamp(context.odds.updated_at)}` : "暂无"} />
        {context.odds ? (
          <>
            <div className="odds-row">
              <span><small>主胜</small><b>{context.odds.home.toFixed(2)}</b></span>
              <span><small>平局</small><b>{context.odds.draw.toFixed(2)}</b></span>
              <span><small>客胜</small><b>{context.odds.away.toFixed(2)}</b></span>
              {context.odds.asian_handicap !== null && <>
                <span><small>{formatHandicapSide(context.odds.asian_handicap, "home")}</small><b>{context.odds.asian_handicap_home_odd?.toFixed(2) ?? "-"}</b></span>
                <span><small>{formatHandicapSide(context.odds.asian_handicap, "away")}</small><b>{context.odds.asian_handicap_away_odd?.toFixed(2) ?? "-"}</b></span>
              </>}
            </div>
            <p className="data-source-note">来源：API-Football / API-Sports 的赛前赔率接口；当前取返回结果中的第一家 bookmaker，记录同步时间。</p>
          </>
        ) : <p className="empty-note">这场比赛没有可用的赛前赔率，因此不会生成让球判断。</p>}
      </section>

      {detail.predictions && Object.values(detail.predictions).some(Boolean) ? <DualProbabilityPanels detail={detail} /> : prediction ? <ProbabilityPanel prediction={prediction} fixture={fixture} bet={detail.bet} /> : (
        <section className="no-prediction">
          <Database size={23} aria-hidden="true" />
          <div><h3>暂无当前版本预测</h3><p>{realEvidencePending ? "真实赛程已经缓存；点击同步赛前数据后，系统会拉取近期状态、交锋、伤停和赔率。" : operatorMode ? "核对数据状态后，可手动生成当前版本预测。" : "证据同步完成后，系统会自动生成当前版本预测。"}</p></div>
        </section>
      )}
    </aside>
  );
}

export function DualProbabilityPanels({ detail, onManualPredict, predicting = false }: { detail: FixtureDetail; onManualPredict?: () => void; predicting?: boolean }) {
  const entries: Array<[ModelKey, Prediction]> = (["deepseek", "chatgpt"] as ModelKey[])
    .map((key) => [key, detail.predictions?.[key] ?? null] as const)
    .filter((item): item is [ModelKey, Prediction] => Boolean(item[1]));
  const [selectedModel, setSelectedModel] = useState<ModelKey>("deepseek");
  const tabRefs = useRef<Partial<Record<ModelKey, HTMLButtonElement | null>>>({});
  if (!entries.length && detail.prediction) {
    return <ProbabilityPanel prediction={detail.prediction} fixture={detail.fixture} bet={detail.bet} onManualPredict={onManualPredict} predicting={predicting} />;
  }
  if (!entries.length) return null;
  const [activeKey, activePrediction] = entries.find(([key]) => key === selectedModel) ?? entries[0];
  const activeBet = detail.bets?.[activeKey] ?? null;

  function selectTab(key: ModelKey) {
    setSelectedModel(key);
    window.requestAnimationFrame(() => tabRefs.current[key]?.focus());
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, currentKey: ModelKey) {
    const currentIndex = entries.findIndex(([key]) => key === currentKey);
    let nextIndex: number | null = null;
    if (["ArrowDown", "ArrowRight"].includes(event.key)) nextIndex = (currentIndex + 1) % entries.length;
    if (["ArrowUp", "ArrowLeft"].includes(event.key)) nextIndex = (currentIndex - 1 + entries.length) % entries.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = entries.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(entries[nextIndex][0]);
  }

  return (
    <section className="dual-prediction-section" aria-label="双模型初步预测">
      <div className="dual-prediction-heading">
        <div><span>MODEL ANALYSIS</span><h3>比赛的初步预测</h3></div>
        <div className="dual-prediction-actions">
          <small>共享同一证据，各自给出观点并使用独立模拟账户</small>
          {detail.fixture.status === "scheduled" && onManualPredict && <button className="manual-predict-button" type="button" title="使用当前赛前数据并行重新生成两个模型的预测" onClick={onManualPredict} disabled={predicting}>{predicting ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : <Play size={13} fill="currentColor" aria-hidden="true" />}{predicting ? "计算中" : "重新生成"}</button>}
        </div>
      </div>
      <div className="dual-prediction-shell">
        <div className="model-prediction-tabs" role="tablist" aria-label="选择预测模型">
        {entries.map(([key, prediction]) => (
          <button
            className={`model-prediction-tab model-${key}${activeKey === key ? " active" : ""}`}
            id={`model-tab-${key}-${detail.fixture.id}`}
            key={key}
            ref={(node) => { tabRefs.current[key] = node; }}
            type="button"
            role="tab"
            aria-selected={activeKey === key}
            aria-controls={`model-panel-${key}-${detail.fixture.id}`}
            tabIndex={activeKey === key ? 0 : -1}
            onClick={() => setSelectedModel(key)}
            onKeyDown={(event) => handleTabKeyDown(event, key)}
          >
            <span className="model-tab-name">{key === "deepseek" ? "DeepSeek" : "GPT-5.6 Sol"}</span>
            <strong className="model-tab-judgment">{outcomeText(prediction.forecast?.predicted_outcome ?? prediction.predicted_outcome)}</strong>
            <span className={`model-tab-investment${prediction.execution?.status !== "bet" ? " no-bet" : ""}`}>{prediction.execution?.status === "bet" ? selectionText(prediction.decision?.selection) : prediction.decision?.considered_selection ? `建议 ${selectionText(prediction.decision.considered_selection)}` : "数据不足"}</span>
            <small className="model-tab-position">{detail.bets?.[key]?.prediction_id === prediction.id ? `本次仓位 ${detail.bets[key]?.stake.toFixed(2)}` : "当前无持仓"}</small>
          </button>
        ))}
        </div>
        <div
          className={`model-prediction-panel model-${activeKey}`}
          id={`model-panel-${activeKey}-${detail.fixture.id}`}
          role="tabpanel"
          aria-labelledby={`model-tab-${activeKey}-${detail.fixture.id}`}
        >
          <ProbabilityPanel prediction={activePrediction} fixture={detail.fixture} bet={activeBet} />
        </div>
      </div>
    </section>
  );
}

function outcomeText(value?: string) {
  return value ? ({ home: "主胜", draw: "平局", away: "客胜" }[value] ?? value) : "-";
}

function marketText(value?: string) {
  return value ? ({ "1x2": "胜平负", asian_handicap: "亚洲盘", no_bet: "不下注" }[value] ?? value) : "-";
}

function selectionText(value?: string) {
  return value ? ({ home: "主胜", draw: "平局", away: "客胜", home_handicap: "主队亚洲盘", away_handicap: "客队亚洲盘", none: "无" }[value] ?? value) : "-";
}

export function FixtureWorkspace({ operatorMode }: { operatorMode: boolean }) {
  const [dateFilter, setDateFilter] = useState<DateFilter>("today");
  const [leagueFilter, setLeagueFilter] = useState<LeagueFilter>("all");
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FixtureDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [success, setSuccess] = useState<Prediction | null>(null);
  const [dataMode, setDataMode] = useState<DataMode>("unconfigured");
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("unconfigured");
  const [scheduleProvider, setScheduleProvider] = useState("thesportsdb");
  const [leagueCounts, setLeagueCounts] = useState<Record<string, number>>({});
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncingEvidence, setSyncingEvidence] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const actionRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    void fetchFixtures(dateFilter, leagueFilter)
      .then((response) => {
        if (!active) return;
        setFixtures(response.items);
        setDataMode(response.mode);
        setSyncStatus(response.sync_status);
        setScheduleProvider(response.schedule_provider);
        setLeagueCounts(response.league_counts ?? {});
        setLastSyncedAt(response.last_synced_at);
        if (operatorMode) {
          setSelectedId((current) => response.items.some((item) => item.id === current) ? current : response.items[0]?.id ?? null);
        } else {
          setSelectedId(null);
          setDetail(null);
        }
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "赛程加载失败");
        setFixtures([]);
        setSelectedId(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [dateFilter, leagueFilter, operatorMode, reloadToken]);

  useEffect(() => {
    if (!operatorMode || !selectedId) return;
    let active = true;
    void fetchFixtureDetail(selectedId)
      .then((response) => { if (active) setDetail(response); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "比赛详情加载失败"); });
    return () => { active = false; };
  }, [operatorMode, selectedId]);

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
      const payload = await response.json() as { prediction?: Prediction; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "预测运行失败");
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
      const payload = await response.json() as { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "赛前数据同步失败");
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
      const payload = await response.json() as { detail?: string; item_count?: number; request_count?: number };
      if (!response.ok) throw new Error(payload.detail ?? "赛程同步失败");
      setSyncMessage(`已同步 ${payload.item_count ?? 0} 场比赛，使用 ${payload.request_count ?? 3} 次接口额度`);
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
      <main className="score-center-page">
        <DataFreshness
          className="status-strip"
          status={syncStatus}
          label={dataMode === "demo" ? "演示数据模式" : syncLabel}
          source={lastSyncedAt ? `${scheduleProvider} · 更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : `${scheduleProvider} · 首次访问自动获取`}
        />
        <PageHeader
          className="score-center-title"
          eyebrow="FOOTBALL SCORES"
          title="比赛中心"
          description="中超、西甲与英超赛程、比分和赛前数据。"
          aside={<div className="today-stamp"><CalendarDays size={19} aria-hidden="true" /><span><small>北京时间</small><strong>{new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" })}</strong></span></div>}
        />
        <div className="score-center-filter">
          <Tabs className="score-date-tabs" ariaLabel="日期范围" value={dateFilter} onChange={(value) => { setLoading(true); setDateFilter(value); }} items={dateTabs.map((tab) => ({ value: tab.key, label: tab.label }))} />
          <Tabs className="score-league-tabs" ariaLabel="联赛筛选" value={leagueFilter} onChange={(value) => { setLoading(true); setLeagueFilter(value); }} items={leagueTabs.map((tab) => ({ value: tab.key, label: tab.label, badge: tab.key !== "all" ? leagueCounts[tab.key] ?? 0 : undefined }))} />
        </div>
        {error && <div className="error-banner score-center-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}<button type="button" onClick={() => setError(null)} aria-label="关闭错误提示">×</button></div>}
        <ScoreCenterHome fixtures={fixtures} loading={loading} dataMode={dataMode} syncStatus={syncStatus} freshnessLabel={dataMode === "demo" ? "演示数据模式" : syncLabel} scheduleProvider={scheduleProvider} lastSyncedAt={lastSyncedAt} />
      </main>
    );
  }

  return (
    <main className="operator-page">
      <DataFreshness
        className="status-strip"
        status={syncStatus}
        label={<><Database size={14} aria-hidden="true" />{dataMode === "demo" ? "演示数据模式" : syncLabel}</>}
        source={`系统就绪 · ${lastSyncedAt ? `${scheduleProvider} · 更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : `${scheduleProvider} · 首次访问自动获取`}`}
        action={<button className="sync-action" onClick={() => void syncFixtures()} disabled={syncing}>{syncing ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}{syncing ? "同步中" : "同步赛程"}</button>}
      />
      {syncMessage && <div className="sync-success" role="status" aria-live="polite"><Check size={16} />{syncMessage}</div>}
      <PageHeader
        className="workspace-title"
        eyebrow={operatorMode ? "OPERATOR CONTROL" : "FIXTURE OPERATIONS"}
        title={operatorMode ? "预测操作台" : "赛程与赛前判断"}
        description={operatorMode ? "只对选中的比赛生成预测，每次运行保留独立版本。" : "浏览三个联赛的赛程，并查看管理员已发布的赛前概率。"}
        aside={<div className="today-stamp"><CalendarDays size={19} /><span><small>北京时间</small><strong>{new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" })}</strong></span></div>}
      />

      <div className="filter-band">
        <Tabs className="segmented" ariaLabel="日期范围" value={dateFilter} onChange={(value) => { setLoading(true); setSuccess(null); setDateFilter(value); }} items={dateTabs.map((tab) => ({ value: tab.key, label: tab.label }))} />
        <Tabs className="league-filter" ariaLabel="联赛筛选" value={leagueFilter} onChange={(value) => { setLoading(true); setSuccess(null); setLeagueFilter(value); }} items={leagueTabs.map((tab) => ({ value: tab.key, label: tab.label, badge: tab.key !== "all" ? leagueCounts[tab.key] ?? 0 : undefined }))} />
      </div>

      {error && <div className="error-banner" role="alert"><AlertTriangle size={18} />{error}<button onClick={() => setError(null)} aria-label="关闭错误提示">×</button></div>}

      <div className="workspace-grid">
        <section className="fixture-board" aria-labelledby="fixture-list-title">
          <div className="board-heading">
            <div><span>开球</span><h2 id="fixture-list-title">比赛</h2></div>
            <span>数据状态</span>
          </div>
          {loading ? <div className="loading-state"><LoaderCircle className="spin" />正在读取赛程</div> : fixtures.length ? fixtures.map((fixture) => (
            <FixtureRow key={fixture.id} fixture={fixture} selected={fixture.id === selectedId} onSelect={() => { setSuccess(null); setSelectedId(fixture.id); }} />
          )) : <div className="loading-state"><CalendarDays />{dataMode === "unconfigured" ? "请在 API 服务中配置免费赛程数据源" : dataMode === "error" ? "自动获取赛程失败，请稍后刷新" : "当前筛选下没有比赛"}</div>}
        </section>
        {detail && selectedId === detail.fixture.id ? <DetailPanel detail={detail} operatorMode={operatorMode} running={running} syncingEvidence={syncingEvidence} success={success} actionRef={actionRef} onPredict={() => void runPrediction()} onSyncEvidence={() => void syncEvidence()} /> : selectedId ? (
          <aside className="detail-panel detail-loading"><LoaderCircle className="spin" />读取比赛证据</aside>
        ) : <aside className="detail-panel detail-loading"><Database />同步真实赛程后可查看比赛详情</aside>}
      </div>
      {operatorMode && <OperationsPanel />}
    </main>
  );
}
