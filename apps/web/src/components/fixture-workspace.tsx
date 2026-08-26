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
import { OperationsPanel } from "@/components/operations-panel";
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
function handicapDirection(line: number, homeTeam: string, awayTeam: string) {
  const notation = line > 0 ? `+${line}` : `${line}`;
  if (line < 0) return `${homeTeam}让球 ${notation}`;
  if (line > 0) return `${awayTeam}让球 ${notation}`;
  return "双方平手 0";
}

function handicapMarketLabel(line: number, team: "home" | "away") {
  const teamLabel = team === "home" ? "主队" : "客队";
  const role = line < 0 ? "让球" : line > 0 ? "受让" : "平手";
  const notation = line > 0 ? `+${line}` : `${line}`;
  return `${teamLabel}${role} ${notation}`;
}

function handicapRecommendation(settlement: NonNullable<Prediction["asian_handicap"]>["home_settlement"], line: number, homeTeam: string, awayTeam: string) {
  const homePositive = settlement.full_win + settlement.half_win;
  const homeNegative = settlement.full_loss + settlement.half_loss;
  const recommendsHome = homePositive >= homeNegative;
  const team = recommendsHome ? homeTeam : awayTeam;
  const recommendedLine = recommendsHome ? line : -line;
  const notation = recommendedLine > 0 ? `+${recommendedLine}` : `${recommendedLine}`;
  return `${team} ${notation}`;
}

function handicapSelection(selection: "home_handicap" | "away_handicap", line: number, homeTeam: string, awayTeam: string) {
  const isHome = selection === "home_handicap";
  const value = isHome ? line : -line;
  const notation = value > 0 ? `+${value}` : `${value}`;
  return `${isHome ? homeTeam : awayTeam} ${notation}`;
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

function ScoreCenterSidebar({ fixtures }: { fixtures: Fixture[] }) {
  const counts = fixtures.reduce<Record<string, number>>((result, fixture) => {
    result[fixture.league.name] = (result[fixture.league.name] ?? 0) + 1;
    return result;
  }, {});
  return <aside className="score-center-sidebar" aria-label="赛程概览">
    <section>
      <div className="score-center-side-heading"><span>FOOTBALL TODAY</span><h2>赛事概览</h2></div>
      <dl className="score-center-stats"><div><dt>比赛</dt><dd>{fixtures.length}</dd></div><div><dt>联赛</dt><dd>{Object.keys(counts).length}</dd></div><div><dt>进行中</dt><dd>{fixtures.filter((item) => item.status === "live").length}</dd></div></dl>
    </section>
    <section>
      <div className="score-center-side-heading"><span>COMPETITIONS</span><h2>联赛</h2></div>
      <ul className="competition-list">{Object.entries(counts).map(([league, count]) => <li key={league}><span>{league}</span><b>{count}</b></li>)}</ul>
    </section>
    <section className="score-center-note"><ShieldCheck size={18} aria-hidden="true" /><div><strong>赛前数据持续更新</strong><p>临近开球时自动补充近期战绩、交锋、伤停与首发信息。</p></div></section>
  </aside>;
}

function ScoreCenterHome({ fixtures, loading, dataMode }: { fixtures: Fixture[]; loading: boolean; dataMode: DataMode }) {
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
    <ScoreCenterSidebar fixtures={fixtures} />
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
      <div className="section-heading">
        <div><span>INPUT READINESS</span><h3 id="evidence-title">赛前证据轨道</h3></div>
        <small>{Object.values(readiness).filter(Boolean).length} / 6 就绪</small>
      </div>
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
              {group.rows.map((player) => <div className="squad-row" role="row" key={player.id ?? player.original_name}>
                <span className="squad-number">{player.number ?? "-"}</span>
                <span className="squad-player-name"><b>{player.name}</b><small>{player.nationality ?? ""}</small></span>
                <span className="squad-age">{player.age ? `${player.age}岁` : "-"}</span>
                <span className="squad-value">{player.market_value ? `${(player.market_value / 1_000_000).toFixed(1)}m` : "暂无身价"}</span>
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
      <div className="section-heading"><div><span>PRE-MATCH READOUT</span><h3 id="analysis-snapshot-title">赛前分析快照</h3></div><small>只读取已同步证据</small></div>
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
        <div className="section-heading"><div><span>TEAM DOSSIER</span><h3>球队档案</h3></div><small>{hasProfile ? "供应商资料" : "待同步"}</small></div>
        <div className="team-profile-grid">
          {profiles.map(({ side, team, profile }) => <div className="team-profile" key={side}><div className="team-profile-top"><TeamLogo profile={profile} team={team} tone={side} /><div><strong>{team.name}</strong><small>{profile.original_name ?? ""}</small></div></div><dl><div><dt>成立</dt><dd>{profile.founded ?? "-"}</dd></div><div><dt>主场</dt><dd>{profile.venue ?? fixture.venue}</dd></div><div><dt>容量</dt><dd>{profile.capacity ? `${profile.capacity.toLocaleString()} 人` : "-"}</dd></div><div><dt>所在地</dt><dd>{profile.city ?? profile.country ?? "-"}</dd></div></dl></div>)}
        </div>
      </div>}
      {showSquads && <div className="detail-data-block squad-block">
        <div className="section-heading"><div><span>SQUAD REGISTER</span><h3>全队球员与身价</h3></div><small>身价字段需授权数据源</small></div>
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
        <div className="section-heading"><div><span>FORM GUIDE</span><h3>近期战绩（{Math.max(homeForm.length, awayForm.length)}/5）</h3></div><small>{context.recent_form.updated_at ? formatTimestamp(context.recent_form.updated_at) : "待同步"}</small></div>
        {hasEvidence ? <div className="recent-form-grid"><RecentFormColumn teamName={fixture.home_team.name} matches={homeForm} pointsPerGame={context.recent_form.home_points_per_game} /><RecentFormColumn teamName={fixture.away_team.name} matches={awayForm} pointsPerGame={context.recent_form.away_points_per_game} /></div> : <p className="data-empty">请先同步这场比赛的赛前数据</p>}
      </div>}

      {sections.includes("h2h") && <div className="detail-data-block">
        <div className="section-heading"><div><span>HEAD TO HEAD</span><h3>历史交锋</h3></div><small>{context.head_to_head.length} 场</small></div>
        {context.head_to_head.length > 0 ? <div className="h2h-table" role="table" aria-label="历史交锋记录"><div className="h2h-row h2h-header" role="row"><span>日期</span><span>对阵</span><span>比分</span></div>{context.head_to_head.map((match) => <div className="h2h-row" role="row" key={`${match.date}-${match.home}-${match.away}`}><time>{match.date}</time><span>{match.home} <i>vs</i> {match.away}</span><ParsedScoreline score={match.score} /></div>)}</div> : <p className="data-empty">暂无历史交锋数据</p>}
      </div>}

      {sections.includes("availability") && <div className="detail-data-block">
        <div className="section-heading"><div><span>AVAILABILITY</span><h3>伤停影响</h3></div><small><HeartPulse size={13} /> {context.availability.home_missing + context.availability.away_missing} 人</small></div>
        {hasEvidence ? <div className="availability-grid"><div><strong>{fixture.home_team.name}</strong><span>{context.availability.home_missing} 人缺阵</span><ul className="absence-list">{homeInjuries.length > 0 ? homeInjuries.map((player) => <li key={`${player.name}-${player.reason}`}><b>{player.name}</b><small>{player.reason}</small></li>) : <li className="absence-empty">暂无已知伤停</li>}</ul></div><div><strong>{fixture.away_team.name}</strong><span>{context.availability.away_missing} 人缺阵</span><ul className="absence-list">{awayInjuries.length > 0 ? awayInjuries.map((player) => <li key={`${player.name}-${player.reason}`}><b>{player.name}</b><small>{player.reason}</small></li>) : <li className="absence-empty">暂无已知伤停</li>}</ul></div></div> : <p className="data-empty">请先同步这场比赛的伤停数据</p>}
      </div>}

      {sections.includes("lineup") && <div className="detail-data-block">
        <div className="section-heading"><div><span>LINEUPS</span><h3>球员名单</h3></div><small>{context.lineup.confirmed ? "已确认" : "未公布"}</small></div>
        {context.lineup.confirmed ? <div className="lineup-grid"><LineupColumn teamName={fixture.home_team.name} formation={context.lineup.home_formation} players={context.lineup.home_players} /><LineupColumn teamName={fixture.away_team.name} formation={context.lineup.away_formation} players={context.lineup.away_players} /></div> : <div className="lineup-pending"><Shirt size={18} /><div><strong>首发名单尚未发布</strong><p>比赛临近后再次同步，确认首发后会显示首发与替补球员。</p></div></div>}
      </div>}
    </section>
  );
}

export function ProbabilityPanel({ prediction, fixture, bet, onManualPredict, predicting = false }: { prediction: Prediction; fixture: Fixture; bet: SimulatedBet | null; onManualPredict?: () => void; predicting?: boolean }) {
  const headingId = `prediction-title-${prediction.id}`;
  const betMatchesPrediction = bet?.prediction_id === prediction.id;
  const options = [
    { key: "home", label: "主胜", team: fixture.home_team.name, value: prediction.probabilities.home },
    { key: "draw", label: "平局", team: "双方战平", value: prediction.probabilities.draw },
    { key: "away", label: "客胜", team: fixture.away_team.name, value: prediction.probabilities.away },
  ] as const;
  const best = options.reduce((left, right) => (left.value > right.value ? left : right));
  const aiHandicap = prediction.asian_handicap_assessment;
  const baselineHandicap = prediction.asian_handicap;
  const baselineSelection = baselineHandicap
    ? baselineHandicap.home_settlement.full_win + baselineHandicap.home_settlement.half_win
      >= baselineHandicap.home_settlement.full_loss + baselineHandicap.home_settlement.half_loss
      ? "home_handicap"
      : "away_handicap"
    : null;
  const handicapDisagreement = Boolean(
    aiHandicap?.available
    && aiHandicap.selection !== "none"
    && baselineHandicap
    && aiHandicap.selection !== baselineSelection,
  );
  return (
    <section className="prediction-panel" aria-labelledby={headingId}>
      <div className="prediction-header">
        <div>
          <span>{prediction.phase === "confirmed_lineup" ? "确认首发版" : "初步预测"}</span>
          <h3 id={headingId}>胜平负概率</h3>
        </div>
        <div className="prediction-actions">
          {prediction.phase === "preliminary" && fixture.status === "scheduled" && onManualPredict && <button className="manual-predict-button" type="button" title="基于当前已同步赛前数据重新生成初步预测" onClick={onManualPredict} disabled={predicting}>{predicting ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : <Play size={13} fill="currentColor" aria-hidden="true" />}{predicting ? "计算中" : "手动生成"}</button>}
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
          <div>
            <span>{prediction.ai.provider === "chatgpt" ? "CHATGPT ASSESSMENT" : "DEEPSEEK ASSESSMENT"}</span>
            <strong>{prediction.ai.status === "completed" ? prediction.analysis_summary : "AI 不可用，当前仅显示 Poisson 基线"}</strong>
            <small>{prediction.ai.status === "completed" ? `${prediction.ai.returned_model} · ${prediction.ai.prompt_version}` : prediction.ai.error}</small>
          </div>
          <dl>
            <div><dt>判断</dt><dd>{outcomeText(prediction.predicted_outcome)}</dd></div>
            <div><dt>市场</dt><dd>{marketText(prediction.recommendation?.market)}</dd></div>
            <div><dt>选择</dt><dd>{selectionText(prediction.recommendation?.selection)}</dd></div>
          </dl>
          {prediction.risk_factors?.length ? <ul>{prediction.risk_factors.map((risk) => <li key={risk}>{risk}</li>)}</ul> : null}
          {aiHandicap && <p className="ai-handicap-note">AI 亚洲盘观点：{aiHandicap.available && aiHandicap.selection !== "none" && aiHandicap.line !== null ? handicapSelection(aiHandicap.selection, aiHandicap.line, fixture.home_team.name, fixture.away_team.name) : "无可用盘口"} · {aiHandicap.reason}</p>}
          {prediction.evidence_hash && <code>证据 {prediction.evidence_hash.slice(0, 12)}</code>}
        </div>
      )}
      <div className="prediction-facts">
        <span><Goal size={16} />预期进球 {prediction.expected_goals.home} : {prediction.expected_goals.away}</span>
        <span><Gauge size={16} />证据置信度 {prediction.confidence}</span>
        <span><Clock3 size={16} />生成于 {formatTimestamp(prediction.created_at)}</span>
      </div>
      {prediction.recommendation?.market === "no_bet" && (
        <div className="simulated-position no-position"><span>本次模型建议</span><strong>本场不下注</strong><small>{prediction.recommendation.reason}</small></div>
      )}
      {bet && (
        <div className={`simulated-position${betMatchesPrediction ? "" : " historical-position"}`}>
          <span>{betMatchesPrediction ? "本次模拟仓位" : "历史版本持仓"}</span>
          <strong>{selectionText(bet.selection)} · {bet.odds.toFixed(2)}</strong>
          <small>{betMatchesPrediction ? "" : "早期预测已经执行，当前建议不会追溯撤单 · "}金额 {bet.stake.toFixed(2)} · {bet.status === "placed" ? "未结算" : `${bet.settlement_result ?? "已结算"} · 盈亏 ${bet.net_profit?.toFixed(2) ?? "-"}`}</small>
        </div>
      )}
      {prediction.asian_handicap && (
        <div className="handicap-block">
          <div><span>市场盘口（博彩公司）</span><strong>{handicapDirection(prediction.asian_handicap.line, fixture.home_team.name, fixture.away_team.name)}</strong><small>Poisson 基线倾向：{handicapRecommendation(prediction.asian_handicap.home_settlement, prediction.asian_handicap.line, fixture.home_team.name, fixture.away_team.name)}</small></div>
          {Object.entries(prediction.asian_handicap.home_settlement).map(([key, value]) => (
            <span key={key}><small>{settlementLabels[key as keyof typeof settlementLabels]}</small><b>{percent(value)}</b></span>
          ))}
        </div>
      )}
      {handicapDisagreement && <p className="handicap-disagreement">AI 亚洲盘观点与 Poisson 基线倾向相反；当前正式建议为“{marketText(prediction.recommendation?.market)}”，不据此执行模拟下注。</p>}
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
        <div className="section-heading">
          <div><span>PRE-MATCH MARKET</span><h3 id="market-title">赛前赔率快照</h3></div>
          <small>{context.odds ? `${context.odds.bookmaker} · ${formatTimestamp(context.odds.updated_at)}` : "暂无"}</small>
        </div>
        {context.odds ? (
          <>
            <div className="odds-row">
              <span><small>主胜</small><b>{context.odds.home.toFixed(2)}</b></span>
              <span><small>平局</small><b>{context.odds.draw.toFixed(2)}</b></span>
              <span><small>客胜</small><b>{context.odds.away.toFixed(2)}</b></span>
              {context.odds.asian_handicap !== null && <>
                <span><small>{handicapMarketLabel(context.odds.asian_handicap, "home")}</small><b>{context.odds.asian_handicap_home_odd?.toFixed(2) ?? "-"}</b></span>
                <span><small>{handicapMarketLabel(-context.odds.asian_handicap, "away")}</small><b>{context.odds.asian_handicap_away_odd?.toFixed(2) ?? "-"}</b></span>
              </>}
            </div>
            <p className="data-source-note">来源：API-Football / API-Sports 的赛前赔率接口；当前取返回结果中的第一家 bookmaker，记录同步时间。</p>
          </>
        ) : <p className="empty-note">这场比赛没有可用的赛前赔率，因此不会生成让球判断。</p>}
      </section>

      {detail.predictions && Object.values(detail.predictions).some(Boolean) ? <DualProbabilityPanels detail={detail} /> : prediction ? <ProbabilityPanel prediction={prediction} fixture={fixture} bet={detail.bet} /> : (
        <section className="no-prediction">
          <Database size={23} aria-hidden="true" />
          <div><h3>尚无已发布预测</h3><p>{realEvidencePending ? "真实赛程已经缓存；点击同步赛前数据后，系统会拉取近期状态、交锋、伤停和赔率。" : operatorMode ? "核对数据状态后，可手动发起这场比赛的首个预测。" : "证据同步完成后，系统会自动生成这场比赛的初步预测。"}</p></div>
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
          <small>两个模型独立判断，分别记录建议与仓位</small>
          {detail.fixture.status === "scheduled" && onManualPredict && <button className="manual-predict-button" type="button" title="使用当前赛前数据并行生成两个模型的预测" onClick={onManualPredict} disabled={predicting}>{predicting ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : <Play size={13} fill="currentColor" aria-hidden="true" />}{predicting ? "计算中" : "手动生成"}</button>}
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
            <strong className="model-tab-judgment">{outcomeText(prediction.predicted_outcome)}</strong>
            <span className={`model-tab-investment${prediction.recommendation?.market === "no_bet" ? " no-bet" : ""}`}>{prediction.recommendation?.market === "no_bet" ? "本次不下注" : selectionText(prediction.recommendation?.selection)}</span>
            <small className="model-tab-position">{detail.bets?.[key] ? `${detail.bets[key]?.prediction_id === prediction.id ? "本次仓位" : "历史持仓"} ${detail.bets[key]?.stake.toFixed(2)}` : "当前无持仓"}</small>
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
  return value ? ({ home: "主胜", draw: "平局", away: "客胜", home_handicap: "主队让球", away_handicap: "客队受让", none: "无" }[value] ?? value) : "-";
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
        <div className={`status-strip sync-${syncStatus}`} role="status">
          <span><i aria-hidden="true" />{dataMode === "demo" ? "演示数据模式" : syncLabel}</span>
          <span className="status-note">{lastSyncedAt ? `${scheduleProvider} · 更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : `${scheduleProvider} · 首次访问自动获取`}</span>
        </div>
        <section className="score-center-title">
          <div><span>FOOTBALL SCORES</span><h1>比赛中心</h1><p>中超、西甲与英超赛程、比分和赛前数据。</p></div>
          <div className="today-stamp"><CalendarDays size={19} aria-hidden="true" /><span><small>北京时间</small><strong>{new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" })}</strong></span></div>
        </section>
        <div className="score-center-filter">
          <div className="score-date-tabs" aria-label="日期范围">{dateTabs.map((tab) => <button key={tab.key} type="button" aria-pressed={dateFilter === tab.key} onClick={() => { setLoading(true); setDateFilter(tab.key); }} className={dateFilter === tab.key ? "active" : ""}>{tab.label}</button>)}</div>
          <div className="score-league-tabs" aria-label="联赛筛选">{leagueTabs.map((tab) => <button key={tab.key} type="button" aria-pressed={leagueFilter === tab.key} onClick={() => { setLoading(true); setLeagueFilter(tab.key); }} className={leagueFilter === tab.key ? "active" : ""}>{tab.label}{tab.key !== "all" && <small>{leagueCounts[tab.key] ?? 0}</small>}</button>)}</div>
        </div>
        {error && <div className="error-banner score-center-error" role="alert"><AlertTriangle size={18} aria-hidden="true" />{error}<button type="button" onClick={() => setError(null)} aria-label="关闭错误提示">×</button></div>}
        <ScoreCenterHome fixtures={fixtures} loading={loading} dataMode={dataMode} />
      </main>
    );
  }

  return (
    <main className="operator-page">
      <div className={`status-strip sync-${syncStatus}`}>
        <span><i />系统就绪</span>
        <span><Database size={14} />{dataMode === "demo" ? "演示数据模式" : syncLabel}</span>
        <span className="status-note">{lastSyncedAt ? `${scheduleProvider} · 更新于 ${formatPreciseTimestamp(lastSyncedAt)}` : `${scheduleProvider} · 首次访问自动获取`}</span>
        {operatorMode && <button className="sync-action" onClick={() => void syncFixtures()} disabled={syncing}>{syncing ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}{syncing ? "同步中" : "同步赛程"}</button>}
      </div>
      {syncMessage && <div className="sync-success" role="status" aria-live="polite"><Check size={16} />{syncMessage}</div>}
      <div className="workspace-title">
        <div>
          <span>{operatorMode ? "OPERATOR CONTROL" : "FIXTURE OPERATIONS"}</span>
          <h1>{operatorMode ? "预测操作台" : "赛程与赛前判断"}</h1>
          <p>{operatorMode ? "只对选中的比赛生成预测，每次运行保留独立版本。" : "浏览三个联赛的赛程，并查看管理员已发布的赛前概率。"}</p>
        </div>
        <div className="today-stamp"><CalendarDays size={19} /><span><small>北京时间</small><strong>{new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" })}</strong></span></div>
      </div>

      <div className="filter-band">
        <div className="segmented" aria-label="日期范围">
          {dateTabs.map((tab) => <button key={tab.key} aria-pressed={dateFilter === tab.key} onClick={() => { setLoading(true); setSuccess(null); setDateFilter(tab.key); }} className={dateFilter === tab.key ? "active" : ""}>{tab.label}</button>)}
        </div>
        <div className="league-filter" aria-label="联赛筛选">
          {leagueTabs.map((tab) => <button key={tab.key} aria-pressed={leagueFilter === tab.key} onClick={() => { setLoading(true); setSuccess(null); setLeagueFilter(tab.key); }} className={leagueFilter === tab.key ? "active" : ""}>{tab.label}{tab.key !== "all" && <small>{leagueCounts[tab.key] ?? 0}</small>}</button>)}
        </div>
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
