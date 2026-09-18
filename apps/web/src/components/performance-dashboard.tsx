"use client";

import { Cpu, Filter, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  Card,
  DataFreshness,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionHeader,
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

const inputClasses =
  "w-full bg-pitch-950 border border-slate-800 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-blue-500";

const insetPanelClasses = "rounded-xl border border-slate-800 bg-pitch-950 p-3.5";
const insetLabelClasses = "block text-[11px] text-slate-400";
const insetHintClasses = "mt-1 block text-xs text-slate-500";

const tableSectionClasses = "space-y-3";
const tableWrapClasses =
  "overflow-hidden rounded-2xl border border-slate-800 bg-pitch-900 shadow-xl";
const tableClasses = "w-full min-w-[900px] text-left text-xs font-mono";
const headRowClasses =
  "bg-pitch-950 text-slate-400 border-b border-slate-800 uppercase text-[11px]";
const headCellClasses = "px-4 py-3 text-left font-medium whitespace-nowrap";
const rowClasses = "transition-colors hover:bg-slate-800/30";
const tbodyClasses = "divide-y divide-slate-800/60";
const cellClasses = "px-4 py-3 whitespace-nowrap text-slate-300";
const numberCellClasses =
  "px-4 py-3 font-mono tabular-nums whitespace-nowrap text-slate-300";
const rowHeadClasses = "px-4 py-3 font-normal";
const moneyPositive = "font-mono font-semibold tabular-nums text-emerald-400";
const moneyNegative = "font-mono font-semibold tabular-nums text-rose-400";
const moneyNeutral = "font-mono tabular-nums text-slate-300";

function moneyClass(value: number) {
  return value > 0 ? moneyPositive : value < 0 ? moneyNegative : moneyNeutral;
}

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
    <main className="mx-auto w-full max-w-[1700px] space-y-6 px-6 pb-16 pt-6">
      <DataFreshness
        status="fresh"
        label="仅模拟资金 · 不连接真实投注平台"
        source="初始资金 1000 · 结算后自动更新"
        action={
          <button
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 font-mono text-xs text-slate-200 transition-colors hover:bg-slate-700 hover:text-white disabled:opacity-50"
            type="button"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
        }
      />
      <Card className="p-5" aria-label="绩效筛选">
        <div className="flex flex-wrap gap-2 border-b border-slate-800/80 pb-3">
          <Tabs
            variant="solid"
            ariaLabel="绩效联赛筛选"
            value={draft.league}
            onChange={(league) =>
              setDraft((current) => ({ ...current, league }))
            }
            items={leagues.map((item) => ({
              value: item.key,
              label: item.label,
            }))}
          />
        </div>
        <form
          className="grid grid-cols-1 gap-3 pt-4 md:grid-cols-12 md:items-end"
          onSubmit={applyFilters}
        >
          <label className="block md:col-span-2">
            <span className="mb-1 block text-[11px] text-slate-400">赛季</span>
            <input
              className={inputClasses}
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
          <label className="block md:col-span-2">
            <span className="mb-1 block text-[11px] text-slate-400">
              开始日期
            </span>
            <input
              className={inputClasses}
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
          <label className="block md:col-span-2">
            <span className="mb-1 block text-[11px] text-slate-400">
              结束日期
            </span>
            <input
              className={inputClasses}
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
          <label className="block md:col-span-4">
            <span className="mb-1 block text-[11px] text-slate-400">
              模型版本
            </span>
            <input
              className={inputClasses}
              value={draft.modelVersion}
              list="model-version-options"
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  modelVersion: event.target.value,
                }))
              }
              placeholder="deepseek:deepseek-v4-flash"
            />
            <datalist id="model-version-options">
              <option value="deepseek:deepseek-v4-flash" />
              <option value="chatgpt:gpt-5.6-sol" />
            </datalist>
          </label>
          <div className="md:col-span-2">
            <button
              type="submit"
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-3 py-2.5 text-xs font-bold text-white shadow-lg shadow-blue-600/30 transition-colors hover:bg-blue-500"
            >
              <Filter size={14} aria-hidden="true" />
              应用
            </button>
          </div>
        </form>
      </Card>
      {error && <ErrorState>{error}</ErrorState>}
      {loading && !bankroll ? (
        <LoadingState>正在读取模拟账本</LoadingState>
      ) : bankroll && metrics ? (
        <>
          <div
            className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-2xl bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-3 shadow-lg shadow-blue-600/20"
          >
            <Cpu size={15} className="text-blue-200" aria-hidden="true" />
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.25em] text-blue-200">
              EVALUATION MODEL
            </span>
            <strong className="font-mono text-base font-bold tracking-wide text-white">
              {modelLabel(selectedModel)}
            </strong>
          </div>
          <CoreMetricsCard
            bankroll={bankroll.accounts?.[selectedModel] ?? bankroll}
            metrics={metrics}
            modelKey={selectedModel}
          />
          <ModelComparisonStrip
            bankroll={bankroll}
            selectedModel={selectedModel}
            onSelect={setSelectedModel}
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

function CoreMetricsCard({
  bankroll,
  metrics,
  modelKey,
}: {
  bankroll: BankrollSummary;
  metrics: PredictionMetrics;
  modelKey: ModelKey;
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
  const pnl = bankroll.net_profit;
  const state =
    pnl > 0
      ? "盈利"
      : pnl < 0
        ? "亏损"
        : bankroll.settled_count
          ? "盈亏平衡"
          : "尚未产生已实现盈亏";
  const pnlToneClass =
    pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-rose-400" : "text-white";
  return (
    <Card className="p-5" aria-label="绩效摘要与盈利状态">
      <div className="grid grid-cols-2 gap-4 text-center font-mono sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9">
        {facts.map(([label, value]) => (
          <div key={label}>
            <span className={`mb-1 ${insetLabelClasses}`}>{label}</span>
            <strong
              className={`block text-xl font-black tabular-nums ${
                label === "已实现利润"
                  ? bankroll.net_profit >= 0
                    ? "text-emerald-400"
                    : "text-rose-400"
                  : "text-white"
              }`}
            >
              {value}
            </strong>
          </div>
        ))}
      </div>
      <div className="mt-4 grid items-center gap-4 border-t border-slate-800/80 pt-4 md:grid-cols-4">
        <div>
          <span className={`mb-1 ${insetLabelClasses}`}>
            当前模型累计结果
          </span>
          <strong className={`block text-lg font-bold ${pnlToneClass}`}>
            {modelLabel(modelKey)} · {state}
          </strong>
          <small className="block font-mono text-xs tabular-nums text-slate-500">
            {bankroll.settled_count} 笔已结算 · {bankroll.open_count} 笔未结算
          </small>
        </div>
        <div className="text-center">
          <span className={`mb-1 ${insetLabelClasses}`}>已实现净盈亏</span>
          <strong
            className={`block font-mono text-lg font-bold tabular-nums ${pnlToneClass}`}
          >
            {signedMoney(pnl)}
          </strong>
        </div>
        <div className="text-center">
          <span className={`mb-1 ${insetLabelClasses}`}>账户权益</span>
          <strong
            className={`block font-mono text-lg font-bold tabular-nums ${pnlToneClass}`}
          >
            {bankroll.equity.toFixed(2)}
          </strong>
        </div>
        <div className="text-center">
          <span className={`mb-1 ${insetLabelClasses}`}>ROI</span>
          <strong
            className={`block font-mono text-lg font-bold tabular-nums ${pnlToneClass}`}
          >
            {percent(bankroll.roi)}
          </strong>
        </div>
      </div>
    </Card>
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
  const leakage = Boolean(current?.leakage_check?.passed);
  return (
    <section className={tableSectionClasses} aria-label="历史回测">
      <SectionHeader
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
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className={insetPanelClasses}>
                  <small className={insetLabelClasses}>平均 Brier（基线）</small>
                  <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
                    {avg(brierValues)?.toFixed(3) ?? "-"}
                  </strong>
                </div>
                <div className={insetPanelClasses}>
                  <small className={insetLabelClasses}>平均 Brier（集成）</small>
                  <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
                    {avg(ensembleValues)?.toFixed(3) ?? "-"}
                  </strong>
                </div>
                <div className={insetPanelClasses}>
                  <small className={insetLabelClasses}>有效样本窗口</small>
                  <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
                    {windows.length} / {current?.runs ?? 0}
                  </strong>
                </div>
                <div className={insetPanelClasses}>
                  <small className={insetLabelClasses}>泄漏检查</small>
                  <strong
                    className={`mt-1 block font-mono text-lg font-bold tabular-nums ${leakage ? "text-emerald-400" : "text-rose-400"}`}
                  >
                    {leakage ? "通过" : "未通过"}
                  </strong>
                </div>
              </div>
              <div className="rounded-xl border border-slate-800 bg-pitch-950 p-4">
                <svg
                  viewBox={`0 0 ${width} ${height}`}
                  role="img"
                  aria-label="滚动回测 Brier 曲线"
                  preserveAspectRatio="none"
                  className="h-36 w-full"
                >
                  <line
                    x1={pad}
                    y1={height - pad}
                    x2={width - pad}
                    y2={height - pad}
                    className="stroke-slate-700"
                    strokeWidth="1"
                  />
                  {brierValues.length > 1 && (
                    <polyline
                      points={points(brierValues)}
                      className="fill-none stroke-amber-400"
                      strokeWidth="2"
                    />
                  )}
                  {ensembleValues.length > 1 && (
                    <polyline
                      points={points(ensembleValues)}
                      className="fill-none stroke-emerald-400"
                      strokeWidth="2"
                    />
                  )}
                </svg>
                <span className="mt-2 block text-xs text-slate-500">
                  基线 · 集成 双线对比，越低越好
                </span>
              </div>
            </>
          ) : (
            <EmptyState>
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
    <div className="flex justify-end">
      <button
        className="inline-flex items-center rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 font-mono text-xs text-white transition-colors hover:bg-slate-700 disabled:opacity-50"
        type="button"
        onClick={() => exportCsv(filename, rows)}
        disabled={!rows.length}
      >
        导出{label}
      </button>
    </div>
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
      className={tableSectionClasses}
      aria-label="Model Evaluation"
    >
      <SectionHeader
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
            className="grid grid-cols-2 gap-3 md:grid-cols-4"
            aria-label="历史模型评估摘要"
          >
            {reportKeys.map((key) => {
              const report = evaluation.reports[key];
              return (
                <div key={key} className={insetPanelClasses}>
                  <strong className="block font-mono text-sm font-bold text-blue-400">
                    {key}
                  </strong>
                  <span className="mt-1 block font-mono text-xs tabular-nums text-slate-300">
                    {report?.sample_count ?? 0} 个样本
                  </span>
                  <small className="mt-0.5 block text-xs text-slate-500">
                    {report?.confidence ?? "暂无评估"}
                  </small>
                </div>
              );
            })}
          </div>
          <div className="font-mono text-xs tabular-nums text-slate-500">
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
    <section className={tableSectionClasses}>
      <SectionHeader
        eyebrow="STRATEGY LEADERBOARD"
        title="模型策略表现榜"
        meta="ROI · 盈亏 · 样本门禁"
      />
      {strategies.length ? (
        <div className={tableWrapClasses}>
          <div className="overflow-x-auto">
            <table className={tableClasses}>
              <thead>
                <tr className={headRowClasses}>
                  <th className={headCellClasses}>排名</th>
                  <th className={headCellClasses}>模型 / 策略</th>
                  <th className={headCellClasses}>ROI</th>
                  <th className={headCellClasses}>盈亏</th>
                  <th className={headCellClasses}>预测样本</th>
                  <th className={headCellClasses}>Brier</th>
                  <th className={headCellClasses}>Log Loss</th>
                  <th className={headCellClasses}>市场改善</th>
                  <th className={headCellClasses}>回撤</th>
                  <th className={headCellClasses}>状态</th>
                </tr>
              </thead>
              <tbody className={tbodyClasses}>
                {strategies.map((item) => (
                  <tr
                    key={`${item.model_key}-${item.strategy_id}-${item.strategy_version}`}
                    className={rowClasses}
                  >
                    <td className={numberCellClasses}>
                      <strong className="font-black text-slate-100">#{item.rank}</strong>
                    </td>
                    <th scope="row" className={rowHeadClasses}>
                      <b className="block text-xs font-semibold text-slate-100">
                        {item.model_key === "deepseek"
                          ? "DeepSeek"
                          : item.model_key === "chatgpt"
                            ? "GPT-5.6 Sol"
                            : item.model_key}
                      </b>
                      <small className="block text-[11px] text-slate-500">
                        {item.strategy_name} · {item.strategy_version}
                      </small>
                    </th>
                    <td className={moneyClass(item.roi)}>
                      {percent(item.roi)}
                    </td>
                    <td className={moneyClass(item.realized_pnl)}>
                      {signedMoney(item.realized_pnl)}
                    </td>
                    <td className={numberCellClasses}>{item.prediction_samples}</td>
                    <td className={numberCellClasses}>{item.average_brier?.toFixed(3) ?? "-"}</td>
                    <td className={numberCellClasses}>{item.average_log_loss?.toFixed(3) ?? "-"}</td>
                    <td className={numberCellClasses}>{signedMetric(item.brier_improvement)}</td>
                    <td className={numberCellClasses}>{percent(item.max_drawdown)}</td>
                    <td className={cellClasses}>
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
        </div>
      ) : (
        <EmptyState>暂无策略表现样本</EmptyState>
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
    <section className={tableSectionClasses}>
      <SectionHeader
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
          <div className={tableWrapClasses}>
            <div className="overflow-x-auto">
              <table className={tableClasses}>
                <thead>
                  <tr className={headRowClasses}>
                    <th className={headCellClasses}>比赛</th>
                    <th className={headCellClasses}>下注模型</th>
                    <th className={headCellClasses}>策略</th>
                    <th className={headCellClasses}>模型建议</th>
                    <th className={headCellClasses}>候选方向</th>
                    <th className={headCellClasses}>后端状态</th>
                    <th className={headCellClasses}>赔率 / 优势</th>
                    <th className={headCellClasses}>理论仓位</th>
                    <th className={headCellClasses}>原因</th>
                  </tr>
                </thead>
                <tbody className={tbodyClasses}>
                  {visible.map((item) => (
                    <tr key={item.id} className={rowClasses}>
                      <th scope="row" className={rowHeadClasses}>
                        <b className="block text-xs font-semibold text-slate-100">
                          {item.home_team ?? "主队"} vs {item.away_team ?? "客队"}
                        </b>
                        <small className="block text-[11px] text-slate-500">
                          {leagueName(item.league_key)} ·{" "}
                          {item.fixture_date ?? "-"}
                        </small>
                      </th>
                      <th scope="row" className={rowHeadClasses}>
                        <b className="block text-xs font-semibold text-slate-100">{modelLabel(item.model_key, item.model_version)}</b>
                        <small className="block text-[11px] text-slate-500">{item.model_version ?? "版本未知"}</small>
                      </th>
                      <td className={cellClasses}>
                        {item.strategy_name} · {item.strategy_version}
                      </td>
                      <td className={cellClasses}>
                        {item.model_recommendation_status === "bet" ? (
                          <span className="font-semibold text-blue-400">
                            建议下注
                          </span>
                        ) : item.model_recommendation_status === "no_bet" ? (
                          <span className="text-slate-500">建议不下注</span>
                        ) : (
                          "未记录"
                        )}
                      </td>
                      <td className={cellClasses}>
                        {(item.considered_selection ?? item.selection) === "none"
                          ? "-"
                          : selectionLabel(
                              item.considered_selection ?? item.selection,
                              null,
                            )}
                      </td>
                      <td className={cellClasses}>
                        <StatusBadge
                          variant={
                            item.execution_status === "bet"
                              ? "info"
                              : item.execution_status === "no_bet"
                                ? "neutral"
                                : "partial"
                          }
                        >
                          {executionLabel(item.execution_status)}
                        </StatusBadge>
                      </td>
                      <td className={numberCellClasses}>
                        {item.price ? (
                          <>
                            {item.price.toFixed(2)} ·{" "}
                            <span
                              className={
                                item.expected_edge == null
                                  ? ""
                                  : item.expected_edge > 0
                                    ? "font-semibold text-emerald-400"
                                    : item.expected_edge < 0
                                      ? "text-rose-400"
                                      : ""
                              }
                            >
                              {signedMetric(item.expected_edge)}
                            </span>
                          </>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className={numberCellClasses}>{percent(item.stake_fraction)}</td>
                      <td className="max-w-60 px-4 py-3 text-xs text-slate-500">{item.execution_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <Pagination
            page={page}
            pageCount={pageCount}
            onChange={setPage}
            total={decisions.length}
          />
        </>
      ) : (
        <EmptyState>
          暂无可审计的策略决策
        </EmptyState>
      )}
    </section>
  );
}

function EvaluationSummary({ metrics }: { metrics: PredictionMetrics }) {
  const gate = metrics.quality_gate;
  const comparison = metrics.market_comparison;
  const portfolio = metrics.portfolio;
  const gateLabel =
    gate?.status === "READY"
      ? "评估通过"
      : gate?.status === "QUALITY_FAILED"
        ? "质量未通过"
        : "样本不足 · 影子模式";
  const gateToneClass =
    gate?.status === "READY"
      ? "text-emerald-400"
      : gate?.status === "QUALITY_FAILED"
        ? "text-amber-400"
        : "text-white";
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
      className={tableSectionClasses}
      aria-label="策略评估摘要"
    >
      <SectionHeader
        eyebrow="STRATEGY EVALUATION"
        title="策略质量门禁"
        meta={metrics.experiment?.strategy_name ?? "基准策略"}
      />
      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        <div className={insetPanelClasses}>
          <small className={insetLabelClasses}>当前状态</small>
          <strong className={`mt-1 block text-lg font-bold ${gateToneClass}`}>
            {gateLabel}
          </strong>
          <span className={insetHintClasses}>
            {failureLabels.length
              ? failureLabels.join(" · ")
              : "所有评估条件已满足"}
          </span>
        </div>
        <div className={insetPanelClasses}>
          <small className={insetLabelClasses}>CLV 相对收盘价（北极星）</small>
          <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
            {portfolio?.average_clv != null
              ? percent(portfolio.average_clv)
              : "-"}
          </strong>
          <span className={insetHintClasses}>
            {portfolio?.clv_samples ?? 0} 样本 · 长期跑赢收盘价 = 真实优势
          </span>
        </div>
        <div className={insetPanelClasses}>
          <small className={insetLabelClasses}>预测样本</small>
          <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
            {gate?.counts.prediction_samples ?? metrics.sample_size}
          </strong>
          <span className={insetHintClasses}>
            命中 {percent(metrics.accuracy)} · Brier{" "}
            {metrics.average_brier_score?.toFixed(3) ?? "-"}
          </span>
        </div>
        <div className={insetPanelClasses}>
          <small className={insetLabelClasses}>概率质量</small>
          <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
            {metrics.average_log_loss?.toFixed(3) ?? "-"}
          </strong>
          <span className={insetHintClasses}>
            Log Loss · RPS {metrics.average_rps?.toFixed(3) ?? "-"}
          </span>
        </div>
        <div className={insetPanelClasses}>
          <small className={insetLabelClasses}>市场对照</small>
          <strong className="mt-1 block font-mono text-lg font-bold tabular-nums text-white">
            {comparison?.sample_size ?? 0}
          </strong>
          <span className={insetHintClasses}>
            Brier 改善 {signedMetric(comparison?.brier_improvement)}
          </span>
        </div>
        <div className={insetPanelClasses}>
          <small className={insetLabelClasses}>组合表现</small>
          <strong
            className={`mt-1 block font-mono text-lg font-bold tabular-nums ${portfolio ? moneyClass(portfolio.realized_pnl) : "text-white"}`}
          >
            {portfolio ? signedMoney(portfolio.realized_pnl) : "-"}
          </strong>
          <span className={insetHintClasses}>
            ROI {portfolio ? percent(portfolio.roi) : "-"} · 回撤{" "}
            {portfolio ? percent(portfolio.max_drawdown) : "-"}
          </span>
        </div>
      </div>
    </section>
  );
}

function ModelComparisonStrip({
  bankroll,
  selectedModel,
  onSelect,
}: {
  bankroll: BankrollSummary;
  selectedModel: ModelKey;
  onSelect: (key: ModelKey) => void;
}) {
  const accounts: Partial<Record<ModelKey, BankrollSummary>> =
    bankroll.accounts ?? {};
  return (
    <section className={tableSectionClasses} aria-label="模型资金归因">
      <SectionHeader
        eyebrow="MODEL ATTRIBUTION"
        title="模型账户对比"
        meta="点击模型名切换复盘账户 · 盈亏不会混算"
      />
      <div className="grid gap-3 md:grid-cols-2">
        {(["deepseek", "chatgpt"] as ModelKey[]).map((key) => {
          const account = accounts[key];
          const profitable = Boolean(account && account.net_profit > 0);
          return (
            <article
              className={`rounded-2xl border bg-pitch-900 p-4 shadow-xl transition-colors ${
                key === selectedModel
                  ? "border-blue-500/50"
                  : "border-slate-800"
              } ${profitable ? "ring-1 ring-emerald-500/40" : ""}`}
              key={key}
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => onSelect(key)}
                  aria-pressed={key === selectedModel}
                  title="切换到该模型的复盘数据"
                  className={`flex items-center gap-1.5 text-sm font-bold transition-colors ${
                    key === selectedModel
                      ? "text-blue-400"
                      : "text-slate-100 hover:text-blue-400"
                  }`}
                >
                  {modelLabel(key)}
                  {key === selectedModel ? (
                    <Cpu size={13} aria-hidden="true" />
                  ) : null}
                </button>
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
                className={`mt-2 block font-mono text-2xl font-black tabular-nums ${
                  account
                    ? moneyClass(account.net_profit)
                    : "text-slate-300"
                }`}
              >
                {account ? signedMoney(account.net_profit) : "-"}
              </strong>
              <small className="mt-0.5 block text-xs text-slate-500">
                已实现净盈亏 ·{" "}
                {account ? `${account.bet_count} 笔下注` : "尚未开始"}
              </small>
              <dl className="mt-3 grid grid-cols-3 gap-3 border-t border-slate-800/70 pt-3">
                <div>
                  <dt className={insetLabelClasses}>ROI</dt>
                  <dd className={`mt-0.5 font-mono text-sm font-bold tabular-nums ${account ? moneyClass(account.roi) : "text-slate-400"}`}>{account ? percent(account.roi) : "-"}</dd>
                </div>
                <div>
                  <dt className={insetLabelClasses}>权益</dt>
                  <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-slate-200">{account ? account.equity.toFixed(2) : "-"}</dd>
                </div>
                <div>
                  <dt className={insetLabelClasses}>未结</dt>
                  <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-slate-200">{account?.open_count ?? 0}</dd>
                </div>
              </dl>
            </article>
          );
        })}
      </div>
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
  const toneByKey: Record<
    keyof PredictionMetrics["asian_handicap_results"],
    string
  > = {
    full_win: "text-emerald-400",
    half_win: "text-emerald-400",
    push: "text-white",
    half_loss: "text-rose-400",
    full_loss: "text-rose-400",
  };
  return (
    <Card
      className="flex flex-wrap items-center gap-x-8 gap-y-3 p-5"
      aria-label="亚洲盘结算分类"
    >
      <span className="text-[10px] font-bold uppercase tracking-wider font-mono text-blue-400">
        亚洲盘结算
      </span>
      {labels.map(([key, label]) => (
        <div key={key}>
          <small className={insetLabelClasses}>{label}</small>
          <strong
            className={`mt-0.5 block font-mono text-lg font-black tabular-nums ${toneByKey[key]}`}
          >
            {metrics.asian_handicap_results[key]}
          </strong>
        </div>
      ))}
    </Card>
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
    <section className={tableSectionClasses}>
      <SectionHeader
        eyebrow="BANKROLL CURVE"
        title="已实现权益曲线"
        meta={`${points.length} 个节点`}
      />
      <Card className="p-5">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="模拟资金已实现权益曲线"
          preserveAspectRatio="none"
          className="h-40 w-full"
        >
          <line
            x1={padding}
            y1={height - padding}
            x2={width - padding}
            y2={height - padding}
            className="stroke-slate-700"
            strokeWidth="1"
          />
          <polyline
            points={coordinates
              .map((point) => `${point.x},${point.y}`)
              .join(" ")}
            className="fill-none stroke-emerald-400"
            strokeWidth="2"
          />
          {coordinates.map((point, index) => (
            <circle
              key={`${point.x}-${index}`}
              cx={point.x}
              cy={point.y}
              r="4"
              className="fill-emerald-400"
            />
          ))}
        </svg>
        <div className="mt-2 flex items-center justify-between">
          <span className="font-mono text-xs tabular-nums text-slate-500">{minimum.toFixed(2)}</span>
          <strong className="font-mono text-sm font-black tabular-nums text-emerald-400">{values.at(-1)?.toFixed(2)}</strong>
        </div>
      </Card>
    </section>
  );
}

function BetHistory({ bets }: { bets: SimulatedBet[] }) {
  return (
    <section className={tableSectionClasses}>
      <SectionHeader
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
        <div className={tableWrapClasses}>
          <div className="overflow-x-auto">
            <table className={tableClasses}>
              <thead>
                <tr className={headRowClasses}>
                  <th className={headCellClasses}>比赛</th>
                  <th className={headCellClasses}>下注模型</th>
                  <th className={headCellClasses}>市场</th>
                  <th className={headCellClasses}>选择</th>
                  <th className={headCellClasses}>赔率</th>
                  <th className={headCellClasses}>金额</th>
                  <th className={headCellClasses}>状态</th>
                  <th className={headCellClasses}>净盈亏</th>
                  <th className={headCellClasses}>时间</th>
                </tr>
              </thead>
              <tbody className={tbodyClasses}>
                {bets.map((bet) => (
                  <tr key={bet.id} className={rowClasses}>
                    <th scope="row" className={rowHeadClasses}>
                      <b className="block text-xs font-semibold text-slate-100">
                        {bet.home_team} vs {bet.away_team}
                      </b>
                      <small className="block text-[11px] text-slate-500">
                        {leagueName(bet.league_key)} · {bet.fixture_date}
                      </small>
                    </th>
                    <th scope="row" className={rowHeadClasses}>
                      <b className="block text-xs font-semibold text-slate-100">{modelLabel(bet.model_key, bet.model_version)}</b>
                      <small className="block text-[11px] text-slate-500">{bet.model_version}</small>
                    </th>
                    <td className={cellClasses}>{bet.market === "1x2" ? "胜平负" : "亚洲盘"}</td>
                    <td className={cellClasses}>{selectionLabel(bet.selection, bet.handicap_line)}</td>
                    <td className={numberCellClasses}>{bet.odds.toFixed(2)}</td>
                    <td className={numberCellClasses}>{bet.stake.toFixed(2)}</td>
                    <td className={cellClasses}>
                      <StatusBadge
                        variant={
                          bet.status === "voided"
                            ? "neutral"
                            : bet.status === "placed"
                              ? "partial"
                              : bet.settlement_result === "full_win" ||
                                  bet.settlement_result === "half_win"
                                ? "ready"
                                : bet.settlement_result === "half_loss" ||
                                    bet.settlement_result === "full_loss"
                                  ? "danger"
                                  : "neutral"
                        }
                        title={
                          bet.status === "voided"
                            ? "管理员作废：本金已退还模拟账户，不计入盈亏与命中率统计"
                            : undefined
                        }
                      >
                        {bet.status === "voided"
                          ? "已作废"
                          : bet.status === "placed"
                            ? "未结"
                            : settlementLabel(bet.settlement_result)}
                      </StatusBadge>
                    </td>
                    <td className={moneyClass(bet.net_profit ?? 0)}>
                      {bet.status === "voided" ? (
                        <span className="text-slate-500">本金已退还</span>
                      ) : bet.net_profit === null ? (
                        "-"
                      ) : (
                        signedMoney(bet.net_profit)
                      )}
                    </td>
                    <td className={numberCellClasses}>{formatDate(bet.placed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <EmptyState>
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
    <section className={tableSectionClasses}>
      <SectionHeader
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
          <div className={tableWrapClasses}>
            <div className="overflow-x-auto">
              <table className={tableClasses}>
                <thead>
                  <tr className={headRowClasses}>
                    <th className={headCellClasses}>比赛</th>
                    <th className={headCellClasses}>日期</th>
                    <th className={headCellClasses}>联赛</th>
                    <th className={headCellClasses}>预测</th>
                    <th className={headCellClasses}>实际</th>
                    <th className={headCellClasses}>比分</th>
                    <th className={headCellClasses}>正确</th>
                    <th className={headCellClasses}>Brier</th>
                    <th className={headCellClasses}>Log Loss</th>
                    <th className={headCellClasses}>RPS</th>
                    <th className={headCellClasses}>完整度</th>
                    <th className={headCellClasses}>模型 / 版本</th>
                  </tr>
                </thead>
                <tbody className={tbodyClasses}>
                  {visible.map((item) => (
                    <tr key={item.id} className={rowClasses}>
                      <th scope="row" className={rowHeadClasses}>
                        <b className="block text-xs font-semibold text-slate-100">
                          {item.home_team ?? "主队"} vs {item.away_team ?? "客队"}
                        </b>
                      </th>
                      <td className={numberCellClasses}>{item.fixture_date}</td>
                      <td className={cellClasses}>{leagueName(item.league_key)}</td>
                      <td className={cellClasses}>{outcomeLabel(item.predicted_outcome)}</td>
                      <td className={cellClasses}>{outcomeLabel(item.actual_outcome)}</td>
                      <td className={numberCellClasses}>
                        {item.score.home} : {item.score.away}
                      </td>
                      <td className={cellClasses}>
                        <StatusBadge variant={item.correct ? "ready" : "danger"}>
                          {item.correct ? "命中" : "未中"}
                        </StatusBadge>
                      </td>
                      <td className={numberCellClasses}>{item.brier_score.toFixed(3)}</td>
                      <td className={numberCellClasses}>{item.log_loss?.toFixed(3) ?? "-"}</td>
                      <td className={numberCellClasses}>{item.rps?.toFixed(3) ?? "-"}</td>
                      <td className={numberCellClasses}>
                        {item.data_completeness === null ? (
                          "-"
                        ) : (
                          <span
                            className={
                              item.data_completeness >= 0.9
                                ? "text-emerald-400"
                                : item.data_completeness >= 0.6
                                  ? "text-amber-400"
                                  : "text-rose-400"
                            }
                          >
                            {percent(item.data_completeness)}
                          </span>
                        )}
                      </td>
                      <th scope="row" className={rowHeadClasses}>
                        <b className="block text-xs font-semibold text-slate-100">{modelLabel(item.model_key, item.model_version)}</b>
                        <small className="block text-[11px] text-slate-500">{item.model_version}</small>
                      </th>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <Pagination
            page={page}
            pageCount={pageCount}
            onChange={setPage}
            total={metrics.items.length}
          />
        </>
      ) : (
        <EmptyState>
          比赛结束并完成结算后显示预测样本
        </EmptyState>
      )}
    </section>
  );
}

const PAGE_SIZE = 10;

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
  total,
}: {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
  total?: number;
}) {
  if (pageCount <= 1) return null;
  const start = (page - 1) * PAGE_SIZE + 1;
  const end = total === undefined ? page * PAGE_SIZE : Math.min(page * PAGE_SIZE, total);
  return (
    <div className="flex justify-between items-center text-xs font-mono text-slate-500 pt-2">
      <span>
        {total === undefined
          ? `第 ${page} / ${pageCount} 页`
          : `显示第 ${start}-${end} 项，共 ${total} 项`}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="rounded bg-slate-800 px-2.5 py-1 text-slate-400 transition-colors hover:text-white disabled:opacity-40"
        >
          上一页
        </button>
        <span className="tabular-nums">
          {page} / {pageCount}
        </span>
        <button
          type="button"
          disabled={page >= pageCount}
          onClick={() => onChange(page + 1)}
          className="rounded bg-slate-800 px-2.5 py-1 text-slate-400 transition-colors hover:text-white disabled:opacity-40"
        >
          下一页
        </button>
      </div>
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
