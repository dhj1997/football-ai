"use client";

import { LoaderCircle, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ErrorState, SectionHeader, StatCard, StatusBadge } from "@/components/ui";
import type { JobRun } from "@/lib/types";

const jobs: Array<{ key: JobRun["job_name"]; label: string }> = [
  { key: "fixtures", label: "赛程" },
  { key: "standings", label: "积分榜" },
  { key: "analysis", label: "证据与预测" },
  { key: "settlement", label: "赛后结算" },
  { key: "dongqiudi_schedule", label: "懂球帝赛程" },
  { key: "dongqiudi_scores", label: "懂球帝比分" },
  { key: "dongqiudi_prematch", label: "懂球帝临场数据" },
];

export function OperationsPanel() {
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [analysisEnabled, setAnalysisEnabled] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await fetch("/api/admin/jobs", { cache: "no-store" });
    const payload = await response.json() as { items?: JobRun[]; enabled?: boolean; analysis_enabled?: boolean; detail?: string };
    if (!response.ok) throw new Error(payload.detail ?? "作业记录读取失败");
    setRuns(payload.items ?? []); setEnabled(Boolean(payload.enabled)); setAnalysisEnabled(payload.analysis_enabled !== false);
  }, []);

  useEffect(() => {
    let active = true;
    void fetch("/api/admin/jobs", { cache: "no-store" })
      .then(async (response) => ({ response, payload: await response.json() as { items?: JobRun[]; enabled?: boolean; analysis_enabled?: boolean; detail?: string } }))
      .then(({ response, payload }) => {
        if (!response.ok) throw new Error(payload.detail ?? "作业记录读取失败");
        if (active) { setRuns(payload.items ?? []); setEnabled(Boolean(payload.enabled)); setAnalysisEnabled(payload.analysis_enabled !== false); }
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "作业记录读取失败"); });
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
      <SectionHeader eyebrow="AUTOMATION RUNS" title="常驻作业" titleId="operations-title" meta={enabled ? (analysisEnabled ? "自动运行中" : "自动同步中 · 预测手动") : "自动运行已关闭"} />
      {error && <ErrorState>{error}</ErrorState>}
      {message && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-300" role="status" aria-live="polite">
          {message}
        </div>
      )}
      <div className="grid grid-cols-3 gap-3" aria-label="自动化健康摘要">
        <StatCard label="系统状态" value={enabled ? (analysisEnabled ? "运行中" : "预测手动") : "已关闭"} />
        <StatCard label="最近成功" value={`${successCount} / ${jobs.length}`} />
        <StatCard label="需关注" value={attentionCount} valueClassName={attentionCount > 0 ? "text-rose-400" : undefined} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {jobs.map((job) => {
          const item = latest.get(job.key);
          const label = job.key === "analysis" && !analysisEnabled ? "证据与预测（手动）" : job.label;
          return (
            <article key={job.key} className="flex flex-col gap-3 rounded-2xl border border-slate-800 bg-pitch-900 p-4 shadow-xl">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-white">{label}</span>
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
