"use client";

import Image from "next/image";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DataFreshness, EmptyState, ErrorState, LoadingState, Tabs } from "@/components/ui";
import { fetchStandings } from "@/lib/api";
import type { LeagueSnapshot, StandingsResponse } from "@/lib/types";

const leagueOrder = ["epl", "laliga", "csl"] as const;

const RELEGATION_COUNT = 3;
const UCL_COUNT = 4;

function formatTimestamp(value: string | null) {
  if (!value) return "尚未同步";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function syncLabel(status: StandingsResponse["sync_status"]) {
  return {
    fresh: "积分数据已是最新",
    updated: "积分数据刚刚更新",
    stale: "上游暂不可用，显示最近缓存",
    failed: "积分数据同步失败",
    unconfigured: "积分数据源未配置",
  }[status];
}

type Zone = "ucl" | "relegation" | null;

function zoneOf(rank: number, total: number): Zone {
  if (rank <= UCL_COUNT) return "ucl";
  if (rank > total - RELEGATION_COUNT) return "relegation";
  return null;
}

export function StandingsDashboard() {
  const [data, setData] = useState<StandingsResponse | null>(null);
  const [selectedLeague, setSelectedLeague] = useState<(typeof leagueOrder)[number]>("epl");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchStandings());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "积分数据请求失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void fetchStandings()
      .then((response) => {
        if (active) setData(response);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "积分数据请求失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const snapshots = useMemo(
    () => new Map((data?.items ?? []).map((item) => [item.league_key, item])),
    [data],
  );
  const selected = snapshots.get(selectedLeague) ?? null;

  return (
    <main className="mx-auto w-full max-w-[1700px] space-y-6 px-6 pb-16 pt-6">
      <DataFreshness
        status={data?.sync_status ?? "unconfigured"}
        label={data ? syncLabel(data.sync_status) : "正在连接积分数据"}
        source={selected ? `来源 ${selected.source.toUpperCase()} · ${formatTimestamp(selected.updated_at)}` : `来源 ESPN · 更新 ${formatTimestamp(data?.last_synced_at ?? null)}`}
        action={
          <button
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs text-slate-200 transition-colors hover:bg-slate-700"
            type="button"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} aria-hidden="true" />刷新
          </button>
        }
      />

      <div className="flex flex-col justify-between gap-4 rounded-2xl border border-slate-800 bg-pitch-900 p-5 shadow-xl md:flex-row md:items-center" aria-label="选择联赛">
        <Tabs
          variant="solid"
          ariaLabel="选择联赛"
          value={selectedLeague}
          onChange={setSelectedLeague}
          items={leagueOrder.map((leagueKey) => {
            const snapshot = snapshots.get(leagueKey);
            return { value: leagueKey, label: snapshot?.league_name ?? { epl: "英超", laliga: "西甲", csl: "中超" }[leagueKey], badge: snapshot?.team_count ?? 0 };
          })}
        />
        <span className="font-mono text-xs tabular-nums text-slate-400">
          {selected ? `${selected.season.name} · ${formatTimestamp(selected.updated_at)}` : "等待数据"}
        </span>
      </div>

      {error && <ErrorState>{error}</ErrorState>}

      <section aria-live="polite">
        {loading && !selected ? (
          <LoadingState>正在同步积分榜</LoadingState>
        ) : selected ? (
          <StandingsTable snapshot={selected} />
        ) : (
          <EmptyState>当前没有可显示的积分数据</EmptyState>
        )}
      </section>
    </main>
  );
}

function zoneRowClass(zone: Zone) {
  if (zone === "ucl") return "border-l-2 border-l-emerald-500";
  if (zone === "relegation") return "border-l-2 border-l-rose-500";
  return "border-l-2 border-l-transparent";
}

function rankClass(zone: Zone) {
  if (zone === "ucl") return "text-emerald-400";
  if (zone === "relegation") return "text-rose-400";
  return "text-slate-300";
}

function pointsClass(zone: Zone) {
  if (zone === "ucl") return "text-emerald-400";
  if (zone === "relegation") return "text-rose-400";
  return "text-white";
}

function countClass(value: number, tone: "win" | "draw" | "loss") {
  if (value <= 0) return "text-slate-500";
  return tone === "win" ? "text-emerald-400" : tone === "draw" ? "text-amber-400" : "text-rose-400";
}

function TeamBadge({ logo, code, name }: { logo?: string | null; code?: string | null; name: string }) {
  if (logo) {
    return <Image src={logo} alt="" width={24} height={24} unoptimized className="h-6 w-6 shrink-0 rounded-full border border-slate-700 bg-slate-800 object-contain" />;
  }
  return (
    <span
      aria-hidden="true"
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-[10px] font-bold text-slate-300"
    >
      {(code ?? name).charAt(0).toUpperCase()}
    </span>
  );
}

function StandingsTable({ snapshot }: { snapshot: LeagueSnapshot }) {
  const total = snapshot.standings.length;
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-pitch-900 shadow-xl">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead className="border-b border-slate-800 bg-pitch-950 font-mono uppercase text-[11px] text-slate-400">
            <tr>
              <th scope="col" className="w-12 whitespace-nowrap px-4 py-3.5 text-center font-medium">排名</th>
              <th scope="col" className="px-4 py-3.5 font-medium">球队</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">赛</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">胜</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">平</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">负</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">进球</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">失球</th>
              <th scope="col" className="px-3 py-3.5 text-center font-medium">净胜</th>
              <th scope="col" className="px-4 py-3.5 text-center font-bold text-white">积分</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-medium">
            {snapshot.standings.map((row) => {
              const zone = zoneOf(row.rank, total);
              return (
                <tr
                  key={`${snapshot.league_key}-${row.team.provider_id ?? row.team.original_name}`}
                  className={`transition-colors hover:bg-slate-800/30 ${zoneRowClass(zone)}`}
                >
                  <td className={`px-4 py-3 text-center font-mono font-bold tabular-nums ${rankClass(zone)}`}>
                    {String(row.rank).padStart(2, "0")}
                  </td>
                  <th scope="row" className="px-4 py-3 font-normal">
                    <span className="flex items-center gap-3">
                      <TeamBadge logo={row.team.logo} code={row.team.code} name={row.team.name} />
                      <Link href={`/teams/${snapshot.league_key}/${row.team.provider_id}`} className="group">
                        <b className="block text-sm font-bold text-white group-hover:text-blue-400">{row.team.name}</b>
                        <small className="block text-[10px] text-slate-500">{row.team.original_name}</small>
                      </Link>
                    </span>
                  </th>
                  <td className="px-3 py-3 text-center font-mono tabular-nums text-slate-300">{row.played}</td>
                  <td className={`px-3 py-3 text-center font-mono tabular-nums ${countClass(row.wins, "win")}`}>{row.wins}</td>
                  <td className={`px-3 py-3 text-center font-mono tabular-nums ${countClass(row.draws, "draw")}`}>{row.draws}</td>
                  <td className={`px-3 py-3 text-center font-mono tabular-nums ${countClass(row.losses, "loss")}`}>{row.losses}</td>
                  <td className="px-3 py-3 text-center font-mono tabular-nums text-slate-300">{row.goals_for}</td>
                  <td className="px-3 py-3 text-center font-mono tabular-nums text-slate-300">{row.goals_against}</td>
                  <td className={`px-3 py-3 text-center font-mono tabular-nums ${row.goal_difference > 0 ? "text-emerald-400" : row.goal_difference < 0 ? "text-rose-400" : "text-slate-500"}`}>
                    {row.goal_difference > 0 ? "+" : ""}{row.goal_difference}
                  </td>
                  <td className={`px-4 py-3 text-center font-mono text-lg font-bold tabular-nums ${pointsClass(zone)}`}>
                    {row.points}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap justify-between items-center gap-2 border-t border-slate-800 bg-pitch-950 p-4 font-mono text-xs text-slate-500">
        <div className="flex flex-wrap gap-4">
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" /> 欧战区 (1-{UCL_COUNT})</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-rose-500" aria-hidden="true" /> 降级区 (末{RELEGATION_COUNT}名)</span>
        </div>
        <span>来源 {snapshot.source.toUpperCase()} · {snapshot.team_count} 支球队</span>
      </div>
    </div>
  );
}
