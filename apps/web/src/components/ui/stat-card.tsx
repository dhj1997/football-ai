import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  valueClassName?: string;
  icon?: ReactNode;
}

export function StatCard({
  label,
  value,
  hint,
  valueClassName,
  icon,
  className,
  ...props
}: StatCardProps) {
  return (
    <div
      className={cx(
        "relative rounded-xl border border-slate-800 bg-pitch-950 px-3.5 py-3 text-left transition-colors",
        className,
      )}
      {...props}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="block text-[11px] font-medium text-slate-400">{label}</span>
        {icon ? (
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-slate-800/80 text-slate-400 border border-slate-700/50">
            {icon}
          </span>
        ) : null}
      </div>
      <strong
        className={cx(
          "mt-1.5 block font-mono text-xl font-black tabular-nums text-white",
          valueClassName,
        )}
      >
        {value}
      </strong>
      {hint ? (
        <small className="mt-1 block text-[10px] text-slate-500">{hint}</small>
      ) : null}
    </div>
  );
}
