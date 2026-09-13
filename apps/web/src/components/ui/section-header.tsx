import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export interface SectionHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  eyebrow: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  level?: 2 | 3;
  titleId?: string;
}

export function SectionHeader({ eyebrow, title, meta, level = 2, titleId, className, ...props }: SectionHeaderProps) {
  const headingClass = "mt-0.5 text-base font-bold text-white";
  const heading = level === 3
    ? <h3 id={titleId} className={headingClass}>{title}</h3>
    : <h2 id={titleId} className={headingClass}>{title}</h2>;
  return (
    <div className={cx("flex flex-wrap items-end justify-between gap-x-4 gap-y-1", className)} {...props}>
      <div>
        <span className="text-[10px] font-bold uppercase tracking-wider font-mono text-blue-400">{eyebrow}</span>
        {heading}
      </div>
      {meta ? <small className="shrink-0 font-mono text-[11px] text-slate-500">{meta}</small> : null}
    </div>
  );
}
