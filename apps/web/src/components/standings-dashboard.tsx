"use client";

import Image from "next/image";
import Link from "next/link";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchStandings } from "@/lib/api";
import type { LeagueSnapshot, StandingsResponse } from "@/lib/types";

const leagueOrder = ["epl", "laliga", "csl"] as const;

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
    <main className="standings-page">
      <div className={`status-strip sync-${data?.sync_status ?? "unconfigured"}`} role="status">
        <span><i aria-hidden="true" />{data ? syncLabel(data.sync_status) : "正在连接积分数据"}</span>
        <span className="status-note">来源 ESPN · 更新 {formatTimestamp(data?.last_synced_at ?? null)}</span>
        <button className="sync-action" type="button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={13} className={loading ? "spin" : ""} aria-hidden="true" />刷新
        </button>
      </div>

      <section className="workspace-title">
        <div>
          <span>LEAGUE TABLES</span>
          <h1>三联赛积分榜</h1>
          <p>当前赛季排名与积分</p>
        </div>
        {selected && (
          <div className="today-stamp">
            <span><small>当前赛季</small><strong>{selected.season.name}</strong></span>
          </div>
        )}
      </section>

      <div className="filter-band standings-filter" aria-label="选择联赛">
        <div className="league-filter">
          {leagueOrder.map((leagueKey) => {
            const snapshot = snapshots.get(leagueKey);
            return (
              <button
                key={leagueKey}
                type="button"
                className={selectedLeague === leagueKey ? "active" : undefined}
                aria-pressed={selectedLeague === leagueKey}
                onClick={() => setSelectedLeague(leagueKey)}
              >
                {snapshot?.league_name ?? { epl: "英超", laliga: "西甲", csl: "中超" }[leagueKey]}
                <small>{snapshot?.team_count ?? 0}</small>
              </button>
            );
          })}
        </div>
        <span className="standings-freshness">{selected ? `${selected.source.toUpperCase()} · ${formatTimestamp(selected.updated_at)}` : "等待数据"}</span>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />{error}
        </div>
      )}

      <section className="standings-board" aria-live="polite">
        {loading && !selected ? (
          <div className="loading-state"><RefreshCw className="spin" size={18} aria-hidden="true" />正在同步积分榜</div>
        ) : selected ? (
          <StandingsTable snapshot={selected} />
        ) : (
          <div className="standings-empty">当前没有可显示的积分数据</div>
        )}
      </section>
    </main>
  );
}

function StandingsTable({ snapshot }: { snapshot: LeagueSnapshot }) {
  return (
    <div className="standings-table-scroll">
      <table className="standings-table">
        <thead>
          <tr>
            <th scope="col">排名</th>
            <th scope="col">球队</th>
            <th scope="col">赛</th>
            <th scope="col">胜</th>
            <th scope="col">平</th>
            <th scope="col">负</th>
            <th scope="col">进球</th>
            <th scope="col">失球</th>
            <th scope="col">净胜</th>
            <th scope="col">积分</th>
          </tr>
        </thead>
        <tbody>
          {snapshot.standings.map((row) => (
            <tr key={`${snapshot.league_key}-${row.team.provider_id ?? row.team.original_name}`}>
              <td><strong className="standing-rank">{row.rank}</strong></td>
              <th scope="row">
                <span className="standing-team">
                  {row.team.logo ? (
                    <Image src={row.team.logo} alt="" width={30} height={30} unoptimized />
                  ) : (
                    <span aria-hidden="true">{row.team.code}</span>
                  )}
                  <Link href={`/teams/${snapshot.league_key}/${row.team.provider_id}`}>
                    <b>{row.team.name}</b><small>{row.team.original_name}</small>
                  </Link>
                </span>
              </th>
              <td>{row.played}</td>
              <td>{row.wins}</td>
              <td>{row.draws}</td>
              <td>{row.losses}</td>
              <td>{row.goals_for}</td>
              <td>{row.goals_against}</td>
              <td className={row.goal_difference > 0 ? "positive" : row.goal_difference < 0 ? "negative" : undefined}>
                {row.goal_difference > 0 ? "+" : ""}{row.goal_difference}
              </td>
              <td><strong className="standing-points">{row.points}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
