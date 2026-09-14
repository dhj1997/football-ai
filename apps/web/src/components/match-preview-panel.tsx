"use client";

import { useEffect, useState } from "react";

import type { MarketReport, MatchPreview } from "@/lib/types";

function PositionRow({
  label,
  name,
  position,
  gap,
}: {
  label: string;
  name: string;
  position: MatchPreview["positions"]["home"];
  gap: number | null;
}) {
  return (
    <div className="flex min-w-0 items-baseline justify-between gap-3">
      <span className="min-w-0 truncate text-sm font-semibold text-slate-100">
        <small className="mr-1.5 rounded bg-pitch-800 px-1.5 py-0.5 text-[10px] font-normal text-slate-400">
          {label}
        </small>
        {name}
      </span>
      {position ? (
        <span className="shrink-0 font-mono text-xs tabular-nums text-slate-300">
          第 <b className="text-base font-black text-amber-400">{position.rank}</b> 位 ·{" "}
          {position.points} 分 / {position.played} 轮
          <small className="ml-1.5 text-slate-500">（净胜 {position.goal_difference ?? 0}）</small>
        </span>
      ) : (
        <span className="shrink-0 text-xs text-slate-500">无积分榜数据</span>
      )}
      {gap !== null ? null : null}
    </div>
  );
}

function UpcomingList({ rows }: { rows: MatchPreview["upcoming"]["home"] }) {
  if (!rows.length) {
    return <p className="text-[11px] text-slate-500">暂无后续赛程</p>;
  }
  return (
    <ul className="space-y-1">
      {rows.map((row) => (
        <li key={row.fixture_id} className="flex items-baseline justify-between gap-2 text-[11px]">
          <span className="min-w-0 truncate text-slate-300">
            <span className="mr-1 font-mono text-slate-500">
              {row.kickoff.slice(5, 10).replace("-", "/")}
            </span>
            {row.is_home ? "主" : "客"} vs {row.opponent}
          </span>
          <span className="shrink-0 font-mono tabular-nums text-slate-500">
            {row.rest_days !== null ? `间隔 ${row.rest_days} 天` : "—"}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function MatchPreviewPanel({
  preview,
  fixture,
}: {
  preview: MatchPreview | null | undefined;
  fixture: { home_team: { name: string }; away_team: { name: string }; kickoff: string };
}) {
  if (!preview) {
    return null;
  }
  const home = preview.positions.home;
  const away = preview.positions.away;
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-pitch-950 p-3">
        <div className="space-y-2">
          <PositionRow label="主" name={fixture.home_team.name} position={home} gap={preview.rank_gap} />
          <div className="h-px bg-slate-800/70" aria-hidden="true" />
          <PositionRow label="客" name={fixture.away_team.name} position={away} gap={preview.rank_gap} />
        </div>
        {preview.rank_gap !== null && home && away ? (
          <p className="mt-2 text-[11px] text-slate-500">
            排名相差 <b className="font-mono text-slate-300">{preview.rank_gap}</b> 位
            {home.rank && away.rank && home.rank < away.rank
              ? `（${fixture.home_team.name} 领先）`
              : home.rank && away.rank && away.rank < home.rank
                ? `（${fixture.away_team.name} 领先）`
                : ""}
          </p>
        ) : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-pitch-950 p-3">
          <b className="mb-2 block truncate text-xs font-semibold text-slate-200">
            {fixture.home_team.name} · 未来三场
          </b>
          <UpcomingList rows={preview.upcoming.home} />
        </div>
        <div className="rounded-xl border border-slate-800 bg-pitch-950 p-3">
          <b className="mb-2 block truncate text-xs font-semibold text-slate-200">
            {fixture.away_team.name} · 未来三场
          </b>
          <UpcomingList rows={preview.upcoming.away} />
        </div>
      </div>
    </div>
  );
}

function OddsMovementRow({
  selection,
  timeline,
}: {
  selection: string;
  timeline: { opening: { decimal_odds: number | null; captured_at: string | null } | null; current: { decimal_odds: number | null; captured_at: string | null } | null; movement: { absolute: number; relative: number | null; direction: string } | null };
}) {
  const opening = timeline.opening?.decimal_odds;
  const current = timeline.current?.decimal_odds;
  const direction = timeline.movement?.direction;
  const tone =
    direction === "down"
      ? "text-emerald-400"
      : direction === "up"
        ? "text-rose-400"
        : "text-slate-400";
  const label = { home: "主胜", draw: "平局", away: "客胜" }[selection] ?? selection;
  return (
    <div className="flex items-baseline justify-between gap-2 font-mono text-xs tabular-nums">
      <span className="w-10 shrink-0 text-slate-400">{label}</span>
      <span className="text-slate-500">{opening ? opening.toFixed(2) : "—"}</span>
      <span aria-hidden="true" className={tone}>
        {direction === "down" ? "↓" : direction === "up" ? "↑" : "→"}
      </span>
      <span className="font-bold text-slate-200">{current ? current.toFixed(2) : "—"}</span>
      <span className={`w-16 shrink-0 text-right ${tone}`}>
        {timeline.movement
          ? `${timeline.movement.absolute > 0 ? "+" : ""}${(timeline.movement.absolute * 100).toFixed(1)}%`
          : ""}
      </span>
      <span className="w-24 shrink-0 truncate text-right text-[10px] text-slate-600">
        {timeline.current?.captured_at ? `更新 ${timeline.current.captured_at.slice(5, 16).replace("T", " ")}` : ""}
      </span>
    </div>
  );
}

export function OddsMovementPanel({ fixtureId }: { fixtureId: string }) {
  const [report, setReport] = useState<MarketReport | null>(null);
  useEffect(() => {
    let active = true;
    fetch(`/api/backend/fixtures/${fixtureId}/market`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data: MarketReport | null) => {
        if (active) setReport(data);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [fixtureId]);
  if (!report || !report.quote_count) {
    return null;
  }
  const section = report.markets["1x2"];
  const timelines = section?.timelines;
  const hasMovement = Object.values(timelines ?? {}).some(
    (timeline) => timeline.movement && timeline.movement.absolute !== 0,
  );
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-slate-500">
        开盘 → 当前（{hasMovement ? "有变动" : "暂无变动"}）
        {section?.consensus
          ? ` · 市场共识：主 ${Math.round((section.consensus.consensus_probabilities.home ?? 0) * 100)}% / 平 ${Math.round(
              (section.consensus.consensus_probabilities.draw ?? 0) * 100,
            )}% / 客 ${Math.round((section.consensus.consensus_probabilities.away ?? 0) * 100)}%`
          : ""}
      </p>
      <div className="space-y-1.5 rounded-xl border border-slate-800 bg-pitch-950 px-3 py-2.5">
        {(["home", "draw", "away"] as const).map((selection) =>
          timelines?.[selection] ? (
            <OddsMovementRow key={selection} selection={selection} timeline={timelines[selection]} />
          ) : null,
        )}
      </div>
    </div>
  );
}
