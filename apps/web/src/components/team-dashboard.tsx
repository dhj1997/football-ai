"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DataFreshness, EmptyState, ErrorState, LoadingState, SectionHeader, StatusBadge } from "@/components/ui";
import { fetchTeamDetail } from "@/lib/api";
import { to_chinese_player_name } from "@/lib/player-names";
import type { TeamDetailResponse, TeamSeasonMatch, TeamSnapshot } from "@/lib/types";

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function syncLabel(status: TeamDetailResponse["sync_status"]) {
  return {
    fresh: "球队数据已是最新",
    updated: "球队数据刚刚更新",
    stale: "上游暂不可用，显示最近缓存",
    failed: "球队数据同步失败",
    unconfigured: "球队数据源未配置",
  }[status];
}

export function TeamDashboard({ leagueKey, teamId }: { leagueKey: string; teamId: string }) {
  const [data, setData] = useState<TeamDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchTeamDetail(leagueKey, teamId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "球队数据请求失败");
    } finally {
      setLoading(false);
    }
  }, [leagueKey, teamId]);

  useEffect(() => {
    let active = true;
    void fetchTeamDetail(leagueKey, teamId)
      .then((response) => {
        if (active) setData(response);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "球队数据请求失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [leagueKey, teamId]);

  const item = data?.item ?? null;
  return (
    <main className="mx-auto w-full max-w-[1700px] space-y-6 px-6 pb-16 pt-6">
      <DataFreshness
        status={data?.sync_status ?? "unconfigured"}
        label={data ? syncLabel(data.sync_status) : "正在连接球队数据"}
        source={item ? `来源 ${item.source.toUpperCase()} · 更新 ${formatTimestamp(item.updated_at)}` : undefined}
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

      <Link className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-400 transition-colors hover:text-blue-300" href="/standings">
        <ArrowLeft size={14} aria-hidden="true" />返回积分榜
      </Link>

      {error && <ErrorState>{error}</ErrorState>}

      {loading && !item ? (
        <LoadingState>正在同步球队资料</LoadingState>
      ) : item ? (
        <TeamContent item={item} />
      ) : !error ? (
        <EmptyState>当前没有可显示的球队资料</EmptyState>
      ) : null}
    </main>
  );
}

function TeamContent({ item }: { item: TeamSnapshot }) {
  return (
    <>
      <header className="flex flex-wrap items-center gap-x-8 gap-y-4 rounded-2xl border border-slate-800 bg-pitch-900 p-6 shadow-xl">
        {item.team.logo ? (
          <Image src={item.team.logo} alt="" width={56} height={56} unoptimized className="h-14 w-14 rounded-full border border-slate-700 bg-slate-800 object-contain" />
        ) : (
          <span className="flex h-14 w-14 items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-sm font-bold text-white" aria-hidden="true">
            {item.team.name.charAt(0)}
          </span>
        )}
        <div className="min-w-0">
          <span className="text-[10px] font-bold uppercase tracking-wider font-mono text-blue-400">TEAM DOSSIER · {item.season.name}</span>
          <h1 className="mt-0.5 text-xl font-bold text-white">{item.team.name}</h1>
          <p className="mt-0.5 text-xs text-slate-400">{item.team.original_name}</p>
        </div>
        <dl className="ml-auto grid grid-cols-3 gap-6">
          <div>
            <dt className="text-[11px] text-slate-500">当前排名</dt>
            <dd className="mt-1 text-sm font-bold text-slate-100">{item.team.standing_summary ?? "待更新"}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-slate-500">主教练</dt>
            <dd className="mt-1 text-sm font-bold text-slate-100">{item.coach?.name ?? "暂无数据"}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-slate-500">一线队</dt>
            <dd className="mt-1 font-mono text-sm font-bold tabular-nums text-slate-100">{item.roster_count} 人</dd>
          </div>
        </dl>
      </header>

      <section className="space-y-3">
        <SectionHeader eyebrow="PLAYER REGISTER" title="当前赛季球员信息" meta={`${item.roster_count} 名 · 出场与技术统计`} />
        <div className="overflow-hidden rounded-2xl border border-slate-800 bg-pitch-900 shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-xs font-mono">
              <thead className="border-b border-slate-800 bg-pitch-950 uppercase text-[11px] text-slate-400">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left font-medium">号码</th>
                  <th scope="col" className="px-3 py-3 text-left font-medium">球员</th>
                  <th scope="col" className="px-3 py-3 text-left font-medium">位置</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">年龄</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">出场</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">替补</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">进球</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">助攻</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">黄牌</th>
                  <th scope="col" className="px-3 py-3 text-center font-medium">红牌</th>
                  <th scope="col" className="px-4 py-3 text-center font-medium">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {item.roster.map((player) => {
                  const chineseName = to_chinese_player_name(player.name);
                  return (
                    <tr key={player.id ?? player.original_name} className="transition-colors hover:bg-slate-800/40">
                      <td className="px-4 py-3">
                        <strong className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-slate-700/80 bg-slate-800 text-[11px] font-bold tabular-nums text-slate-300">
                          {player.number ?? "-"}
                        </strong>
                      </td>
                      <th scope="row" className="px-3 py-3 font-normal">
                        <span className="block text-xs font-bold text-white">
                          {chineseName}
                        </span>
                        <small className="block text-[10px] text-slate-500">
                          {player.name !== chineseName ? `${player.name} · ` : ""}{player.nationality ?? "国籍未知"}
                        </small>
                      </th>
                      <td className="px-3 py-3 font-sans text-slate-300">{player.position}</td>
                      <td className="px-3 py-3 text-center tabular-nums text-slate-300">{player.age ? `${player.age}岁` : "-"}</td>
                      <td className="px-3 py-3 text-center font-bold tabular-nums text-white">{player.statistics.appearances}</td>
                      <td className="px-3 py-3 text-center tabular-nums text-slate-400">{player.statistics.substitute_appearances}</td>
                      <td className="px-3 py-3 text-center tabular-nums font-semibold text-emerald-400">{player.statistics.goals}</td>
                      <td className="px-3 py-3 text-center tabular-nums font-semibold text-blue-400">{player.statistics.assists}</td>
                      <td className="px-3 py-3 text-center tabular-nums text-amber-400">{player.statistics.yellow_cards}</td>
                      <td className="px-3 py-3 text-center tabular-nums text-rose-400">{player.statistics.red_cards}</td>
                      <td className="px-4 py-3 text-center">
                        <StatusBadge variant={player.injuries.length ? "danger" : "ready"}>
                          {player.injuries.length ? "伤停" : player.status ?? "正常"}
                        </StatusBadge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <SectionHeader eyebrow="SEASON RECORD" title="当前赛季比赛记录" meta={`${item.matches.length} 场`} />
        {item.matches.length ? <MatchTable matches={item.matches} /> : <EmptyState>当前赛季暂无比赛记录</EmptyState>}
      </section>
    </>
  );
}

const resultClasses: Record<string, string> = {
  win: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  draw: "bg-slate-800 text-slate-400 border border-slate-700",
  loss: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
};

function MatchTable({ matches }: { matches: TeamSeasonMatch[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800 bg-pitch-900 shadow-xl">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-xs font-mono">
          <thead className="border-b border-slate-800 bg-pitch-950 uppercase text-[11px] text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-medium">日期</th>
              <th scope="col" className="px-3 py-3 text-left font-medium">主队</th>
              <th scope="col" className="px-3 py-3 text-center font-medium">比分</th>
              <th scope="col" className="px-3 py-3 text-left font-medium">客队</th>
              <th scope="col" className="px-3 py-3 text-center font-medium">结果</th>
              <th scope="col" className="px-3 py-3 text-center font-medium">状态</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">场地</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {matches.map((match) => (
              <tr key={match.id} className="transition-colors hover:bg-slate-800/30">
                <td className="px-4 py-3 tabular-nums text-slate-400">{new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(match.date))}</td>
                <th scope="row" className="px-3 py-3 font-sans font-bold text-white">{match.home.name}</th>
                <td className="px-3 py-3 text-center">
                  <strong className="font-black tabular-nums text-white">{match.home_score ?? "-"} : {match.away_score ?? "-"}</strong>
                </td>
                <th scope="row" className="px-3 py-3 font-sans font-bold text-white">{match.away.name}</th>
                <td className="px-3 py-3 text-center">
                  <span className={`inline-block rounded-md px-2 py-0.5 text-[11px] font-medium ${resultClasses[match.result?.toLowerCase() ?? ""] ?? "bg-slate-800 text-slate-400 border border-slate-700"}`}>
                    {match.result ?? "-"}
                  </span>
                </td>
                <td className="px-3 py-3 text-center font-sans text-slate-400">{match.status_text ?? (match.status === "scheduled" ? "未开始" : match.status)}</td>
                <td className="px-4 py-3 font-sans text-slate-400">{match.venue ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
