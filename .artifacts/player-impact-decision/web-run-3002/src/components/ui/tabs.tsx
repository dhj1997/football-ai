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
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className,
  itemClassName,
  activeItemClassName = "active",
  orientation = "horizontal",
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
    <div className={cx("ui-tabs", className)} role="tablist" aria-label={ariaLabel} aria-orientation={orientation}>
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
            className={cx(itemClassName, active && activeItemClassName)}
            onClick={() => onChange(item.value)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {item.label}
            {item.badge !== undefined ? <small>{item.badge}</small> : null}
          </button>
        );
      })}
    </div>
  );
}
