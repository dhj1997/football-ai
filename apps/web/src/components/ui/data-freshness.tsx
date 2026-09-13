import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export type DataFreshnessStatus = "fresh" | "updated" | "stale" | "failed" | "unconfigured";

const dotClasses: Record<DataFreshnessStatus, string> = {
  fresh: "bg-emerald-400",
  updated: "bg-emerald-400",
  stale: "bg-amber-400",
  failed: "bg-rose-400",
  unconfigured: "bg-slate-500",
};

export interface DataFreshnessProps extends HTMLAttributes<HTMLDivElement> {
  status: DataFreshnessStatus;
  label: ReactNode;
  source?: ReactNode;
  updatedAt?: ReactNode;
  action?: ReactNode;
}

export function DataFreshness({ status, label, source, updatedAt, action, className, ...props }: DataFreshnessProps) {
  return (
    <div
      className={cx(
        "flex flex-wrap items-center gap-x-3 gap-y-1 self-start rounded-full border border-slate-800 bg-pitch-900 px-4 py-2 text-xs text-slate-400",
        className,
      )}
      role="status"
      {...props}
    >
      <span className="flex items-center gap-2 font-medium text-slate-200">
        <i className={cx("h-2 w-2 animate-pulse rounded-full", dotClasses[status])} aria-hidden="true" />
        {label}
      </span>
      {source ? <span className="font-mono text-[11px]">{source}</span> : null}
      {updatedAt ? <span className="font-mono text-[11px] tabular-nums">{updatedAt}</span> : null}
      {action ? <span className="ml-auto">{action}</span> : null}
    </div>
  );
}
