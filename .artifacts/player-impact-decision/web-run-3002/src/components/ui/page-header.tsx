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
    <section className={cx("ui-page-header", className)} {...props}>
      <div>
        <span>{eyebrow}</span>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {aside ? <div className="ui-page-header-aside">{aside}</div> : null}
    </section>
  );
}
