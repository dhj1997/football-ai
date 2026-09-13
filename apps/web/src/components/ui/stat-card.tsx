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
    <div className={cx("rounded-xl border border-slate-800 bg-pitch-950 px-3 py-3 text-center", className)} {...props}>
      <span className="block text-[11px] text-slate-500">{label}</span>
      <strong className={cx("mt-1 block font-mono text-xl font-black tabular-nums text-white", valueClassName)}>
        {value}
      </strong>
      {hint ? <small className="mt-0.5 block text-[10px] text-slate-500">{hint}</small> : null}
    </div>
  );
}
