import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export type StatusVariant = "ready" | "partial" | "danger" | "info" | "neutral";

export interface StatusBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: StatusVariant;
  icon?: ReactNode;
}

export function StatusBadge({ variant = "neutral", icon, children, className, ...props }: StatusBadgeProps) {
  return (
    <span className={cx("ui-status", `status-${variant}`, className)} {...props}>
      {icon ? <span className="ui-status-icon" aria-hidden="true">{icon}</span> : null}
      {children}
    </span>
  );
}
