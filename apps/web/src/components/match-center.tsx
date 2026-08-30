"use client";

import { ArrowLeft, CalendarDays, CircleAlert, Clock3, LoaderCircle, MapPin, Play, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AnalysisSnapshot, DualProbabilityPanels, EvidenceDetails, PlayerImpactPanel, Scoreline, TeamLogo, TeamProfiles } from "@/components/fixture-workspace";
import { Tabs } from "@/components/ui";
import { fetchFixtureDetail } from "@/lib/api";
import { formatHandicapSide } from "@/lib/handicap";
import type { FixtureDetail } from "@/lib/types";

type MatchTab = "overview" | "analysis" | "h2h" | "squads" | "odds";

const tabs: Array<{ key: MatchTab; label: string }> = [
  { key: "overview", label: "概览" },
  { key: "analysis", label: "AI 分析" },
  { key: "h2h", label: "交锋" },
  { key: "squads", label: "阵容" },
  { key: "odds", label: "赔率" },
];

function formatKickoff(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
}

function kickoffHasStarted(detail: FixtureDetail) {
  const kickoff = new Date(detail.fixture.kickoff).getTime();
  return Number.isFinite(kickoff) && kickoff <= Date.now();
}

function fixtureState(detail: FixtureDetail) {
  const { fixture } = detail;
  if (fixture.status === "finished") return "完场";
  if (fixture.status === "live") return "进行中";
  if (fixture.status === "postponed") return "延期";
  if (fixture.status === "cancelled") return "取消";
  return fixture.lineup_confirmed ? "首发已确认" : "未开始";
}

function MatchHeader({ detail }: { detail: FixtureDetail }) {
  const { fixture, context } = detail;
  const outcome = fixture.score
    ? fixture.score.home > fixture.score.away ? "主胜" : fixture.score.home < fixture.score.away ? "客胜" : "平局"
    : null;
  return (
    <header className="match-center-header">
      <div className="match-breadcrumb"><Link href="/"><ArrowLeft size={15} aria-hidden="true" />全部比赛</Link><span>{fixture.league.name}</span><span>{fixtureState(detail)}</span></div>
      <div className="match-center-scoreboard">
        <div className="match-side home"><TeamLogo profile={context.teams.home ?? {}} team={fixture.home_team} tone="home" /><strong>{fixture.home_team.name}</strong><small>主队</small></div>
        <div className="match-score">
          <span className={`match-state ${fixture.status}`}>{fixtureState(detail)}</span>
          {fixture.score ? <Scoreline home={fixture.score.home} away={fixture.score.away} large /> : <strong>{new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(fixture.kickoff))}</strong>}
          <small>{outcome ?? "北京时间"}</small>
        </div>
        <div className="match-side away"><TeamLogo profile={context.teams.away ?? {}} team={fixture.away_team} tone="away" /><strong>{fixture.away_team.name}</strong><small>客队</small></div>
      </div>
      <div className="match-meta"><span><CalendarDays size={14} aria-hidden="true" />{formatKickoff(fixture.kickoff)}</span><span><MapPin size={14} aria-hidden="true" />{fixture.venue}</span><span><ShieldCheck size={14} aria-hidden="true" />{context.synced_at ? "赛前数据已同步" : "赛前数据待同步"}</span></div>
    </header>
  );
}

function MatchOverview({ detail, onManualPredict, predicting }: { detail: FixtureDetail; onManualPredict: () => void; predicting: boolean }) {
  const { context, prediction } = detail;
  const readiness = [
    ["近期状态", context.recent_form.home.length > 0 && context.recent_form.away.length > 0],
    ["历史交锋", context.head_to_head.length > 0],
    ["伤停", Boolean(context.availability.updated_at)],
    ["首发", context.lineup.confirmed],
    ["赔率", Boolean(context.odds)],
  ];
  return <>
    <section className="match-overview-strip" aria-label="比赛数据状态">
      <div><span>数据就绪</span><strong>{readiness.filter(([, ready]) => ready).length} / {readiness.length}</strong></div>
      <div><span>近期战绩</span><strong>{Math.max(context.recent_form.home.length, context.recent_form.away.length)} 场</strong></div>
      <div><span>伤停</span><strong>{context.availability.home_missing + context.availability.away_missing} 人</strong></div>
      <div><span>首发</span><strong>{context.lineup.confirmed ? "已确认" : "待发布"}</strong></div>
      <div><span>赔率</span><strong>{context.odds ? "已获取" : "待同步"}</strong></div>
      <div><span>预测</span><strong>{prediction ? "已生成" : "待生成"}</strong></div>
    </section>
    <div className="match-tab-stack">
      <AnalysisSnapshot detail={detail} />
      <PlayerImpactPanel detail={detail} />
      {Object.values(detail.predictions ?? {}).some(Boolean) ? <DualProbabilityPanels detail={detail} onManualPredict={onManualPredict} predicting={predicting} /> : <ManualPredictionEmpty detail={detail} onManualPredict={onManualPredict} predicting={predicting} />}
    </div>
  </>;
}

function ManualPredictionEmpty({ detail, onManualPredict, predicting }: { detail: FixtureDetail; onManualPredict: () => void; predicting: boolean }) {
  const messages = {
    finished: ["比赛已结束，不能重新预测", "系统只生成赛前预测，避免赛果和赛后数据影响模型判断。"],
    live: ["比赛进行中，不能生成赛前预测", "比赛开赛后将保留既有赛前判断，不再补生成预测。"],
    postponed: ["比赛已延期，等待新赛程后再预测", "新开球时间同步后，系统会重新开放赛前预测。"],
    cancelled: ["比赛已取消，不能生成预测", "已取消比赛不会进入预测和模拟下注流程。"],
  } as const;
  const blocked = kickoffHasStarted(detail)
    ? ["比赛已开球，不能生成赛前预测", "系统只生成赛前预测，避免赛果和赛后数据影响模型判断。"]
    : messages[detail.fixture.status as keyof typeof messages];
  return <section className="match-empty manual-prediction-empty">
    <Clock3 size={20} aria-hidden="true" />
    <div>
      <strong>{blocked?.[0] ?? "暂无当前版本预测"}</strong>
      <p>{blocked?.[1] ?? "赛前证据已就绪后，可手动生成 DeepSeek 与 ChatGPT 的当前版本判断。"}</p>
      {!blocked && detail.fixture.status === "scheduled" && <button className="manual-predict-button" type="button" title="使用当前赛前数据并行生成两个模型的预测" onClick={onManualPredict} disabled={predicting}>{predicting ? <LoaderCircle className="spin" size={13} aria-hidden="true" /> : <Play size={13} fill="currentColor" aria-hidden="true" />}{predicting ? "计算中" : "手动生成预测"}</button>}
    </div>
  </section>;
}

function MatchOdds({ detail }: { detail: FixtureDetail }) {
  const odds = detail.context.odds;
  if (!odds) return <section className="match-empty"><CircleAlert size={20} aria-hidden="true" /><div><strong>暂无可用赛前赔率</strong><p>系统不会用估算赔率替代缺失的市场数据。</p></div></section>;
  const handicap = odds.asian_handicap;
  return <section className="market-board" aria-label="赛前赔率">
    <div className="market-board-heading"><div><span>PRE-MATCH MARKET</span><h2>赛前赔率</h2></div><small>{odds.bookmaker} · {new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(odds.updated_at))}</small></div>
    <div className="market-grid">
      <div><span>主胜</span><strong>{odds.home.toFixed(2)}</strong></div><div><span>平局</span><strong>{odds.draw.toFixed(2)}</strong></div><div><span>客胜</span><strong>{odds.away.toFixed(2)}</strong></div>
      {handicap !== null && <><div><span>{formatHandicapSide(handicap, "home")}</span><strong>{odds.asian_handicap_home_odd?.toFixed(2) ?? "-"}</strong></div><div><span>{formatHandicapSide(handicap, "away")}</span><strong>{odds.asian_handicap_away_odd?.toFixed(2) ?? "-"}</strong></div></>}
    </div>
  </section>;
}

export function MatchCenter({ fixtureId }: { fixtureId: string }) {
  const [detail, setDetail] = useState<FixtureDetail | null>(null);
  const [activeTab, setActiveTab] = useState<MatchTab>("overview");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [predicting, setPredicting] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchFixtureDetail(fixtureId)
      .then((response) => { if (active) setDetail(response); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "比赛详情加载失败"); });
    return () => { active = false; };
  }, [fixtureId]);

  async function runManualPrediction() {
    if (!detail) return;
    setPredicting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = await fetch("/api/admin/predict", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fixtureId: detail.fixture.id }),
      });
      const payload = await response.json() as { detail?: string; prediction?: { id?: string } };
      if (!response.ok) throw new Error(payload.detail ?? "手动预测失败");
      setDetail(await fetchFixtureDetail(detail.fixture.id));
      setActionMessage(`已并行生成双模型预测 ${payload.prediction?.id?.slice(0, 8) ?? ""}`.trim());
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "手动预测失败");
    } finally {
      setPredicting(false);
    }
  }

  if (error) return <main className="match-center-page"><section className="match-empty"><CircleAlert size={20} aria-hidden="true" /><div><strong>比赛详情暂不可用</strong><p>{error}</p></div></section></main>;
  if (!detail) return <main className="match-center-page"><div className="match-loading"><LoaderCircle className="spin" size={20} aria-hidden="true" />正在加载比赛中心</div></main>;

  return <main className="match-center-page">
    <MatchHeader detail={detail} />
    <Tabs
      className="match-tabs"
      ariaLabel="比赛详情页签"
      value={activeTab}
      onChange={setActiveTab}
      items={tabs.map((tab) => ({ value: tab.key, label: tab.label }))}
    />
    <div className="match-content">
      {actionError && <div className="match-action-message error" role="alert"><CircleAlert size={15} aria-hidden="true" />{actionError}</div>}
      {actionMessage && <div className="match-action-message success" role="status"><ShieldCheck size={15} aria-hidden="true" />{actionMessage}</div>}
      {activeTab === "overview" && <MatchOverview detail={detail} onManualPredict={runManualPrediction} predicting={predicting} />}
      {activeTab === "analysis" && <div className="match-tab-stack"><EvidenceDetails detail={detail} sections={["form", "availability"]} /><PlayerImpactPanel detail={detail} />{Object.values(detail.predictions ?? {}).some(Boolean) ? <DualProbabilityPanels detail={detail} onManualPredict={runManualPrediction} predicting={predicting} /> : <ManualPredictionEmpty detail={detail} onManualPredict={runManualPrediction} predicting={predicting} />}</div>}
      {activeTab === "h2h" && <div className="match-tab-stack"><EvidenceDetails detail={detail} sections={["h2h"]} /></div>}
      {activeTab === "squads" && <div className="match-tab-stack"><EvidenceDetails detail={detail} sections={["lineup"]} /><TeamProfiles detail={detail} /></div>}
      {activeTab === "odds" && <MatchOdds detail={detail} />}
    </div>
  </main>;
}
