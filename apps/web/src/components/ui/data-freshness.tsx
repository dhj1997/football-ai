import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export type DataFreshnessStatus = "fresh" | "updated" | "stale" | "failed" | "unconfigured";

export interface DataFreshnessProps extends HTMLAttributes<HTMLDivElement> {
  status: DataFreshnessStatus;
  label: ReactNode;
  source?: ReactNode;
  updatedAt?: ReactNode;
  action?: ReactNode;
}

export function DataFreshness({ status, label, source, updatedAt, action, className, ...props }: DataFreshnessProps) {
  return (
    <div className={cx("data-freshness", `sync-${status}`, className)} role="status" {...props}>
      <span className="data-freshness-label"><i className="data-freshness-dot" aria-hidden="true" />{label}</span>
      {source ? <span className="status-note">{source}</span> : null}
      {updatedAt ? <span className="data-freshness-time">{updatedAt}</span> : null}
      {action ? <span className="data-freshness-action">{action}</span> : null}
    </div>
  );
}
