"use client";

import { useSyncExternalStore } from "react";

const TICK_MS = 30_000;

function subscribe(onStoreChange: () => void) {
  const timer = setInterval(onStoreChange, TICK_MS);
  return () => clearInterval(timer);
}

function getSnapshot() {
  // 按 30s 取整，保证同一 tick 内快照稳定
  return Math.floor(Date.now() / TICK_MS);
}

function getServerSnapshot() {
  return null;
}

function format(value: Date) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(value);
}

export function SiteClock() {
  const tick = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <span className="font-mono text-xs tabular-nums text-slate-400">
      北京时间 {tick === null ? "--/-- --:--" : format(new Date(tick * TICK_MS))}
    </span>
  );
}
