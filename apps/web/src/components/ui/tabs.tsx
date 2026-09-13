"use client";

import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { cx } from "./utils";

export interface TabItem<T extends string = string> {
  value: T;
  label: ReactNode;
  badge?: ReactNode;
  disabled?: boolean;
}

export interface TabsProps<T extends string = string> {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
  itemClassName?: string;
  activeItemClassName?: string;
  orientation?: "horizontal" | "vertical";
  /** pill: 深色胶囊组（次级筛选）；solid: 蓝色实心胶囊（主分类切换） */
  variant?: "pill" | "solid";
}

const containerByVariant = {
  pill: "inline-flex flex-wrap items-center gap-1 bg-pitch-950 p-1 rounded-xl border border-slate-800",
  solid: "flex flex-wrap items-center gap-2",
} as const;

const itemByVariant = {
  pill: "px-3.5 py-1.5 text-xs font-medium rounded-lg border border-transparent text-slate-400 transition-colors hover:text-slate-200 disabled:opacity-40 whitespace-nowrap",
  solid: "px-4 py-2 text-xs font-semibold rounded-xl border border-slate-800 bg-pitch-950 text-slate-400 transition-colors hover:text-white disabled:opacity-40 whitespace-nowrap",
} as const;

const activeByVariant = {
  pill: "bg-slate-800 text-blue-400 font-semibold border-slate-700",
  solid: "bg-blue-600 text-white font-bold border-transparent shadow-md shadow-blue-600/30",
} as const;

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className,
  itemClassName,
  activeItemClassName,
  orientation = "horizontal",
  variant = "pill",
}: TabsProps<T>) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  function focusTab(index: number) {
    const enabled = items.map((item, itemIndex) => ({ item, itemIndex })).filter(({ item }) => !item.disabled);
    if (!enabled.length) return;
    const current = enabled.findIndex(({ item }) => item.value === value);
    const next = enabled.findIndex(({ itemIndex }) => itemIndex === index);
    const target = next >= 0 ? next : Math.max(current, 0);
    tabRefs.current[enabled[target].itemIndex]?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const previousKey = orientation === "vertical" ? "ArrowUp" : "ArrowLeft";
    const nextKey = orientation === "vertical" ? "ArrowDown" : "ArrowRight";
    const enabledIndexes = items.map((item, itemIndex) => ({ item, itemIndex })).filter(({ item }) => !item.disabled).map(({ itemIndex }) => itemIndex);
    if (!enabledIndexes.length) return;
    const current = enabledIndexes.indexOf(index);
    let target = -1;
    if (event.key === previousKey || (orientation === "horizontal" && event.key === "ArrowUp")) target = enabledIndexes[(current - 1 + enabledIndexes.length) % enabledIndexes.length];
    if (event.key === nextKey || (orientation === "horizontal" && event.key === "ArrowDown")) target = enabledIndexes[(current + 1) % enabledIndexes.length];
    if (event.key === "Home") target = enabledIndexes[0];
    if (event.key === "End") target = enabledIndexes.at(-1) ?? -1;
    if (target < 0) return;
    event.preventDefault();
    focusTab(target);
  }

  return (
    <div className={cx(containerByVariant[variant], className)} role="tablist" aria-label={ariaLabel} aria-orientation={orientation}>
      {items.map((item, index) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            ref={(node) => { tabRefs.current[index] = node; }}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={item.disabled}
            className={cx(
              itemByVariant[variant],
              itemClassName,
              active && (activeItemClassName ?? activeByVariant[variant]),
            )}
            onClick={() => onChange(item.value)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {item.label}
            {item.badge !== undefined ? (
              <small className={cx("rounded-sm px-1.5 py-px font-mono text-[10px] tabular-nums", active ? "bg-blue-500/20 text-blue-300" : "bg-pitch-800 text-slate-400")}>
                {item.badge}
              </small>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
