import { AlertTriangle } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export interface FeedbackProps extends HTMLAttributes<HTMLDivElement> {
  icon?: ReactNode;
}

/** 加载骨架屏：animate-pulse 色块替代纯文字 Loading，文案仅保留给读屏器。 */
export function LoadingState({ children = "正在加载", icon, className, ...props }: FeedbackProps) {
  return (
    <div
      className={cx("animate-pulse rounded-2xl border border-slate-800 bg-pitch-900 p-6", className)}
      role="status"
      aria-live="polite"
      {...props}
    >
      {icon ? <span className="sr-only">{icon}</span> : null}
      <span className="sr-only">{children}</span>
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-full bg-pitch-800" />
        <div className="flex-1 space-y-2">
          <div className="h-3 w-1/3 rounded bg-pitch-800" />
          <div className="h-3 w-2/3 rounded bg-pitch-800/70" />
        </div>
      </div>
      <div className="mt-4 space-y-2">
        <div className="h-3 w-full rounded bg-pitch-800/70" />
        <div className="h-3 w-5/6 rounded bg-pitch-800/50" />
        <div className="h-3 w-1/2 rounded bg-pitch-800/40" />
      </div>
    </div>
  );
}

export function EmptyState({ children, icon, className, ...props }: FeedbackProps) {
  return (
    <div
      className={cx(
        "flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-slate-700 bg-pitch-900/50 px-6 py-10 text-sm text-slate-400",
        className,
      )}
      {...props}
    >
      {icon ? <span className="text-slate-500" aria-hidden="true">{icon}</span> : null}
      {children}
    </div>
  );
}

export function ErrorState({ children, icon, className, ...props }: FeedbackProps) {
  return (
    <div
      className={cx(
        "flex items-start gap-2.5 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300",
        className,
      )}
      role="alert"
      {...props}
    >
      {icon ?? <AlertTriangle size={16} className="mt-0.5 shrink-0 text-rose-400" aria-hidden="true" />}
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}
