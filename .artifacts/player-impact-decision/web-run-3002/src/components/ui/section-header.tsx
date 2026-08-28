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
  const heading = level === 3 ? <h3 id={titleId}>{title}</h3> : <h2 id={titleId}>{title}</h2>;
  return (
    <div className={cx("ui-section-header", className)} {...props}>
      <div><span>{eyebrow}</span>{heading}</div>
      {meta ? <small>{meta}</small> : null}
    </div>
  );
}
