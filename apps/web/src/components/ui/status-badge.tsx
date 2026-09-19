import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export type StatusVariant = "ready" | "partial" | "danger" | "info" | "neutral" | "live";

const variantClasses: Record<StatusVariant, string> = {
  ready: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  partial: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  danger: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  info: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  neutral: "bg-slate-800 text-slate-400 border-slate-700",
  live: "bg-rose-500/15 text-rose-300 border-rose-500/40",
};

export interface StatusBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: StatusVariant;
  icon?: ReactNode;
}

export function StatusBadge({ variant = "neutral", icon, children, className, ...props }: StatusBadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        variantClasses[variant],
        className,
      )}
      {...props}
    >
      {variant === "live" ? (
        <span aria-hidden="true" className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-rose-400" />
        </span>
      ) : icon ? (
        <span aria-hidden="true">{icon}</span>
      ) : null}
      {children}
    </span>
  );
}
