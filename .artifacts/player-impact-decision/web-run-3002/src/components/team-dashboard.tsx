"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DataFreshness, EmptyState, ErrorState, LoadingState, SectionHeader, StatusBadge } from "@/components/ui";
import { fetchTeamDetail } from "@/lib/api";
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
    <main className="team-page">
      <DataFreshness
        className="status-strip"
        status={data?.sync_status ?? "unconfigured"}
        label={data ? syncLabel(data.sync_status) : "正在连接球队数据"}
        source={item ? `来源 ${item.source.toUpperCase()} · 更新 ${formatTimestamp(item.updated_at)}` : undefined}
        action={<button className="sync-action" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={13} className={loading ? "spin" : ""} aria-hidden="true" />刷新</button>}
      />

      <Link className="team-back" href="/standings"><ArrowLeft size={15} aria-hidden="true" />返回积分榜</Link>

      {error && <ErrorState className="error-banner team-error">{error}</ErrorState>}

      {loading && !item ? (
        <LoadingState className="team-loading">正在同步球队资料</LoadingState>
      ) : item ? (
        <TeamContent item={item} />
      ) : !error ? (
        <EmptyState className="team-loading">当前没有可显示的球队资料</EmptyState>
      ) : null}
    </main>
  );
}

function TeamContent({ item }: { item: TeamSnapshot }) {
  return (
    <>
      <header className="team-hero">
        {item.team.logo ? <Image src={item.team.logo} alt="" width={72} height={72} unoptimized /> : null}
        <div>
          <span>TEAM DOSSIER · {item.season.name}</span>
          <h1>{item.team.name}</h1>
          <p>{item.team.original_name}</p>
        </div>
        <dl>
          <div><dt>当前排名</dt><dd>{item.team.standing_summary ?? "待更新"}</dd></div>
          <div><dt>主教练</dt><dd>{item.coach?.name ?? "暂无数据"}</dd></div>
          <div><dt>一线队</dt><dd>{item.roster_count} 人</dd></div>
        </dl>
      </header>

      <section className="team-data-section">
        <SectionHeader className="team-section-heading" eyebrow="PLAYER REGISTER" title="当前赛季球员信息" meta={`${item.roster_count} 名 · 出场与技术统计`} />
        <div className="team-table-scroll">
          <table className="roster-table">
            <thead><tr><th>号码</th><th>球员</th><th>位置</th><th>年龄</th><th>出场</th><th>替补</th><th>进球</th><th>助攻</th><th>黄牌</th><th>红牌</th><th>状态</th></tr></thead>
            <tbody>
              {item.roster.map((player) => (
                <tr key={player.id ?? player.original_name}>
                  <td><strong className="shirt-number">{player.number ?? "-"}</strong></td>
                  <th scope="row"><span className="player-name"><b>{player.name}</b><small>{player.nationality ?? "国籍未知"}</small></span></th>
                  <td>{player.position}</td><td>{player.age ?? "-"}</td>
                  <td><strong>{player.statistics.appearances}</strong></td><td>{player.statistics.substitute_appearances}</td>
                  <td>{player.statistics.goals}</td><td>{player.statistics.assists}</td>
                  <td>{player.statistics.yellow_cards}</td><td>{player.statistics.red_cards}</td>
                  <td><StatusBadge className={player.injuries.length ? "player-status injured" : "player-status"} variant={player.injuries.length ? "danger" : "ready"}>{player.injuries.length ? "伤病" : player.status ?? "未知"}</StatusBadge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="team-data-section match-record-section">
        <SectionHeader className="team-section-heading" eyebrow="SEASON RECORD" title="当前赛季比赛记录" meta={`${item.matches.length} 场`} />
        {item.matches.length ? <MatchTable matches={item.matches} /> : <EmptyState className="team-empty">当前赛季暂无比赛记录</EmptyState>}
      </section>
    </>
  );
}

function MatchTable({ matches }: { matches: TeamSeasonMatch[] }) {
  return (
    <div className="team-table-scroll">
      <table className="team-match-table">
        <thead><tr><th>日期</th><th>主队</th><th>比分</th><th>客队</th><th>结果</th><th>状态</th><th>场地</th></tr></thead>
        <tbody>{matches.map((match) => (
          <tr key={match.id}>
            <td>{new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(match.date))}</td>
            <th scope="row">{match.home.name}</th>
            <td><strong>{match.home_score ?? "-"} : {match.away_score ?? "-"}</strong></td>
            <th scope="row">{match.away.name}</th>
            <td><span className={`match-result result-${match.result?.toLowerCase() ?? "pending"}`}>{match.result ?? "-"}</span></td>
            <td>{match.status_text ?? (match.status === "scheduled" ? "未开始" : match.status)}</td>
            <td>{match.venue ?? "-"}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
