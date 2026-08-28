import { AlertTriangle, LoaderCircle } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export interface FeedbackProps extends HTMLAttributes<HTMLDivElement> {
  icon?: ReactNode;
}

export function LoadingState({ children = "正在加载", icon, className, ...props }: FeedbackProps) {
  return <div className={cx("ui-feedback", "ui-loading", className)} role="status" aria-live="polite" {...props}>{icon ?? <LoaderCircle className="spin" size={18} aria-hidden="true" />}{children}</div>;
}

export function EmptyState({ children, icon, className, ...props }: FeedbackProps) {
  return <div className={cx("ui-feedback", "ui-empty", className)} {...props}>{icon ?? null}{children}</div>;
}

export function ErrorState({ children, icon, className, ...props }: FeedbackProps) {
  return <div className={cx("ui-feedback", "ui-error", className)} role="alert" {...props}>{icon ?? <AlertTriangle size={16} aria-hidden="true" />}{children}</div>;
}
