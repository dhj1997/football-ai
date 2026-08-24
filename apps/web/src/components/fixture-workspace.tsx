"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarDays,
  Check,
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
  Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { fetchFixtureDetail, fetchFixtures } from "@/lib/api";
import type { DateFilter, Fixture, FixtureDetail, LeagueFilter, Prediction } from "@/lib/types";

type DataMode = "cached" | "demo" | "empty" | "unconfigured";

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

function TeamMark({ team, tone }: { team: Fixture["home_team"]; tone: "home" | "away" }) {
  return <span className={`team-mark ${tone}`} aria-hidden="true">{team.code.slice(0, 3)}</span>;
}

function FixtureRow({ fixture, selected, onSelect }: { fixture: Fixture; selected: boolean; onSelect: () => void }) {
  const statusText = {
    scheduled: fixture.lineup_confirmed ? "首发已确认" : "等待首发",
    finished: "完场",
    postponed: "延期",
    cancelled: "取消",
    live: "进行中",
  }[fixture.status];
  return (
    <button className={`fixture-row ${selected ? "selected" : ""}`} onClick={onSelect} aria-pressed={selected}>
      <span className="fixture-time">
        <strong>{fixture.status === "finished" ? "完场" : formatKickoff(fixture.kickoff)}</strong>
        <small>{fixture.league.name}</small>
      </span>
      <span className="fixture-teams">
        <span><TeamMark team={fixture.home_team} tone="home" /><b>{fixture.home_team.name}</b></span>
        <span><TeamMark team={fixture.away_team} tone="away" /><b>{fixture.away_team.name}</b></span>
      </span>
      <span className="fixture-state">
        {fixture.score ? <strong>{fixture.score.home} : {fixture.score.away}</strong> : <em className={fixture.lineup_confirmed ? "state-ready" : ""}>{statusText}</em>}
        <ChevronRight size={18} aria-hidden="true" />
      </span>
    </button>
  );
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

function ProbabilityPanel({ prediction, fixture }: { prediction: Prediction; fixture: Fixture }) {
  const options = [
    { key: "home", label: "主胜", team: fixture.home_team.name, value: prediction.probabilities.home },
    { key: "draw", label: "平局", team: "双方战平", value: prediction.probabilities.draw },
    { key: "away", label: "客胜", team: fixture.away_team.name, value: prediction.probabilities.away },
  ] as const;
  const best = options.reduce((left, right) => (left.value > right.value ? left : right));
  return (
    <section className="prediction-panel" aria-labelledby="prediction-title">
      <div className="prediction-header">
        <div>
          <span>{prediction.phase === "confirmed_lineup" ? "确认首发版" : "初步预测"}</span>
          <h3 id="prediction-title">胜平负概率</h3>
        </div>
        <span className="model-tag">{prediction.model_version}</span>
      </div>
      <div className="probability-grid">
        {options.map((item) => (
          <div className={item.key === best.key ? "probability winner" : "probability"} key={item.key}>
            <span>{item.label}</span><strong>{percent(item.value)}</strong><small>{item.team}</small>
            <i style={{ "--probability": percent(item.value) } as React.CSSProperties} />
          </div>
        ))}
      </div>
      <div className="prediction-facts">
        <span><Goal size={16} />预期进球 {prediction.expected_goals.home} : {prediction.expected_goals.away}</span>
        <span><Gauge size={16} />证据置信度 {prediction.confidence}</span>
        <span><Clock3 size={16} />生成于 {formatTimestamp(prediction.created_at)}</span>
      </div>
      {prediction.asian_handicap && (
        <div className="handicap-block">
          <div><span>亚洲让球 · 主队</span><strong>{prediction.asian_handicap.line > 0 ? "+" : ""}{prediction.asian_handicap.line}</strong></div>
          {Object.entries(prediction.asian_handicap.home_settlement).map(([key, value]) => (
            <span key={key}><small>{settlementLabels[key as keyof typeof settlementLabels]}</small><b>{percent(value)}</b></span>
          ))}
        </div>
      )}
      <p className="disclaimer">概率是模型对赛前信息的量化结果，不代表确定赛果，也不构成投注建议。</p>
    </section>
  );
}

function DetailPanel({ detail, operatorMode, running, success, actionRef, onPredict }: { detail: FixtureDetail; operatorMode: boolean; running: boolean; success: Prediction | null; actionRef: React.RefObject<HTMLButtonElement | null>; onPredict: () => void }) {
  const { fixture, context, prediction } = detail;
  const realEvidencePending = !fixture.is_demo;
  return (
    <aside className="detail-panel">
      <div className="match-summary">
        <div className="detail-kicker"><span>{fixture.league.name}</span><span>{fixture.is_demo ? "演示数据" : "提供商数据"}</span></div>
        <div className="match-teams">
          <div><TeamMark team={fixture.home_team} tone="home" /><strong>{fixture.home_team.name}</strong><small>主队</small></div>
          <span className="versus">VS<small>{formatKickoff(fixture.kickoff)}</small></span>
          <div><TeamMark team={fixture.away_team} tone="away" /><strong>{fixture.away_team.name}</strong><small>客队</small></div>
        </div>
        <p><CalendarDays size={15} /> {new Date(fixture.kickoff).toLocaleDateString("zh-CN")} · {fixture.venue}</p>
      </div>

      {operatorMode && fixture.status !== "finished" && (
        <div className="operator-actions">
          <div><strong>{realEvidencePending ? "真实赛前证据尚未同步" : prediction ? "生成新预测版本" : "这场比赛尚未预测"}</strong><small>{realEvidencePending ? "当前只完成真实赛程，暂不使用演示证据生成判断" : context.lineup.confirmed ? "确认首发已纳入，可以生成最终赛前版" : "首发未确认，将生成初步预测"}</small></div>
          <button className="icon-button secondary" title={realEvidencePending ? "近期状态、阵容和赔率同步将在下一阶段接入" : "演示数据无需刷新"} aria-label="刷新比赛上下文" disabled><RefreshCw size={18} /></button>
          <button ref={actionRef} className="primary-action" onClick={onPredict} disabled={running || realEvidencePending} aria-describedby={success ? "prediction-success" : undefined}>
            {running ? <LoaderCircle className="spin" size={18} /> : <Play size={18} fill="currentColor" />}
            {running ? "计算中" : realEvidencePending ? "等待证据" : "发起预测"}
          </button>
        </div>
      )}

      {operatorMode && success && (
        <div className="prediction-success" id="prediction-success" role="status" aria-live="polite">
          <Check size={17} aria-hidden="true" />
          <span><strong>预测版本已保存</strong><small>版本 {success.id.slice(0, 8)} · {formatPreciseTimestamp(success.created_at)}</small></span>
        </div>
      )}

      <EvidenceRail detail={detail} />

      <section className="market-section" aria-labelledby="market-title">
        <div className="section-heading">
          <div><span>PRE-MATCH MARKET</span><h3 id="market-title">赛前赔率快照</h3></div>
          <small>{context.odds ? formatTimestamp(context.odds.updated_at) : "暂无"}</small>
        </div>
        {context.odds ? (
          <div className="odds-row">
            <span><small>主胜</small><b>{context.odds.home.toFixed(2)}</b></span>
            <span><small>平局</small><b>{context.odds.draw.toFixed(2)}</b></span>
            <span><small>客胜</small><b>{context.odds.away.toFixed(2)}</b></span>
            <span><small>主队让球</small><b>{context.odds.asian_handicap}</b></span>
          </div>
        ) : <p className="empty-note">这场比赛没有可用的赛前赔率，因此不会生成让球判断。</p>}
      </section>

      {prediction ? <ProbabilityPanel prediction={prediction} fixture={fixture} /> : (
        <section className="no-prediction">
          <Database size={23} aria-hidden="true" />
          <div><h3>尚无已发布预测</h3><p>{realEvidencePending ? "真实赛程已经缓存；近期状态、阵容和赔率同步完成后才能生成预测。" : operatorMode ? "核对数据状态后，可手动发起这场比赛的首个预测。" : "比赛会正常显示，但只有管理员选中的比赛才会出现预测。"}</p></div>
        </section>
      )}
    </aside>
  );
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
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
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
        setLastSyncedAt(response.last_synced_at);
        setSelectedId((current) => response.items.some((item) => item.id === current) ? current : response.items[0]?.id ?? null);
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
  }, [dateFilter, leagueFilter, reloadToken]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    void fetchFixtureDetail(selectedId)
      .then((response) => { if (active) setDetail(response); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "比赛详情加载失败"); });
    return () => { active = false; };
  }, [selectedId]);

  const leagueCounts = useMemo(() => fixtures.reduce<Record<string, number>>((counts, fixture) => {
    counts[fixture.league_key] = (counts[fixture.league_key] ?? 0) + 1;
    return counts;
  }, {}), [fixtures]);

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
      const payload = await response.json() as Prediction & { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "预测运行失败");
      setSuccess(payload);
      setDetail(await fetchFixtureDetail(selectedId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "预测运行失败");
    } finally {
      setRunning(false);
      window.requestAnimationFrame(() => actionRef.current?.focus());
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

  const modeLabel = {
    cached: "真实赛程缓存",
    demo: "演示数据模式",
    empty: "等待首次同步",
    unconfigured: "未配置 API 密钥",
  }[dataMode];

  return (
    <main>
      <div className="status-strip">
        <span><i />系统就绪</span>
        <span><Database size={14} />{modeLabel}</span>
        <span className="status-note">{lastSyncedAt ? `最后同步 ${formatPreciseTimestamp(lastSyncedAt)}` : "公开页只读取本地缓存，不消耗上游额度"}</span>
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
          )) : <div className="loading-state"><CalendarDays />{dataMode === "unconfigured" ? "请在 API 服务中配置免费赛程数据源" : dataMode === "empty" ? "请在操作台执行首次赛程同步" : "当前筛选下没有比赛"}</div>}
        </section>
        {detail && selectedId === detail.fixture.id ? <DetailPanel detail={detail} operatorMode={operatorMode} running={running} success={success} actionRef={actionRef} onPredict={() => void runPrediction()} /> : selectedId ? (
          <aside className="detail-panel detail-loading"><LoaderCircle className="spin" />读取比赛证据</aside>
        ) : <aside className="detail-panel detail-loading"><Database />同步真实赛程后可查看比赛详情</aside>}
      </div>
    </main>
  );
}
