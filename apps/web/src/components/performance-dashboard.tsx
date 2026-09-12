"use client";

import { Filter, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  DataFreshness,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SectionHeader,
  StatCard,
  StatusBadge,
  Tabs,
} from "@/components/ui";
import {
  fetchBacktestReport,
  fetchBankroll,
  fetchBets,
  fetchDecisionAudits,
  fetchModelEvaluation,
  fetchPredictionMetrics,
  fetchStrategyPerformance,
} from "@/lib/api";
import { formatHandicapSide } from "@/lib/handicap";
import type {
  BacktestResponse,
  BankrollSummary,
  DecisionAudit,
  LeagueFilter,
  ModelKey,
  PredictionMetrics,
  PredictionSettlement,
  SimulatedBet,
  StrategyPerformance,
} from "@/lib/types";

const leagues: Array<{ key: LeagueFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "epl", label: "英超" },
  { key: "laliga", label: "西甲" },
  { key: "csl", label: "中超" },
  { key: "cfa_cup", label: "中国足协杯" },
  { key: "ucl", label: "欧冠" },
  { key: "acl", label: "亚冠" },
];

export function PerformanceDashboard() {
  const [bankroll, setBankroll] = useState<BankrollSummary | null>(null);
  const [bets, setBets] = useState<SimulatedBet[]>([]);
  const [decisions, setDecisions] = useState<DecisionAudit[]>([]);
  const [strategies, setStrategies] = useState<StrategyPerformance[]>([]);
  const [metrics, setMetrics] = useState<PredictionMetrics | null>(null);
  const [selectedModel, setSelectedModel] = useState<ModelKey>("chatgpt");
  const [filters, setFilters] = useState({
    league: "all" as LeagueFilter,
    season: "",
    startDate: "",
    endDate: "",
    modelVersion: "",
  });
  const [draft, setDraft] = useState(filters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = metricQuery(filters);
      const [summary, betData, decisionData, strategyData, metricData] =
        await Promise.all([
          fetchBankroll(),
          fetchBets(selectedModel),
          fetchDecisionAudits(query, selectedModel),
          fetchStrategyPerformance(query),
          fetchPredictionMetrics(query, selectedModel),
        ]);
      setBankroll(summary);
      setBets(betData.items);
      setDecisions(decisionData.items);
      setStrategies(strategyData.items);
      setMetrics(metricData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "绩效数据请求失败");
    } finally {
      setLoading(false);
    }
  }, [filters, selectedModel]);

  useEffect(() => {
    let active = true;
    const query = metricQuery(filters);
    void Promise.all([
      fetchBankroll(),
      fetchBets(selectedModel),
      fetchDecisionAudits(query, selectedModel),
      fetchStrategyPerformance(query),
      fetchPredictionMetrics(query, selectedModel),
    ])
      .then(([summary, betData, decisionData, strategyData, metricData]) => {
        if (!active) return;
        setBankroll(summary);
        setBets(betData.items);
        setDecisions(decisionData.items);
        setStrategies(strategyData.items);
        setMetrics(metricData);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "绩效数据请求失败",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filters, selectedModel]);

  const visibleBets = useMemo(
    () =>
      bets.filter((bet) => {
        if (filters.league !== "all" && bet.league_key !== filters.league)
          return false;
        if (filters.startDate && bet.fixture_date < filters.startDate)
          return false;
        if (filters.endDate && bet.fixture_date > filters.endDate) return false;
        if (filters.modelVersion && bet.model_version !== filters.modelVersion)
          return false;
        return true;
      }),
    [bets, filters],
  );

  const visibleDecisions = useMemo(
    () =>
      decisions.filter((item) => {
        if (filters.league !== "all" && item.league_key !== filters.league)
          return false;
        if (filters.startDate && (item.fixture_date ?? "") < filters.startDate)
          return false;
        if (filters.endDate && (item.fixture_date ?? "") > filters.endDate)
          return false;
        if (filters.modelVersion && item.model_version !== filters.modelVersion)
          return false;
        return true;
      }),
    [decisions, filters],
  );

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
        action={
          <button
            className="sync-action"
            type="button"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={13} className={loading ? "spin" : ""} />
            刷新
          </button>
        }
      />
      <PageHeader
        className="workspace-title"
        eyebrow="MODEL PERFORMANCE"
        title="模拟资金与预测绩效"
        description="逐笔追踪下注、结算、盈利与概率质量。"
      />
      <Tabs
        className="performance-filter"
        ariaLabel="绩效联赛筛选"
        value={draft.league}
        onChange={(league) => setDraft((current) => ({ ...current, league }))}
        items={leagues.map((item) => ({ value: item.key, label: item.label }))}
      />
      <form className="metric-filter-row" onSubmit={applyFilters}>
        <label>
          <span>赛季</span>
          <input
            value={draft.season}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                season: event.target.value,
              }))
            }
            placeholder="2026-27"
          />
        </label>
        <label>
          <span>开始日期</span>
          <input
            type="date"
            value={draft.startDate}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                startDate: event.target.value,
              }))
            }
          />
        </label>
        <label>
          <span>结束日期</span>
          <input
            type="date"
            value={draft.endDate}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                endDate: event.target.value,
              }))
            }
          />
        </label>
        <label className="model-filter">
          <span>模型版本</span>
          <input
            value={draft.modelVersion}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                modelVersion: event.target.value,
              }))
            }
            placeholder="deepseek:deepseek-v4-flash"
          />
        </label>
        <button type="submit">
          <Filter size={14} aria-hidden="true" />
          应用
        </button>
      </form>
      {error && (
        <ErrorState className="error-banner performance-error">
          {error}
        </ErrorState>
      )}
      {loading && !bankroll ? (
        <LoadingState className="team-loading">正在读取模拟账本</LoadingState>
      ) : bankroll && metrics ? (
        <>
          <Tabs
            className="model-performance-tabs"
            ariaLabel="选择模型资金账户"
            value={selectedModel}
            onChange={setSelectedModel}
            items={(["chatgpt"] as ModelKey[]).map((key) => ({
              value: key,
              label: "GPT-5.6 Sol",
            }))}
          />
          <SummaryStrip
            bankroll={bankroll.accounts?.[selectedModel] ?? bankroll}
            metrics={metrics}
          />
          <ProfitabilityCallout
            bankroll={bankroll.accounts?.[selectedModel] ?? bankroll}
            modelKey={selectedModel}
          />
          <ModelComparisonStrip
            bankroll={bankroll}
            selectedModel={selectedModel}
          />
          <StrategyLeaderboard strategies={strategies} />
          <EvaluationSummary metrics={metrics} />
          <BacktestPanel />
          <ModelEvaluationPanel />
          <AsianOutcomeStrip metrics={metrics} />
          <EquityCurve
            points={
              (bankroll.accounts?.[selectedModel] ?? bankroll).equity_curve
            }
          />
          <DecisionAuditTable decisions={visibleDecisions} />
          <BetHistory bets={visibleBets} />
          <SettlementHistory metrics={metrics} />
        </>
      ) : null}
    </main>
  );
}

function BacktestPanel() {
  const [report, setReport] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [league, setLeague] = useState<"global" | "CSL" | "EPL" | "LAL">(
    "global",
  );
  useEffect(() => {
    let active = true;
    void fetchBacktestReport()
      .then((result) => {
        if (active) setReport(result);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "回测数据请求失败",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  const leagueKeys = ["global", "CSL", "EPL", "LAL"] as const;
  const leagueLabels: Record<(typeof leagueKeys)[number], string> = {
    global: "全联赛",
    CSL: "中超",
    EPL: "英超",
    LAL: "西甲",
  };
  const current = report?.[league];
  const windows = (current?.windows ?? []).filter(
    (w) => (w.eligible_samples ?? 0) > 0,
  );
  const width = 880;
  const height = 150;
  const pad = 16;
  const brierValues = windows
    .map(
      (w) =>
        w.forecast_metrics?.baseline?.brier ??
        w.forecast_metrics?.p3_ensemble?.brier,
    )
    .filter((v): v is number => v != null);
  const ensembleValues = windows
    .map((w) => w.forecast_metrics?.p3_ensemble?.brier)
    .filter((v): v is number => v != null);
  const all = [...brierValues, ...ensembleValues];
  const min = all.length ? Math.min(...all) * 0.9 : 0;
  const max = all.length ? Math.max(...all) * 1.1 : 1;
  const points = (values: number[]) =>
    values
      .map((v, i) => {
        const x =
          pad +
          (values.length === 1
            ? (width - pad * 2) / 2
            : (i * (width - pad * 2)) / (values.length - 1));
        const y =
          height - pad - ((v - min) / (max - min || 1)) * (height - pad * 2);
        return `${x},${y}`;
      })
      .join(" ");
  const avg = (values: number[]) =>
    values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return (
    <section className="performance-section" aria-label="历史回测">
      <SectionHeader
        className="team-section-heading"
        eyebrow="ROLLING BACKTEST"
        title="历史滚动回测"
        meta={
          current
            ? `${windows.length} 个有效窗口 · 泄漏检查${current.leakage_check?.passed ? "通过" : "未通过"}`
            : "P4"
        }
      />
      {error ? (
        <ErrorState>{error}</ErrorState>
      ) : !report ? (
        <LoadingState>正在计算滚动回测</LoadingState>
      ) : (
        <>
          <Tabs
            className="league-filter backtest-league-tabs"
            ariaLabel="回测联赛"
            value={league}
            onChange={(key) => setLeague(key)}
            items={leagueKeys.map((key) => ({
              value: key,
              label: leagueLabels[key],
            }))}
          />
          {windows.length ? (
            <>
              <div className="backtest-stats">
                <div>
                  <small>平均 Brier（基线）</small>
                  <strong>{avg(brierValues)?.toFixed(3) ?? "-"}</strong>
                </div>
                <div>
                  <small>平均 Brier（集成）</small>
                  <strong>{avg(ensembleValues)?.toFixed(3) ?? "-"}</strong>
                </div>
                <div>
                  <small>有效样本窗口</small>
                  <strong>
                    {windows.length} / {current?.runs ?? 0}
                  </strong>
                </div>
                <div>
                  <small>泄漏检查</small>
                  <strong>
                    {current?.leakage_check?.passed ? "通过" : "未通过"}
                  </strong>
                </div>
              </div>
              <div className="equity-chart backtest-chart">
                <svg
                  viewBox={`0 0 ${width} ${height}`}
                  role="img"
                  aria-label="滚动回测 Brier 曲线"
                  preserveAspectRatio="none"
                >
                  <line
                    x1={pad}
                    y1={height - pad}
                    x2={width - pad}
                    y2={height - pad}
                  />
                  {brierValues.length > 1 && (
                    <polyline points={points(brierValues)} />
                  )}
                  {ensembleValues.length > 1 && (
                    <polyline
                      className="ensemble-line"
                      points={points(ensembleValues)}
                    />
                  )}
                </svg>
                <span>基线 · 集成 双线对比，越低越好</span>
              </div>
            </>
          ) : (
            <EmptyState className="performance-empty">
              结算样本不足，暂无可回测窗口
            </EmptyState>
          )}
        </>
      )}
    </section>
  );
}

function exportCsv(filename: string, rows: Array<Record<string, unknown>>) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const newline = String.fromCharCode(10);
  const esc = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    return text.includes(",") ||
      text.includes(String.fromCharCode(34)) ||
      text.includes(newline)
      ? String.fromCharCode(34) +
          text.replace(/"/g, String.fromCharCode(34, 34)) +
          String.fromCharCode(34)
      : text;
  };
  const csv = [
    headers.join(","),
    ...rows.map((row) => headers.map((h) => esc(row[h])).join(",")),
  ].join(newline);
  const bom = String.fromCharCode(65279);
  const blob = new Blob([bom + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ExportButton({
  filename,
  rows,
  label,
}: {
  filename: string;
  rows: Array<Record<string, unknown>>;
  label: string;
}) {
  return (
    <button
      className="table-export"
      type="button"
      onClick={() => exportCsv(filename, rows)}
      disabled={!rows.length}
    >
      导出{label}
    </button>
  );
}

function ModelEvaluationPanel() {
  const [evaluation, setEvaluation] = useState<Awaited<
    ReturnType<typeof fetchModelEvaluation>
  > | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchModelEvaluation()
      .then((result) => {
        if (active) setEvaluation(result);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "模型评估请求失败",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  const reportKeys = ["CSL", "EPL", "LAL", "GLOBAL"];
  return (
    <section
      className="performance-section model-evaluation-section"
      aria-label="Model Evaluation"
    >
      <SectionHeader
        className="team-section-heading"
        eyebrow="MODEL EVALUATION"
        title="历史模型评估"
        meta={evaluation ? `实验 ${evaluation.experiment_id.slice(-8)}` : "P6"}
      />
      {error ? (
        <ErrorState>{error}</ErrorState>
      ) : !evaluation ? (
        <LoadingState>正在读取历史评估</LoadingState>
      ) : (
        <>
          <div
            className="model-evaluation-overview"
            aria-label="历史模型评估摘要"
          >
            {reportKeys.map((key) => {
              const report = evaluation.reports[key];
              return (
                <div key={key}>
                  <strong>{key}</strong>
                  <span>{report?.sample_count ?? 0} 个样本</span>
                  <small>{report?.confidence ?? "暂无评估"}</small>
                </div>
              );
            })}
          </div>
          <div className="model-evaluation-footnote">
            Leakage violations {evaluation.leakage_audit.violations} ·{" "}
            {evaluation.status}
          </div>
        </>
      )}
    </section>
  );
}

function StrategyLeaderboard({
  strategies,
}: {
  strategies: StrategyPerformance[];
}) {
  return (
    <section className="performance-section">
      <SectionHeader
        className="team-section-heading"
        eyebrow="STRATEGY LEADERBOARD"
        title="模型策略表现榜"
        meta="ROI · 盈亏 · 样本门禁"
      />
      {strategies.length ? (
        <div className="team-table-scroll">
          <table className="performance-table strategy-leaderboard">
            <thead>
              <tr>
                <th>排名</th>
                <th>模型 / 策略</th>
                <th>ROI</th>
                <th>盈亏</th>
                <th>预测样本</th>
                <th>Brier</th>
                <th>Log Loss</th>
                <th>市场改善</th>
                <th>回撤</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((item) => (
                <tr
                  key={`${item.model_key}-${item.strategy_id}-${item.strategy_version}`}
                >
                  <td>
                    <strong>#{item.rank}</strong>
                  </td>
                  <th scope="row">
                    <b>
                      {item.model_key === "deepseek"
                        ? "DeepSeek"
                        : item.model_key === "chatgpt"
                          ? "GPT-5.6 Sol"
                          : item.model_key}
                    </b>
                    <small>
                      {item.strategy_name} · {item.strategy_version}
                    </small>
                  </th>
                  <td
                    className={
                      item.roi > 0
                        ? "positive"
                        : item.roi < 0
                          ? "negative"
                          : undefined
                    }
                  >
                    {percent(item.roi)}
                  </td>
                  <td
                    className={
                      item.realized_pnl > 0
                        ? "positive"
                        : item.realized_pnl < 0
                          ? "negative"
                          : undefined
                    }
                  >
                    {signedMoney(item.realized_pnl)}
                  </td>
                  <td>{item.prediction_samples}</td>
                  <td>{item.average_brier?.toFixed(3) ?? "-"}</td>
                  <td>{item.average_log_loss?.toFixed(3) ?? "-"}</td>
                  <td>{signedMetric(item.brier_improvement)}</td>
                  <td>{percent(item.max_drawdown)}</td>
                  <td>
                    <StatusBadge
                      variant={
                        item.gate_status === "READY"
                          ? "ready"
                          : item.gate_status === "QUALITY_FAILED"
                            ? "danger"
                            : "partial"
                      }
                    >
                      {item.gate_status === "READY"
                        ? "通过"
                        : item.gate_status === "QUALITY_FAILED"
                          ? "未通过"
                          : "影子模式"}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState className="performance-empty">暂无策略表现样本</EmptyState>
      )}
    </section>
  );
}

function DecisionAuditTable({ decisions }: { decisions: DecisionAudit[] }) {
  const { visible, page, pageCount, setPage } = usePaginated(
    decisions,
    byDateDesc<DecisionAudit>((item) => item.fixture_date ?? item.created_at),
  );
  return (
    <section className="performance-section">
      <SectionHeader
        className="team-section-heading"
        eyebrow="DECISION AUDIT"
        title="逐场策略决策"
        meta={`${decisions.length} 场`}
      />
      <ExportButton
        filename="策略决策.csv"
        label="决策"
        rows={decisions.map((item) => ({
          比赛: `${item.home_team ?? ""} vs ${item.away_team ?? ""}`,
          日期: item.fixture_date ?? "",
          联赛: item.league_key ?? "",
          模型: item.model_version ?? "",
          策略: `${item.strategy_name} ${item.strategy_version}`,
          建议: item.model_recommendation_status ?? "",
          执行: item.execution_status,
          市场方向: item.considered_selection ?? item.selection ?? "",
          赔率: item.price ?? "",
          优势: item.expected_edge ?? "",
          仓位: item.stake_fraction ?? "",
          原因: item.execution_reason ?? "",
        }))}
      />
      {decisions.length ? (
        <>
          <div className="team-table-scroll">
            <table className="performance-table decision-audit-table">
              <thead>
                <tr>
                  <th>比赛</th>
                  <th>下注模型</th>
                  <th>策略</th>
                  <th>模型建议</th>
                  <th>候选方向</th>
                  <th>后端状态</th>
                  <th>赔率 / 优势</th>
                  <th>理论仓位</th>
                  <th>原因</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.id}>
                    <th scope="row">
                      <b>
                        {item.home_team ?? "主队"} vs {item.away_team ?? "客队"}
                      </b>
                      <small>
                        {leagueName(item.league_key)} ·{" "}
                        {item.fixture_date ?? "-"}
                      </small>
                    </th>
                    <td className="model-cell">
                      <b>{modelLabel(item.model_key, item.model_version)}</b>
                      <small>{item.model_version ?? "版本未知"}</small>
                    </td>
                    <td>
                      {item.strategy_name} · {item.strategy_version}
                    </td>
                    <td>
                      {item.model_recommendation_status === "bet"
                        ? "建议下注"
                        : item.model_recommendation_status === "no_bet"
                          ? "建议不下注"
                          : "未记录"}
                    </td>
                    <td>
                      {(item.considered_selection ?? item.selection) === "none"
                        ? "-"
                        : selectionLabel(
                            item.considered_selection ?? item.selection,
                            null,
                          )}
                    </td>
                    <td>
                      <StatusBadge
                        className={`ledger-status ${item.execution_status}`}
                        variant={
                          item.execution_status === "bet"
                            ? "ready"
                            : item.execution_status === "unknown"
                              ? "partial"
                              : "danger"
                        }
                      >
                        {executionLabel(item.execution_status)}
                      </StatusBadge>
                    </td>
                    <td>
                      {item.price
                        ? `${item.price.toFixed(2)} · ${signedMetric(item.expected_edge)}`
                        : "-"}
                    </td>
                    <td>{percent(item.stake_fraction)}</td>
                    <td className="decision-reason">{item.execution_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageCount={pageCount} onChange={setPage} />
        </>
      ) : (
        <EmptyState className="performance-empty">
          暂无可审计的策略决策
        </EmptyState>
      )}
    </section>
  );
}

function EvaluationSummary({ metrics }: { metrics: PredictionMetrics }) {
  const gate = metrics.quality_gate;
  const comparison = metrics.market_comparison;
  const decisions = metrics.decision_counts;
  const portfolio = metrics.portfolio;
  const gateLabel =
    gate?.status === "READY"
      ? "评估通过"
      : gate?.status === "QUALITY_FAILED"
        ? "质量未通过"
        : "样本不足 · 影子模式";
  const failureLabels = (gate?.failures ?? []).map(
    (failure) =>
      (
        ({
          MIN_SETTLED_FIXTURES: "已结算比赛不足",
          MIN_PREDICTION_SAMPLES: "预测样本不足",
          MIN_MARKET_COMPARISON_SAMPLES: "市场对照样本不足",
          MIN_CLV_SAMPLES: "CLV 样本不足",
          MIN_ROI: "ROI 未达到门槛",
          MIN_AVERAGE_CLV: "平均 CLV 未达到门槛",
          MIN_BRIER_IMPROVEMENT_VS_MARKET: "Brier 未优于市场",
          MAX_DRAWDOWN: "最大回撤超限",
        }) as Record<string, string>
      )[failure] ?? failure,
  );
  return (
    <section
      className="performance-section evaluation-summary"
      aria-label="策略评估摘要"
    >
      <SectionHeader
        className="team-section-heading"
        eyebrow="STRATEGY EVALUATION"
        title="策略质量门禁"
        meta={metrics.experiment?.strategy_name ?? "基准策略"}
      />
      <div className="evaluation-grid">
        <div
          className={`evaluation-gate ${gate?.status === "READY" ? "ready" : "shadow"}`}
        >
          <small>当前状态</small>
          <strong>{gateLabel}</strong>
          <span>
            {failureLabels.length
              ? failureLabels.join(" · ")
              : "所有评估条件已满足"}
          </span>
        </div>
        <div>
          <small>CLV 相对收盘价（北极星）</small>
          <strong>
            {portfolio?.average_clv != null
              ? percent(portfolio.average_clv)
              : "-"}
          </strong>
          <span>
            {portfolio?.clv_samples ?? 0} 样本 · 长期跑赢收盘价 = 真实优势
          </span>
        </div>
        <div>
          <small>预测样本</small>
          <strong>
            {gate?.counts.prediction_samples ?? metrics.sample_size}
          </strong>
          <span>
            命中 {percent(metrics.accuracy)} · Brier{" "}
            {metrics.average_brier_score?.toFixed(3) ?? "-"}
          </span>
        </div>
        <div>
          <small>概率质量</small>
          <strong>{metrics.average_log_loss?.toFixed(3) ?? "-"}</strong>
          <span>Log Loss · RPS {metrics.average_rps?.toFixed(3) ?? "-"}</span>
        </div>
        <div>
          <small>市场对照</small>
          <strong>{comparison?.sample_size ?? 0}</strong>
          <span>Brier 改善 {signedMetric(comparison?.brier_improvement)}</span>
        </div>
        <div>
          <small>组合表现</small>
          <strong>
            {portfolio ? signedMoney(portfolio.realized_pnl) : "-"}
          </strong>
          <span>
            ROI {portfolio ? percent(portfolio.roi) : "-"} · 回撤{" "}
            {portfolio ? percent(portfolio.max_drawdown) : "-"}
          </span>
        </div>
      </div>
    </section>
  );
}

function ProfitabilityCallout({
  bankroll,
  modelKey,
}: {
  bankroll: BankrollSummary;
  modelKey: ModelKey;
}) {
  const pnl = bankroll.net_profit;
  const state =
    pnl > 0
      ? "盈利"
      : pnl < 0
        ? "亏损"
        : bankroll.settled_count
          ? "盈亏平衡"
          : "尚未产生已实现盈亏";
  return (
    <section
      className={`profitability-callout ${pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral"}`}
      aria-label="当前模型盈利状态"
    >
      <div>
        <span>当前模型累计结果</span>
        <strong>
          {modelLabel(modelKey)} · {state}
        </strong>
        <small>
          {bankroll.settled_count} 笔已结算 · {bankroll.open_count} 笔未结算
        </small>
      </div>
      <div>
        <small>已实现净盈亏</small>
        <strong>{signedMoney(pnl)}</strong>
      </div>
      <div>
        <small>账户权益</small>
        <strong>{bankroll.equity.toFixed(2)}</strong>
      </div>
      <div>
        <small>ROI</small>
        <strong>{percent(bankroll.roi)}</strong>
      </div>
    </section>
  );
}

function ModelComparisonStrip({
  bankroll,
  selectedModel,
}: {
  bankroll: BankrollSummary;
  selectedModel: ModelKey;
}) {
  const accounts: Partial<Record<ModelKey, BankrollSummary>> =
    bankroll.accounts ?? {};
  return (
    <section className="model-comparison-strip" aria-label="模型资金归因">
      <div className="model-comparison-heading">
        <div>
          <span>MODEL ATTRIBUTION</span>
          <strong>模型账户对比</strong>
        </div>
        <small>每个模型独立模拟账户，盈亏不会混算</small>
      </div>
      {(["deepseek", "chatgpt"] as ModelKey[]).map((key) => {
        const account = accounts[key];
        return (
          <article
            className={key === selectedModel ? "selected" : ""}
            key={key}
          >
            <div className="model-account-heading">
              <span>{modelLabel(key)}</span>
              <StatusBadge
                variant={
                  account?.net_profit && account.net_profit > 0
                    ? "ready"
                    : account?.net_profit && account.net_profit < 0
                      ? "danger"
                      : "neutral"
                }
              >
                {account
                  ? account.settled_count
                    ? account.net_profit > 0
                      ? "盈利"
                      : account.net_profit < 0
                        ? "亏损"
                        : "持平"
                    : "未结算"
                  : "无数据"}
              </StatusBadge>
            </div>
            <strong
              className={
                account && account.net_profit > 0
                  ? "positive"
                  : account && account.net_profit < 0
                    ? "negative"
                    : undefined
              }
            >
              {account ? signedMoney(account.net_profit) : "-"}
            </strong>
            <small>
              已实现净盈亏 ·{" "}
              {account ? `${account.bet_count} 笔下注` : "尚未开始"}
            </small>
            <dl>
              <div>
                <dt>ROI</dt>
                <dd>{account ? percent(account.roi) : "-"}</dd>
              </div>
              <div>
                <dt>权益</dt>
                <dd>{account ? account.equity.toFixed(2) : "-"}</dd>
              </div>
              <div>
                <dt>未结</dt>
                <dd>{account?.open_count ?? 0}</dd>
              </div>
            </dl>
          </article>
        );
      })}
    </section>
  );
}

function AsianOutcomeStrip({ metrics }: { metrics: PredictionMetrics }) {
  const labels: Array<
    [keyof PredictionMetrics["asian_handicap_results"], string]
  > = [
    ["full_win", "全赢"],
    ["half_win", "半赢"],
    ["push", "走水"],
    ["half_loss", "半输"],
    ["full_loss", "全输"],
  ];
  return (
    <section className="asian-outcome-strip" aria-label="亚洲盘结算分类">
      <span>亚洲盘结算</span>
      {labels.map(([key, label]) => (
        <div key={key}>
          <small>{label}</small>
          <strong>{metrics.asian_handicap_results[key]}</strong>
        </div>
      ))}
    </section>
  );
}

function SummaryStrip({
  bankroll,
  metrics,
}: {
  bankroll: BankrollSummary;
  metrics: PredictionMetrics;
}) {
  const facts = [
    ["账户权益", bankroll.equity.toFixed(2)],
    ["可用现金", bankroll.balance.toFixed(2)],
    ["已实现利润", signedMoney(bankroll.net_profit)],
    ["未结敞口", bankroll.open_exposure.toFixed(2)],
    ["ROI", percent(bankroll.roi)],
    ["命中率", percent(metrics.accuracy)],
    ["Brier", metrics.average_brier_score?.toFixed(3) ?? "-"],
    [
      "数据完整度",
      metrics.average_data_completeness === null
        ? "-"
        : percent(metrics.average_data_completeness),
    ],
    ["最大回撤", percent(bankroll.max_drawdown)],
  ];
  return (
    <section className="performance-summary" aria-label="绩效摘要">
      {facts.map(([label, value]) => (
        <StatCard
          key={label}
          label={label}
          value={value}
          valueClassName={
            label === "已实现利润"
              ? bankroll.net_profit >= 0
                ? "positive"
                : "negative"
              : undefined
          }
        />
      ))}
    </section>
  );
}

function EquityCurve({ points }: { points: BankrollSummary["equity_curve"] }) {
  const width = 900;
  const height = 160;
  const padding = 18;
  const values = points.length ? points.map((point) => point.balance) : [1000];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const spread = maximum - minimum || 20;
  const coordinates = values.map((value, index) => {
    const x =
      padding +
      (values.length === 1
        ? (width - padding * 2) / 2
        : (index * (width - padding * 2)) / (values.length - 1));
    const y =
      height -
      padding -
      ((value - minimum + (maximum === minimum ? 10 : 0)) / spread) *
        (height - padding * 2);
    return { x, y };
  });
  return (
    <section className="performance-section equity-curve-section">
      <SectionHeader
        className="team-section-heading"
        eyebrow="BANKROLL CURVE"
        title="已实现权益曲线"
        meta={`${points.length} 个节点`}
      />
      <div className="equity-chart">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="模拟资金已实现权益曲线"
          preserveAspectRatio="none"
        >
          <line
            x1={padding}
            y1={height - padding}
            x2={width - padding}
            y2={height - padding}
          />
          <polyline
            points={coordinates
              .map((point) => `${point.x},${point.y}`)
              .join(" ")}
          />
          {coordinates.map((point, index) => (
            <circle
              key={`${point.x}-${index}`}
              cx={point.x}
              cy={point.y}
              r="4"
            />
          ))}
        </svg>
        <span>{minimum.toFixed(2)}</span>
        <strong>{values.at(-1)?.toFixed(2)}</strong>
      </div>
    </section>
  );
}

function BetHistory({ bets }: { bets: SimulatedBet[] }) {
  return (
    <section className="performance-section">
      <SectionHeader
        className="team-section-heading"
        eyebrow="SIMULATED LEDGER"
        title="模拟下注明细"
        meta={`${bets.length} 笔`}
      />
      <ExportButton
        filename="模拟下注.csv"
        label="下注"
        rows={bets.map((bet) => ({
          比赛: `${bet.home_team} vs ${bet.away_team}`,
          日期: bet.fixture_date,
          联赛: bet.league_key,
          市场: bet.market,
          选择: bet.selection,
          让球线: bet.handicap_line ?? "",
          赔率: bet.odds,
          金额: bet.stake,
          状态: bet.status,
          结果: bet.settlement_result ?? "",
          净盈亏: bet.net_profit ?? "",
          下注时间: bet.placed_at,
        }))}
      />
      {bets.length ? (
        <div className="team-table-scroll">
          <table className="performance-table bet-ledger">
            <thead>
              <tr>
                <th>比赛</th>
                <th>下注模型</th>
                <th>市场</th>
                <th>选择</th>
                <th>赔率</th>
                <th>金额</th>
                <th>状态</th>
                <th>净盈亏</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {bets.map((bet) => (
                <tr key={bet.id}>
                  <th scope="row">
                    <b>
                      {bet.home_team} vs {bet.away_team}
                    </b>
                    <small>
                      {leagueName(bet.league_key)} · {bet.fixture_date}
                    </small>
                  </th>
                  <td className="model-cell">
                    <b>{modelLabel(bet.model_key, bet.model_version)}</b>
                    <small>{bet.model_version}</small>
                  </td>
                  <td>{bet.market === "1x2" ? "胜平负" : "亚洲盘"}</td>
                  <td>{selectionLabel(bet.selection, bet.handicap_line)}</td>
                  <td>{bet.odds.toFixed(2)}</td>
                  <td>{bet.stake.toFixed(2)}</td>
                  <td>
                    <StatusBadge
                      className={`ledger-status ${bet.status}`}
                      variant={bet.status === "placed" ? "partial" : "ready"}
                    >
                      {bet.status === "placed"
                        ? "未结"
                        : settlementLabel(bet.settlement_result)}
                    </StatusBadge>
                  </td>
                  <td
                    className={
                      (bet.net_profit ?? 0) > 0
                        ? "positive"
                        : (bet.net_profit ?? 0) < 0
                          ? "negative"
                          : undefined
                    }
                  >
                    {bet.net_profit === null
                      ? "-"
                      : signedMoney(bet.net_profit)}
                  </td>
                  <td>{formatDate(bet.placed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState className="performance-empty">
          尚无符合规则的模拟下注
        </EmptyState>
      )}
    </section>
  );
}

function SettlementHistory({ metrics }: { metrics: PredictionMetrics }) {
  const { visible, page, pageCount, setPage } = usePaginated(
    metrics.items,
    byDateDesc<PredictionSettlement>((item) => item.fixture_date),
  );
  return (
    <section className="performance-section">
      <SectionHeader
        className="team-section-heading"
        eyebrow="PREDICTION EVALUATION"
        title="预测结算记录"
        meta={`${metrics.sample_size} 个样本`}
      />
      <ExportButton
        filename="预测结算.csv"
        label="结算"
        rows={metrics.items.map((item) => ({
          比赛: `${item.home_team ?? ""} vs ${item.away_team ?? ""}`,
          日期: item.fixture_date,
          联赛: item.league_key,
          预测: item.predicted_outcome,
          实际: item.actual_outcome,
          比分: `${item.score.home}:${item.score.away}`,
          命中: item.correct,
          Brier: item.brier_score,
          LogLoss: item.log_loss ?? "",
          RPS: item.rps ?? "",
          模型版本: item.model_version,
        }))}
      />
      {metrics.items.length ? (
        <>
          <div className="team-table-scroll">
            <table className="performance-table settlement-ledger">
              <thead>
                <tr>
                  <th>比赛</th>
                  <th>日期</th>
                  <th>联赛</th>
                  <th>预测</th>
                  <th>实际</th>
                  <th>比分</th>
                  <th>正确</th>
                  <th>Brier</th>
                  <th>Log Loss</th>
                  <th>RPS</th>
                  <th>完整度</th>
                  <th>模型 / 版本</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.id}>
                    <th scope="row">
                      <b>
                        {item.home_team ?? "主队"} vs {item.away_team ?? "客队"}
                      </b>
                    </th>
                    <td>{item.fixture_date}</td>
                    <td>{leagueName(item.league_key)}</td>
                    <td>{outcomeLabel(item.predicted_outcome)}</td>
                    <td>{outcomeLabel(item.actual_outcome)}</td>
                    <td>
                      {item.score.home} : {item.score.away}
                    </td>
                    <td>
                      <StatusBadge
                        className={
                          item.correct ? "result-correct" : "result-wrong"
                        }
                        variant={item.correct ? "ready" : "danger"}
                      >
                        {item.correct ? "命中" : "未中"}
                      </StatusBadge>
                    </td>
                    <td>{item.brier_score.toFixed(3)}</td>
                    <td>{item.log_loss?.toFixed(3) ?? "-"}</td>
                    <td>{item.rps?.toFixed(3) ?? "-"}</td>
                    <td>
                      {item.data_completeness === null
                        ? "-"
                        : percent(item.data_completeness)}
                    </td>
                    <td className="model-cell">
                      <b>{modelLabel(item.model_key, item.model_version)}</b>
                      <small>{item.model_version}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageCount={pageCount} onChange={setPage} />
        </>
      ) : (
        <EmptyState className="performance-empty">
          比赛结束并完成结算后显示预测样本
        </EmptyState>
      )}
    </section>
  );
}

const PAGE_SIZE = 5;

const LEAGUE_NAMES: Record<string, string> = {
  epl: "英超",
  laliga: "西甲",
  csl: "中超",
  cfa_cup: "中国足协杯",
  ucl: "欧冠",
  acl: "亚冠",
};
function leagueName(value: string | null | undefined) {
  return (value && LEAGUE_NAMES[value]) || (value ?? "-").toUpperCase();
}

function usePaginated<T>(items: T[], compare: (a: T, b: T) => number) {
  const sorted = useMemo(() => [...items].sort(compare), [items, compare]);
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const visible = sorted.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  return { visible, page: current, pageCount, setPage };
}

function Pagination({
  page,
  pageCount,
  onChange,
}: {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;
  return (
    <div className="table-pagination">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </button>
      <span>
        {page} / {pageCount}
      </span>
      <button
        type="button"
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </button>
    </div>
  );
}

function byDateDesc<T>(dateOf: (item: T) => string | null) {
  return (a: T, b: T) => (dateOf(b) ?? "").localeCompare(dateOf(a) ?? "");
}

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}
function signedMoney(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}
function signedMetric(value: number | null | undefined) {
  return value === null || value === undefined
    ? "-"
    : `${value > 0 ? "+" : ""}${value.toFixed(3)}`;
}
function modelLabel(
  value: ModelKey | string | null | undefined,
  version?: string | null,
) {
  const key = value || version?.split(":", 1)[0];
  return key === "chatgpt"
    ? "GPT-5.6 Sol"
    : key === "deepseek"
      ? "DeepSeek"
      : key || "模型未知";
}
function executionLabel(value: DecisionAudit["execution_status"]) {
  return value === "bet"
    ? "已下注"
    : value === "no_bet"
      ? "未下注"
      : value === "insufficient_data"
        ? "数据不足"
        : "历史未记录";
}
function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
function outcomeLabel(value: string) {
  return { home: "主胜", draw: "平", away: "客胜" }[value] ?? value;
}
function settlementLabel(value: SimulatedBet["settlement_result"]) {
  return value
    ? {
        full_win: "全赢",
        half_win: "半赢",
        push: "走水",
        half_loss: "半输",
        full_loss: "全输",
      }[value]
    : "已结";
}
function selectionLabel(value: string, line: number | null) {
  if (line !== null && value === "home_handicap")
    return formatHandicapSide(line, "home");
  if (line !== null && value === "away_handicap")
    return formatHandicapSide(line, "away");
  return (
    {
      home: "主胜",
      draw: "平",
      away: "客胜",
      home_handicap: "主队亚洲盘",
      away_handicap: "客队亚洲盘",
    }[value] ?? value
  );
}

function metricQuery(filters: {
  league: LeagueFilter;
  season: string;
  startDate: string;
  endDate: string;
  modelVersion: string;
}) {
  const parameters = new URLSearchParams();
  if (filters.league !== "all") parameters.set("league", filters.league);
  if (filters.season) parameters.set("season", filters.season);
  if (filters.startDate) parameters.set("start_date", filters.startDate);
  if (filters.endDate) parameters.set("end_date", filters.endDate);
  if (filters.modelVersion)
    parameters.set("model_version", filters.modelVersion);
  return parameters.toString();
}
