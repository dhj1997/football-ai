import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  valueClassName?: string;
}

export function StatCard({ label, value, hint, valueClassName, className, ...props }: StatCardProps) {
  return (
    <div className={cx("ui-stat-card", className)} {...props}>
      <span>{label}</span>
      <strong className={valueClassName}>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}
