"use client";

import { Filter, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { DataFreshness, EmptyState, ErrorState, LoadingState, PageHeader, SectionHeader, StatCard, StatusBadge, Tabs } from "@/components/ui";
import { fetchBankroll, fetchBets, fetchPredictionMetrics } from "@/lib/api";
import type { BankrollSummary, LeagueFilter, ModelKey, PredictionMetrics, SimulatedBet } from "@/lib/types";

const leagues: Array<{ key: LeagueFilter; label: string }> = [
  { key: "all", label: "全部" }, { key: "epl", label: "英超" }, { key: "laliga", label: "西甲" }, { key: "csl", label: "中超" },
];

export function PerformanceDashboard() {
  const [bankroll, setBankroll] = useState<BankrollSummary | null>(null);
  const [bets, setBets] = useState<SimulatedBet[]>([]);
  const [metrics, setMetrics] = useState<PredictionMetrics | null>(null);
  const [selectedModel, setSelectedModel] = useState<ModelKey>("deepseek");
  const [filters, setFilters] = useState({ league: "all" as LeagueFilter, season: "", startDate: "", endDate: "", modelVersion: "" });
  const [draft, setDraft] = useState(filters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = metricQuery(filters);
      const [summary, betData, metricData] = await Promise.all([
        fetchBankroll(), fetchBets(selectedModel), fetchPredictionMetrics(query, selectedModel),
      ]);
      setBankroll(summary); setBets(betData.items); setMetrics(metricData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "绩效数据请求失败");
    } finally {
      setLoading(false);
    }
  }, [filters, selectedModel]);

  useEffect(() => {
    let active = true;
    const query = metricQuery(filters);
    void Promise.all([fetchBankroll(), fetchBets(selectedModel), fetchPredictionMetrics(query, selectedModel)])
      .then(([summary, betData, metricData]) => {
        if (!active) return;
        setBankroll(summary); setBets(betData.items); setMetrics(metricData);
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "绩效数据请求失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, selectedModel]);

  const visibleBets = useMemo(() => bets.filter((bet) => {
    if (filters.league !== "all" && bet.league_key !== filters.league) return false;
    if (filters.startDate && bet.fixture_date < filters.startDate) return false;
    if (filters.endDate && bet.fixture_date > filters.endDate) return false;
    if (filters.modelVersion && bet.model_version !== filters.modelVersion) return false;
    return true;
  }), [bets, filters]);

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setFilters(draft);
  }

  return (
    <main className="performance-page">
      <DataFreshness
        className="status-strip"
        status="fresh"
        label="仅模拟资金 · 不连接真实投注平台"
        source="初始资金 1000 · 结算后自动更新"
        action={<button className="sync-action" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={13} className={loading ? "spin" : ""} />刷新</button>}
      />
      <PageHeader className="workspace-title" eyebrow="MODEL PERFORMANCE" title="模拟资金与预测绩效" description="逐笔追踪下注、结算、盈利与概率质量。" />
      <Tabs
        className="performance-filter"
        ariaLabel="绩效联赛筛选"
        value={draft.league}
        onChange={(league) => setDraft((current) => ({ ...current, league }))}
        items={leagues.map((item) => ({ value: item.key, label: item.label }))}
      />
      <form className="metric-filter-row" onSubmit={applyFilters}>
        <label><span>赛季</span><input value={draft.season} onChange={(event) => setDraft((current) => ({ ...current, season: event.target.value }))} placeholder="2026-27" /></label>
        <label><span>开始日期</span><input type="date" value={draft.startDate} onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))} /></label>
        <label><span>结束日期</span><input type="date" value={draft.endDate} onChange={(event) => setDraft((current) => ({ ...current, endDate: event.target.value }))} /></label>
        <label className="model-filter"><span>模型版本</span><input value={draft.modelVersion} onChange={(event) => setDraft((current) => ({ ...current, modelVersion: event.target.value }))} placeholder="deepseek:deepseek-v4-flash" /></label>
        <button type="submit"><Filter size={14} aria-hidden="true" />应用</button>
      </form>
      {error && <ErrorState className="error-banner performance-error">{error}</ErrorState>}
      {loading && !bankroll ? <LoadingState className="team-loading">正在读取模拟账本</LoadingState> : bankroll && metrics ? (
        <>
          <Tabs
            className="model-performance-tabs"
            ariaLabel="选择模型资金账户"
            value={selectedModel}
            onChange={setSelectedModel}
            items={(["deepseek", "chatgpt"] as ModelKey[]).map((key) => ({ value: key, label: key === "deepseek" ? "DeepSeek" : "GPT-5.6 Sol" }))}
          />
          <SummaryStrip bankroll={bankroll.accounts?.[selectedModel] ?? bankroll} metrics={metrics} />
          <ModelComparisonStrip bankroll={bankroll} />
          <AsianOutcomeStrip metrics={metrics} />
          <EquityCurve points={(bankroll.accounts?.[selectedModel] ?? bankroll).equity_curve} />
          <BetHistory bets={visibleBets} />
          <SettlementHistory metrics={metrics} />
        </>
      ) : null}
    </main>
  );
}

function ModelComparisonStrip({ bankroll }: { bankroll: BankrollSummary }) {
  const accounts: Partial<Record<ModelKey, BankrollSummary>> = bankroll.accounts ?? {};
  return <section className="model-comparison-strip" aria-label="双模型资金对比">
    {(["deepseek", "chatgpt"] as ModelKey[]).map((key) => {
      const account = accounts[key];
      return <div key={key}><span>{key === "deepseek" ? "DeepSeek" : "GPT-5.6 Sol"}</span><strong>{account ? account.equity.toFixed(2) : "-"}</strong><small>{account ? `盈利 ${signedMoney(account.net_profit)} · ROI ${percent(account.roi)}` : "尚未开始"}</small></div>;
    })}
  </section>;
}

function AsianOutcomeStrip({ metrics }: { metrics: PredictionMetrics }) {
  const labels: Array<[keyof PredictionMetrics["asian_handicap_results"], string]> = [
    ["full_win", "全赢"], ["half_win", "半赢"], ["push", "走水"], ["half_loss", "半输"], ["full_loss", "全输"],
  ];
  return <section className="asian-outcome-strip" aria-label="亚洲盘结算分类"><span>亚洲盘结算</span>{labels.map(([key, label]) => <div key={key}><small>{label}</small><strong>{metrics.asian_handicap_results[key]}</strong></div>)}</section>;
}

function SummaryStrip({ bankroll, metrics }: { bankroll: BankrollSummary; metrics: PredictionMetrics }) {
  const facts = [
    ["账户权益", bankroll.equity.toFixed(2)], ["可用现金", bankroll.balance.toFixed(2)],
    ["已实现利润", signedMoney(bankroll.net_profit)], ["未结敞口", bankroll.open_exposure.toFixed(2)],
    ["ROI", percent(bankroll.roi)], ["命中率", percent(metrics.accuracy)],
    ["Brier", metrics.average_brier_score?.toFixed(3) ?? "-"], ["数据完整度", metrics.average_data_completeness === null ? "-" : percent(metrics.average_data_completeness)],
    ["最大回撤", percent(bankroll.max_drawdown)],
  ];
  return <section className="performance-summary" aria-label="绩效摘要">{facts.map(([label, value]) => <StatCard key={label} label={label} value={value} valueClassName={label === "已实现利润" ? bankroll.net_profit >= 0 ? "positive" : "negative" : undefined} />)}</section>;
}

function EquityCurve({ points }: { points: BankrollSummary["equity_curve"] }) {
  const width = 900; const height = 160; const padding = 18;
  const values = points.length ? points.map((point) => point.balance) : [1000];
  const minimum = Math.min(...values); const maximum = Math.max(...values);
  const spread = maximum - minimum || 20;
  const coordinates = values.map((value, index) => {
    const x = padding + (values.length === 1 ? (width - padding * 2) / 2 : index * (width - padding * 2) / (values.length - 1));
    const y = height - padding - ((value - minimum + (maximum === minimum ? 10 : 0)) / spread) * (height - padding * 2);
    return { x, y };
  });
  return <section className="performance-section equity-curve-section"><SectionHeader className="team-section-heading" eyebrow="BANKROLL CURVE" title="已实现权益曲线" meta={`${points.length} 个节点`} /><div className="equity-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="模拟资金已实现权益曲线" preserveAspectRatio="none"><line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} /><polyline points={coordinates.map((point) => `${point.x},${point.y}`).join(" ")} />{coordinates.map((point, index) => <circle key={`${point.x}-${index}`} cx={point.x} cy={point.y} r="4" />)}</svg><span>{minimum.toFixed(2)}</span><strong>{values.at(-1)?.toFixed(2)}</strong></div></section>;
}

function BetHistory({ bets }: { bets: SimulatedBet[] }) {
  return <section className="performance-section"><SectionHeader className="team-section-heading" eyebrow="SIMULATED LEDGER" title="模拟下注明细" meta={`${bets.length} 笔`} />{bets.length ? <div className="team-table-scroll"><table className="performance-table bet-ledger"><thead><tr><th>比赛</th><th>市场</th><th>选择</th><th>赔率</th><th>金额</th><th>状态</th><th>盈亏</th><th>时间</th></tr></thead><tbody>{bets.map((bet) => <tr key={bet.id}><th scope="row"><b>{bet.home_team} vs {bet.away_team}</b><small>{bet.league_key.toUpperCase()} · {bet.fixture_date}</small></th><td>{bet.market === "1x2" ? "胜平负" : "亚洲盘"}</td><td>{selectionLabel(bet.selection, bet.handicap_line)}</td><td>{bet.odds.toFixed(2)}</td><td>{bet.stake.toFixed(2)}</td><td><StatusBadge className={`ledger-status ${bet.status}`} variant={bet.status === "placed" ? "partial" : "ready"}>{bet.status === "placed" ? "未结" : settlementLabel(bet.settlement_result)}</StatusBadge></td><td className={(bet.net_profit ?? 0) > 0 ? "positive" : (bet.net_profit ?? 0) < 0 ? "negative" : undefined}>{bet.net_profit === null ? "-" : signedMoney(bet.net_profit)}</td><td>{formatDate(bet.placed_at)}</td></tr>)}</tbody></table></div> : <EmptyState className="performance-empty">尚无符合规则的模拟下注</EmptyState>}</section>;
}

function SettlementHistory({ metrics }: { metrics: PredictionMetrics }) {
  return <section className="performance-section"><SectionHeader className="team-section-heading" eyebrow="PREDICTION EVALUATION" title="预测结算记录" meta={`${metrics.sample_size} 个样本`} />{metrics.items.length ? <div className="team-table-scroll"><table className="performance-table settlement-ledger"><thead><tr><th>日期</th><th>联赛</th><th>赛季</th><th>预测</th><th>实际</th><th>比分</th><th>正确</th><th>Brier</th><th>完整度</th><th>模型</th></tr></thead><tbody>{metrics.items.map((item) => <tr key={item.id}><td>{item.fixture_date}</td><td>{item.league_key.toUpperCase()}</td><td>{item.season}</td><td>{outcomeLabel(item.predicted_outcome)}</td><td>{outcomeLabel(item.actual_outcome)}</td><td>{item.score.home} : {item.score.away}</td><td><StatusBadge className={item.correct ? "result-correct" : "result-wrong"} variant={item.correct ? "ready" : "danger"}>{item.correct ? "命中" : "未中"}</StatusBadge></td><td>{item.brier_score.toFixed(3)}</td><td>{item.data_completeness === null ? "-" : percent(item.data_completeness)}</td><td>{item.model_version}</td></tr>)}</tbody></table></div> : <EmptyState className="performance-empty">比赛结束并完成结算后显示预测样本</EmptyState>}</section>;
}

function percent(value: number) { return `${(value * 100).toFixed(1)}%`; }
function signedMoney(value: number) { return `${value > 0 ? "+" : ""}${value.toFixed(2)}`; }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
function outcomeLabel(value: string) { return { home: "主胜", draw: "平", away: "客胜" }[value] ?? value; }
function settlementLabel(value: SimulatedBet["settlement_result"]) { return value ? { full_win: "全赢", half_win: "半赢", push: "走水", half_loss: "半输", full_loss: "全输" }[value] : "已结"; }
function selectionLabel(value: string, line: number | null) { return `${{ home: "主胜", draw: "平", away: "客胜", home_handicap: "主队", away_handicap: "客队" }[value] ?? value}${line !== null && value.includes("handicap") ? ` ${line > 0 ? "+" : ""}${value === "away_handicap" ? -line : line}` : ""}`; }

function metricQuery(filters: { league: LeagueFilter; season: string; startDate: string; endDate: string; modelVersion: string }) {
  const parameters = new URLSearchParams();
  if (filters.league !== "all") parameters.set("league", filters.league);
  if (filters.season) parameters.set("season", filters.season);
  if (filters.startDate) parameters.set("start_date", filters.startDate);
  if (filters.endDate) parameters.set("end_date", filters.endDate);
  if (filters.modelVersion) parameters.set("model_version", filters.modelVersion);
  return parameters.toString();
}
