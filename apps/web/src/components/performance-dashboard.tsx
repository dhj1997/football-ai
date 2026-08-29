"use client";

import { Filter, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { DataFreshness, EmptyState, ErrorState, LoadingState, PageHeader, SectionHeader, StatCard, StatusBadge, Tabs } from "@/components/ui";
import { fetchBankroll, fetchBets, fetchDecisionAudits, fetchPredictionMetrics, fetchStrategyPerformance } from "@/lib/api";
import { formatHandicapSide } from "@/lib/handicap";
import type { BankrollSummary, DecisionAudit, LeagueFilter, ModelKey, PredictionMetrics, SimulatedBet, StrategyPerformance } from "@/lib/types";

const leagues: Array<{ key: LeagueFilter; label: string }> = [
  { key: "all", label: "全部" }, { key: "epl", label: "英超" }, { key: "laliga", label: "西甲" }, { key: "csl", label: "中超" },
];

export function PerformanceDashboard() {
  const [bankroll, setBankroll] = useState<BankrollSummary | null>(null);
  const [bets, setBets] = useState<SimulatedBet[]>([]);
  const [decisions, setDecisions] = useState<DecisionAudit[]>([]);
  const [strategies, setStrategies] = useState<StrategyPerformance[]>([]);
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
      const [summary, betData, decisionData, strategyData, metricData] = await Promise.all([
        fetchBankroll(), fetchBets(selectedModel), fetchDecisionAudits(query, selectedModel), fetchStrategyPerformance(query), fetchPredictionMetrics(query, selectedModel),
      ]);
      setBankroll(summary); setBets(betData.items); setDecisions(decisionData.items); setStrategies(strategyData.items); setMetrics(metricData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "绩效数据请求失败");
    } finally {
      setLoading(false);
    }
  }, [filters, selectedModel]);

  useEffect(() => {
    let active = true;
    const query = metricQuery(filters);
    void Promise.all([fetchBankroll(), fetchBets(selectedModel), fetchDecisionAudits(query, selectedModel), fetchStrategyPerformance(query), fetchPredictionMetrics(query, selectedModel)])
      .then(([summary, betData, decisionData, strategyData, metricData]) => {
        if (!active) return;
        setBankroll(summary); setBets(betData.items); setDecisions(decisionData.items); setStrategies(strategyData.items); setMetrics(metricData);
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

  const visibleDecisions = useMemo(() => decisions.filter((item) => {
    if (filters.league !== "all" && item.league_key !== filters.league) return false;
    if (filters.startDate && (item.fixture_date ?? "") < filters.startDate) return false;
    if (filters.endDate && (item.fixture_date ?? "") > filters.endDate) return false;
    if (filters.modelVersion && item.model_version !== filters.modelVersion) return false;
    return true;
  }), [decisions, filters]);

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
          <StrategyLeaderboard strategies={strategies} />
          <EvaluationSummary metrics={metrics} />
          <AsianOutcomeStrip metrics={metrics} />
          <EquityCurve points={(bankroll.accounts?.[selectedModel] ?? bankroll).equity_curve} />
          <DecisionAuditTable decisions={visibleDecisions} />
          <BetHistory bets={visibleBets} />
          <SettlementHistory metrics={metrics} />
        </>
      ) : null}
    </main>
  );
}

function StrategyLeaderboard({ strategies }: { strategies: StrategyPerformance[] }) {
  return <section className="performance-section"><SectionHeader className="team-section-heading" eyebrow="STRATEGY LEADERBOARD" title="模型策略表现榜" meta="ROI · 盈亏 · 样本门禁" />{strategies.length ? <div className="team-table-scroll"><table className="performance-table strategy-leaderboard"><thead><tr><th>排名</th><th>模型 / 策略</th><th>ROI</th><th>盈亏</th><th>预测样本</th><th>Brier</th><th>Log Loss</th><th>市场改善</th><th>回撤</th><th>状态</th></tr></thead><tbody>{strategies.map((item) => <tr key={`${item.model_key}-${item.strategy_id}-${item.strategy_version}`}><td><strong>#{item.rank}</strong></td><th scope="row"><b>{item.model_key === "deepseek" ? "DeepSeek" : item.model_key === "chatgpt" ? "GPT-5.6 Sol" : item.model_key}</b><small>{item.strategy_name} · {item.strategy_version}</small></th><td className={item.roi > 0 ? "positive" : item.roi < 0 ? "negative" : undefined}>{percent(item.roi)}</td><td className={item.realized_pnl > 0 ? "positive" : item.realized_pnl < 0 ? "negative" : undefined}>{signedMoney(item.realized_pnl)}</td><td>{item.prediction_samples}</td><td>{item.average_brier?.toFixed(3) ?? "-"}</td><td>{item.average_log_loss?.toFixed(3) ?? "-"}</td><td>{signedMetric(item.brier_improvement)}</td><td>{percent(item.max_drawdown)}</td><td><StatusBadge variant={item.gate_status === "READY" ? "ready" : item.gate_status === "QUALITY_FAILED" ? "danger" : "partial"}>{item.gate_status === "READY" ? "通过" : item.gate_status === "QUALITY_FAILED" ? "未通过" : "影子模式"}</StatusBadge></td></tr>)}</tbody></table></div> : <EmptyState className="performance-empty">暂无策略表现样本</EmptyState>}</section>;
}

function DecisionAuditTable({ decisions }: { decisions: DecisionAudit[] }) {
  return <section className="performance-section"><SectionHeader className="team-section-heading" eyebrow="DECISION AUDIT" title="逐场策略决策" meta={`${decisions.length} 场`} />{decisions.length ? <div className="team-table-scroll"><table className="performance-table decision-audit-table"><thead><tr><th>比赛</th><th>策略</th><th>模型建议</th><th>候选方向</th><th>后端状态</th><th>赔率 / 优势</th><th>理论仓位</th><th>原因</th></tr></thead><tbody>{decisions.map((item) => <tr key={item.id}><th scope="row"><b>{item.home_team ?? "主队"} vs {item.away_team ?? "客队"}</b><small>{(item.league_key ?? "-").toUpperCase()} · {item.fixture_date ?? "-"}</small></th><td>{item.strategy_name} · {item.strategy_version}</td><td>{item.model_recommendation_status === "bet" ? "建议下注" : item.model_recommendation_status === "no_bet" ? "建议不下注" : "未记录"}</td><td>{(item.considered_selection ?? item.selection) === "none" ? "-" : selectionLabel(item.considered_selection ?? item.selection, null)}</td><td><StatusBadge className={`ledger-status ${item.execution_status}`} variant={item.execution_status === "bet" ? "ready" : item.execution_status === "unknown" ? "partial" : "danger"}>{executionLabel(item.execution_status)}</StatusBadge></td><td>{item.price ? `${item.price.toFixed(2)} · ${signedMetric(item.expected_edge)}` : "-"}</td><td>{percent(item.stake_fraction)}</td><td className="decision-reason">{item.execution_reason}</td></tr>)}</tbody></table></div> : <EmptyState className="performance-empty">暂无可审计的策略决策</EmptyState>}</section>;
}

function EvaluationSummary({ metrics }: { metrics: PredictionMetrics }) {
  const gate = metrics.quality_gate;
  const comparison = metrics.market_comparison;
  const decisions = metrics.decision_counts;
  const portfolio = metrics.portfolio;
  const gateLabel = gate?.status === "READY" ? "评估通过" : gate?.status === "QUALITY_FAILED" ? "质量未通过" : "样本不足 · 影子模式";
  const failureLabels = (gate?.failures ?? []).map((failure) => ({
    MIN_SETTLED_FIXTURES: "已结算比赛不足",
    MIN_PREDICTION_SAMPLES: "预测样本不足",
    MIN_MARKET_COMPARISON_SAMPLES: "市场对照样本不足",
    MIN_CLV_SAMPLES: "CLV 样本不足",
    MIN_ROI: "ROI 未达到门槛",
    MIN_AVERAGE_CLV: "平均 CLV 未达到门槛",
    MIN_BRIER_IMPROVEMENT_VS_MARKET: "Brier 未优于市场",
    MAX_DRAWDOWN: "最大回撤超限",
  } as Record<string, string>)[failure] ?? failure);
  return <section className="performance-section evaluation-summary" aria-label="策略评估摘要">
    <SectionHeader className="team-section-heading" eyebrow="STRATEGY EVALUATION" title="策略质量门禁" meta={metrics.experiment?.strategy_name ?? "基准策略"} />
    <div className="evaluation-grid">
      <div className={`evaluation-gate ${gate?.status === "READY" ? "ready" : "shadow"}`}><small>当前状态</small><strong>{gateLabel}</strong><span>{failureLabels.length ? failureLabels.join(" · ") : "所有评估条件已满足"}</span></div>
      <div><small>预测样本</small><strong>{gate?.counts.prediction_samples ?? metrics.sample_size}</strong><span>命中 {percent(metrics.accuracy)} · Brier {metrics.average_brier_score?.toFixed(3) ?? "-"}</span></div>
      <div><small>概率质量</small><strong>{metrics.average_log_loss?.toFixed(3) ?? "-"}</strong><span>Log Loss · RPS {metrics.average_rps?.toFixed(3) ?? "-"}</span></div>
      <div><small>市场对照</small><strong>{comparison?.sample_size ?? 0}</strong><span>Brier 改善 {signedMetric(comparison?.brier_improvement)} · CLV {portfolio?.clv_samples ?? 0} 样本</span></div>
      <div><small>决策记录</small><strong>{(decisions?.bet ?? 0) + (decisions?.no_bet ?? 0) + (decisions?.insufficient_data ?? 0) + (decisions?.unknown ?? 0)}</strong><span>下注 {decisions?.bet ?? 0} · 不下注 {decisions?.no_bet ?? 0} · 数据不足 {decisions?.insufficient_data ?? 0} · 历史未记录 {decisions?.unknown ?? 0}</span></div>
      <div><small>组合表现</small><strong>{portfolio ? signedMoney(portfolio.realized_pnl) : "-"}</strong><span>ROI {portfolio ? percent(portfolio.roi) : "-"} · 回撤 {portfolio ? percent(portfolio.max_drawdown) : "-"}</span></div>
    </div>
  </section>;
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
  return <section className="performance-section"><SectionHeader className="team-section-heading" eyebrow="PREDICTION EVALUATION" title="预测结算记录" meta={`${metrics.sample_size} 个样本`} />{metrics.items.length ? <div className="team-table-scroll"><table className="performance-table settlement-ledger"><thead><tr><th>日期</th><th>联赛</th><th>赛季</th><th>预测</th><th>实际</th><th>比分</th><th>正确</th><th>Brier</th><th>Log Loss</th><th>RPS</th><th>完整度</th><th>模型</th></tr></thead><tbody>{metrics.items.map((item) => <tr key={item.id}><td>{item.fixture_date}</td><td>{item.league_key.toUpperCase()}</td><td>{item.season}</td><td>{outcomeLabel(item.predicted_outcome)}</td><td>{outcomeLabel(item.actual_outcome)}</td><td>{item.score.home} : {item.score.away}</td><td><StatusBadge className={item.correct ? "result-correct" : "result-wrong"} variant={item.correct ? "ready" : "danger"}>{item.correct ? "命中" : "未中"}</StatusBadge></td><td>{item.brier_score.toFixed(3)}</td><td>{item.log_loss?.toFixed(3) ?? "-"}</td><td>{item.rps?.toFixed(3) ?? "-"}</td><td>{item.data_completeness === null ? "-" : percent(item.data_completeness)}</td><td>{item.model_version}</td></tr>)}</tbody></table></div> : <EmptyState className="performance-empty">比赛结束并完成结算后显示预测样本</EmptyState>}</section>;
}

function percent(value: number) { return `${(value * 100).toFixed(1)}%`; }
function signedMoney(value: number) { return `${value > 0 ? "+" : ""}${value.toFixed(2)}`; }
function signedMetric(value: number | null | undefined) { return value === null || value === undefined ? "-" : `${value > 0 ? "+" : ""}${value.toFixed(3)}`; }
function executionLabel(value: DecisionAudit["execution_status"]) { return value === "bet" ? "已下注" : value === "no_bet" ? "未下注" : value === "insufficient_data" ? "数据不足" : "历史未记录"; }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
function outcomeLabel(value: string) { return { home: "主胜", draw: "平", away: "客胜" }[value] ?? value; }
function settlementLabel(value: SimulatedBet["settlement_result"]) { return value ? { full_win: "全赢", half_win: "半赢", push: "走水", half_loss: "半输", full_loss: "全输" }[value] : "已结"; }
function selectionLabel(value: string, line: number | null) {
  if (line !== null && value === "home_handicap") return formatHandicapSide(line, "home");
  if (line !== null && value === "away_handicap") return formatHandicapSide(line, "away");
  return { home: "主胜", draw: "平", away: "客胜", home_handicap: "主队亚洲盘", away_handicap: "客队亚洲盘" }[value] ?? value;
}

function metricQuery(filters: { league: LeagueFilter; season: string; startDate: string; endDate: string; modelVersion: string }) {
  const parameters = new URLSearchParams();
  if (filters.league !== "all") parameters.set("league", filters.league);
  if (filters.season) parameters.set("season", filters.season);
  if (filters.startDate) parameters.set("start_date", filters.startDate);
  if (filters.endDate) parameters.set("end_date", filters.endDate);
  if (filters.modelVersion) parameters.set("model_version", filters.modelVersion);
  return parameters.toString();
}
