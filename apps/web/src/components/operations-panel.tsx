"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeftRight,
  BrainCircuit,
  CalendarDays,
  CheckCircle2,
  Database,
  Flame,
  FlaskConical,
  Gauge,
  Layers3,
  LoaderCircle,
  Play,
  Radio,
  Receipt,
  ShieldAlert,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ErrorState, SectionHeader, StatCard, StatusBadge } from "@/components/ui";
import type { ActivationSourceStatus, ActivationStatus, JobRun } from "@/lib/types";

interface JobConfig {
  key: JobRun["job_name"];
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
}

const jobs: JobConfig[] = [
  { key: "fixtures", label: "赛程", icon: CalendarDays },
  { key: "standings", label: "积分榜", icon: Trophy },
  { key: "analysis", label: "证据与预测", icon: BrainCircuit },
  { key: "settlement", label: "赛后结算", icon: Receipt },
  { key: "dongqiudi_schedule", label: "懂球帝赛程", icon: Radio },
  { key: "dongqiudi_scores", label: "懂球帝比分", icon: Flame },
  { key: "dongqiudi_prematch", label: "懂球帝临场数据", icon: Zap },
  { key: "clubeelo", label: "ClubElo 评级", icon: Gauge },
  { key: "transfers_backfill", label: "转会数据", icon: ArrowLeftRight },
  { key: "player_stats_backfill", label: "球员统计", icon: Users },
  { key: "player_impact_rules", label: "球员影响规则", icon: ShieldAlert },
  { key: "ensemble_learning", label: "集成权重", icon: Layers3 },
  { key: "fd_confirmatory_research", label: "确认性研究", icon: FlaskConical },
];

type JobsPayload = { items?: JobRun[]; enabled?: boolean; analysis_enabled?: boolean; detail?: string };

async function fetchOperationsState() {
  const [jobsResponse, activationResponse] = await Promise.all([
    fetch("/api/admin/jobs", { cache: "no-store" }),
    fetch("/api/admin/activation-status", { cache: "no-store" }),
  ]);
  const jobsPayload = await jobsResponse.json() as JobsPayload;
  const activationPayload = await activationResponse.json() as ActivationStatus & { detail?: string };
  if (!jobsResponse.ok) throw new Error(jobsPayload.detail ?? "作业记录读取失败");
  if (!activationResponse.ok) throw new Error(activationPayload.detail ?? "激活状态读取失败");
  return { jobsPayload, activationPayload };
}

export function OperationsPanel() {
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [activation, setActivation] = useState<ActivationStatus | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [analysisEnabled, setAnalysisEnabled] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { jobsPayload, activationPayload } = await fetchOperationsState();
    setRuns(jobsPayload.items ?? []);
    setEnabled(Boolean(jobsPayload.enabled));
    setAnalysisEnabled(jobsPayload.analysis_enabled !== false);
    setActivation(activationPayload);
  }, []);

  useEffect(() => {
    let active = true;
    void fetchOperationsState()
      .then(({ jobsPayload, activationPayload }) => {
        if (!active) return;
        setRuns(jobsPayload.items ?? []);
        setEnabled(Boolean(jobsPayload.enabled));
        setAnalysisEnabled(jobsPayload.analysis_enabled !== false);
        setActivation(activationPayload);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "运维状态读取失败");
      });
    return () => { active = false; };
  }, []);

  const latest = useMemo(() => new Map(jobs.map((job) => [job.key, runs.find((run) => run.job_name === job.key)])), [runs]);
  const attentionCount = jobs.filter((job) => {
    const status = latest.get(job.key)?.status;
    return status === "failed" || status === "partial";
  }).length;
  const successCount = jobs.filter((job) => latest.get(job.key)?.status === "success").length;

  async function run(jobName: string) {
    setRunning(jobName); setError(null); setMessage(null);
    try {
      const response = await fetch(`/api/admin/jobs/${jobName}`, { method: "POST" });
      const payload = await response.json() as JobRun & { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "作业运行失败");
      await load();
      const job = jobs.find((item) => item.key === jobName);
      setMessage(`${job?.label ?? jobName}已${statusText(payload.status)} · 处理 ${payload.item_count} 项`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "作业运行失败");
    } finally {
      setRunning(null);
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="operations-title">
      <SectionHeader
        eyebrow="PRODUCTION ACTIVATION"
        title="上线激活与常驻作业"
        titleId="operations-title"
        meta={activation ? activationStatusText(activation) : "状态读取中"}
      />
      {error && <ErrorState>{error}</ErrorState>}
      {message && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-300" role="status" aria-live="polite">
          {message}
        </div>
      )}
      {activation && (
        <>
          <div className="grid overflow-hidden rounded-lg border border-slate-800 bg-pitch-900 sm:grid-cols-2 xl:grid-cols-6" aria-label="功能激活摘要">
            <ActivationMetric label="数据库" value={activation.database.backend.toUpperCase()} status={activation.database.status} icon={<Database size={14} />} />
            <ActivationMetric label="备份验证" value={activation.database.backup.status === "verified" ? "已验证" : "未验证"} status={activation.database.backup.status} icon={<CheckCircle2 size={14} />} />
            <ActivationMetric label="球员影响" value={`${activation.player_impact.covered_fixture_count} / ${activation.player_impact.upcoming_fixture_count}`} status={activation.player_impact.status} icon={<ShieldAlert size={14} />} />
            <ActivationMetric label="可用集成" value={String(activation.ensemble.count)} status={activation.ensemble.status} icon={<Layers3 size={14} />} />
            <ActivationMetric label="有效回测" value={String(activation.evaluation.backtests.passing_count)} status={activation.evaluation.backtests.passing_count > 0 ? "ready" : "pending"} icon={<Activity size={14} />} />
            <ActivationMetric label="有效研究" value={String(activation.evaluation.research.passing_count)} status={activation.evaluation.research.passing_count > 0 ? "ready" : "pending"} icon={<FlaskConical size={14} />} />
          </div>
          <div className="grid gap-x-6 gap-y-2 border-y border-slate-800 py-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="数据源状态">
            {activation.providers.sources.map((source) => (
              <div key={source.key} className="flex min-w-0 items-center justify-between gap-3 text-xs">
                <span className="truncate text-slate-300" title={source.label}>{source.label}</span>
                <span className={sourceTone(source)}>{sourceStatusText(source)}</span>
              </div>
            ))}
          </div>
          {(activation.blocking_reasons.length > 0 || activation.attention_reasons.length > 0) && (
            <p className="break-words font-mono text-[11px] text-amber-300/80">
              {[...activation.blocking_reasons, ...activation.attention_reasons].join(" · ")}
            </p>
          )}
        </>
      )}
      <div className="grid grid-cols-3 gap-3" aria-label="自动化健康摘要">
        <StatCard
          label="系统状态"
          value={enabled ? (analysisEnabled ? "运行中" : "预测手动") : "已关闭"}
          icon={<Activity size={14} className={enabled ? "text-emerald-400" : "text-slate-500"} aria-hidden="true" />}
        />
        <StatCard
          label="最近成功"
          value={`${successCount} / ${jobs.length}`}
          icon={<CheckCircle2 size={14} className="text-blue-400" aria-hidden="true" />}
        />
        <StatCard
          label="需关注"
          value={attentionCount}
          valueClassName={attentionCount > 0 ? "text-rose-400" : undefined}
          icon={<AlertTriangle size={14} className={attentionCount > 0 ? "text-rose-400" : "text-slate-500"} aria-hidden="true" />}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {jobs.map((job) => {
          const item = latest.get(job.key);
          const label = job.key === "analysis" && !analysisEnabled ? "证据与预测（手动）" : job.label;
          const Icon = job.icon;
          return (
            <article key={job.key} className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-pitch-900 p-4 shadow-xl">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="grid h-6 w-6 place-items-center rounded-lg bg-slate-800/80 border border-slate-700/60 text-slate-300">
                    <Icon size={13} aria-hidden="true" />
                  </span>
                  <span className="text-xs font-bold text-white">{label}</span>
                </div>
                <StatusBadge variant={statusVariant(item?.status)}>{statusText(item?.status)}</StatusBadge>
              </div>
              <dl className="space-y-1.5 text-[11px] font-mono">
                <div className="flex justify-between gap-2"><dt className="text-slate-500">最近运行</dt><dd className="tabular-nums text-slate-300">{item ? formatDate(item.started_at) : "尚未运行"}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-slate-500">处理</dt><dd className="tabular-nums text-slate-300">{item?.item_count ?? 0}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-slate-500">下次运行</dt><dd className="tabular-nums text-slate-300">{nextRunLabel(item)}</dd></div>
              </dl>
              <p className="line-clamp-2 min-h-8 text-[11px] text-slate-600">{item?.error_summary ?? "没有错误"}</p>
              <button
                type="button"
                title={`立即运行${job.label}`}
                aria-label={`立即运行${job.label}`}
                onClick={() => void run(job.key)}
                disabled={running !== null}
                className="mt-auto grid h-8 w-8 place-items-center self-end rounded-lg border border-slate-700 bg-slate-800 text-slate-200 transition-colors hover:bg-slate-700 disabled:opacity-40"
              >
                {running === job.key ? <LoaderCircle className="animate-spin" size={15} /> : <Play size={15} fill="currentColor" />}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ActivationMetric({ label, value, status, icon }: { label: string; value: string; status: string; icon: ReactNode }) {
  return (
    <div className="min-w-0 border-b border-slate-800 p-3 last:border-b-0 sm:border-r xl:border-b-0">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] text-slate-500">{icon}<span>{label}</span></div>
      <div className="flex items-center justify-between gap-2">
        <strong className="truncate text-sm text-white" title={value}>{value}</strong>
        <span className={`h-2 w-2 shrink-0 rounded-full ${activationTone(status)}`} aria-label={status} />
      </div>
    </div>
  );
}

function activationStatusText(status: ActivationStatus) {
  if (status.mode === "demo") return "演示模式";
  if (status.status === "ready") return "已就绪";
  if (status.status === "blocked") return "部署受阻";
  return "需要关注";
}

function activationTone(status: string) {
  if (["ready", "verified", "ok", "not_applicable"].includes(status)) return "bg-emerald-400";
  if (["failed", "blocked", "invalid"].includes(status)) return "bg-rose-400";
  return "bg-amber-400";
}

function sourceStatusText(source: ActivationSourceStatus) {
  if (source.reason === "provider_required") return "需要数据源";
  return {
    ready: "正常",
    running: "运行中",
    partial: "部分完成",
    failed: "失败",
    not_run: "尚未运行",
    unavailable: "不可用",
  }[source.status];
}

function sourceTone(source: ActivationSourceStatus) {
  if (source.status === "ready") return "shrink-0 text-emerald-400";
  if (source.status === "failed") return "shrink-0 text-rose-400";
  return "shrink-0 text-amber-300";
}

function statusText(status?: JobRun["status"]) { return status ? { running: "运行中", success: "成功", partial: "部分完成", failed: "失败" }[status] : "未运行"; }
function statusVariant(status?: JobRun["status"]) {
  if (status === "success") return "ready" as const;
  if (status === "partial") return "partial" as const;
  if (status === "failed") return "danger" as const;
  if (status === "running") return "info" as const;
  return "neutral" as const;
}
function nextRunLabel(item?: JobRun) {
  const value = item?.result?.next_run;
  return typeof value === "string" ? formatDate(value) : "未提供";
}
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
