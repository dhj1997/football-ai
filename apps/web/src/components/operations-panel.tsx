"use client";

import { AlertTriangle, LoaderCircle, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { JobRun } from "@/lib/types";

const jobs: Array<{ key: JobRun["job_name"]; label: string }> = [
  { key: "fixtures", label: "赛程" },
  { key: "standings", label: "积分榜" },
  { key: "analysis", label: "证据与预测" },
  { key: "settlement", label: "赛后结算" },
];

export function OperationsPanel() {
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await fetch("/api/admin/jobs", { cache: "no-store" });
    const payload = await response.json() as { items?: JobRun[]; enabled?: boolean; detail?: string };
    if (!response.ok) throw new Error(payload.detail ?? "作业记录读取失败");
    setRuns(payload.items ?? []); setEnabled(Boolean(payload.enabled));
  }, []);

  useEffect(() => {
    let active = true;
    void fetch("/api/admin/jobs", { cache: "no-store" })
      .then(async (response) => ({ response, payload: await response.json() as { items?: JobRun[]; enabled?: boolean; detail?: string } }))
      .then(({ response, payload }) => {
        if (!response.ok) throw new Error(payload.detail ?? "作业记录读取失败");
        if (active) { setRuns(payload.items ?? []); setEnabled(Boolean(payload.enabled)); }
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "作业记录读取失败"); });
    return () => { active = false; };
  }, []);

  const latest = useMemo(() => new Map(jobs.map((job) => [job.key, runs.find((run) => run.job_name === job.key)])), [runs]);

  async function run(jobName: string) {
    setRunning(jobName); setError(null);
    try {
      const response = await fetch(`/api/admin/jobs/${jobName}`, { method: "POST" });
      const payload = await response.json() as JobRun & { detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "作业运行失败");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "作业运行失败");
    } finally {
      setRunning(null);
    }
  }

  return (
    <section className="operations-panel" aria-labelledby="operations-title">
      <div className="team-section-heading">
        <div><span>AUTOMATION RUNS</span><h2 id="operations-title">常驻作业</h2></div>
        <small>{enabled ? "自动运行中" : "自动运行已关闭"}</small>
      </div>
      {error && <div className="error-banner" role="alert"><AlertTriangle size={16} />{error}</div>}
      <div className="operations-grid">
        {jobs.map((job) => {
          const item = latest.get(job.key);
          return <article key={job.key}>
            <div><span>{job.label}</span><strong className={`run-${item?.status ?? "none"}`}>{statusText(item?.status)}</strong></div>
            <dl><div><dt>最近运行</dt><dd>{item ? formatDate(item.started_at) : "尚未运行"}</dd></div><div><dt>处理</dt><dd>{item?.item_count ?? 0}</dd></div></dl>
            <p>{item?.error_summary ?? "没有错误"}</p>
            <button type="button" title={`立即运行${job.label}`} aria-label={`立即运行${job.label}`} onClick={() => void run(job.key)} disabled={running !== null}>{running === job.key ? <LoaderCircle className="spin" size={15} /> : <Play size={15} fill="currentColor" />}</button>
          </article>;
        })}
      </div>
    </section>
  );
}

function statusText(status?: JobRun["status"]) { return status ? { running: "运行中", success: "成功", partial: "部分完成", failed: "失败" }[status] : "未运行"; }
function formatDate(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
