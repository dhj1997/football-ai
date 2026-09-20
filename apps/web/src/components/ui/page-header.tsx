import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./utils";

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  eyebrow: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, aside, className, ...props }: PageHeaderProps) {
  return (
    <section className={cx("flex flex-wrap items-center justify-between gap-x-6 gap-y-3", className)} {...props}>
      <div className="min-w-0">
        <span className="text-[10px] font-bold uppercase tracking-wider font-mono text-blue-400">{eyebrow}</span>
        <h1 className="mt-0.5 text-lg font-bold text-white">{title}</h1>
        {description ? <p className="mt-0.5 text-xs text-slate-400">{description}</p> : null}
      </div>
      {aside ? <div className="w-full min-w-0 sm:w-auto sm:shrink-0">{aside}</div> : null}
    </section>
  );
}
