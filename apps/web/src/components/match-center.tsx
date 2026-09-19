"use client";

import {
  ArrowLeft,
  Check,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Database,
  LoaderCircle,
  Play,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { RecentFormCompare } from "@/components/recent-form-compare";
import { MarketsDetailPanel } from "@/components/markets-detail-panel";
import { MatchPreviewPanel, OddsMovementPanel } from "@/components/match-preview-panel";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  AnalysisSnapshot,
  DualProbabilityPanels,
  EvidenceDetails,
  PlayerImpactPanel,
  TeamLogo,
  TeamProfiles,
} from "@/components/fixture-workspace";
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  StatusBadge,
  Tabs,
} from "@/components/ui";
import {
  fetchFixtureDetail,
  fetchPredictionMetrics,
  fetchStandings,
  readJson,
} from "@/lib/api";
import { formatHandicapSide } from "@/lib/handicap";
import { canCreatePrediction, deriveMatchReport } from "@/lib/match-report";
import { to_chinese_player_name } from "@/lib/player-names";
import type { FixtureDetail } from "@/lib/types";

type MatchTab =
  "decision" | "models" | "form" | "h2h" | "squads" | "odds" | "teams";

const tabs: Array<{ key: MatchTab; label: string }> = [
  { key: "decision", label: "研究报告" },
  { key: "models", label: "模型明细" },
  { key: "form", label: "近期状态" },
  { key: "h2h", label: "历史交锋" },
  { key: "squads", label: "阵容伤停" },
  { key: "odds", label: "赔率" },
  { key: "teams", label: "球队信息" },
];

const labelClass =
  "text-[11px] font-semibold uppercase tracking-wider text-slate-500";
const innerPanelClass =
  "rounded-xl border border-slate-800 bg-pitch-950 px-3 py-2.5";
const consensusGridClass =
  "grid grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))_minmax(0,1.1fr)] items-center gap-x-3";
const primaryButtonClass =
  "inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-blue-600/30 transition-colors hover:from-blue-500 hover:to-indigo-500 disabled:cursor-not-allowed disabled:opacity-40";

const percent = (value: number | null) =>
  value === null ? "-" : `${Math.round(value * 100)}%`;

function formatKickoff(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatTimestamp(value: string | null) {
  if (!value) return "待同步";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function fixtureState(detail: FixtureDetail) {
  const { fixture } = detail;
  if (fixture.status === "finished") return "完场";
  if (fixture.status === "live") return "进行中";
  if (fixture.status === "postponed") return "延期";
  if (fixture.status === "cancelled") return "取消";
  return fixture.lineup_confirmed ? "首发已确认" : "未开始";
}

function fixtureStatusVariant(detail: FixtureDetail) {
  const { status } = detail.fixture;
  if (status === "finished") return "neutral" as const;
  if (status === "live") return "ready" as const;
  if (status === "postponed" || status === "cancelled") return "danger" as const;
  return "info" as const;
}

function scoreToneClass(self: number, other: number) {
  if (self > other) return "text-rose-400";
  if (self < other) return "text-emerald-400";
  return "text-slate-100";
}

function teamLogoCircle(
  profile: FixtureDetail["context"]["teams"]["home"],
  team: FixtureDetail["fixture"]["home_team"],
  tone: "home" | "away",
) {
  return (
    <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-slate-700 bg-pitch-950">
      <TeamLogo profile={profile ?? {}} team={team} tone={tone} />
    </span>
  );
}

/** 设计稿样式的单行区块标题：mono 大写眉题 + 中文标题 + 右侧备注。 */
function SectionTitle({
  titleId,
  eyebrow,
  title,
  meta,
  className,
}: {
  titleId?: string;
  eyebrow: string;
  title: string;
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-x-4 gap-y-1 ${className ?? ""}`}
    >
      <h3 id={titleId} className="text-xs font-bold uppercase tracking-wider text-slate-400">
        {eyebrow} <span className="ml-1">{title}</span>
      </h3>
      {meta != null ? <span className="text-xs text-slate-500">{meta}</span> : null}
    </div>
  );
}

function useLeagueRanks(detail: FixtureDetail | null) {
  const [ranks, setRanks] = useState<{ home: string; away: string } | null>(
    null,
  );
  const leagueKey = detail?.fixture.league_key;
  const homeName = detail?.fixture.home_team.name;
  const awayName = detail?.fixture.away_team.name;

  useEffect(() => {
    if (!leagueKey) return;
    let active = true;
    void fetchStandings()
      .then((response) => {
        if (!active) return;
        const snapshot = (response.items ?? []).find(
          (item) => item.league_key === leagueKey,
        );
        const rows = snapshot?.standings ?? [];
        const find = (name?: string) => {
          const row = rows.find(
            (item) =>
              name &&
              (item.team.name === name ||
                item.team.name.includes(name) ||
                name.includes(item.team.name)),
          );
          return row ? `联赛第 ${row.rank} 位 · ${row.points} 分` : "暂无排名";
        };
        setRanks({
          home: find(homeName),
          away: find(awayName),
        });
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [leagueKey, homeName, awayName]);

  return ranks;
}

function MatchHeader({
  detail,
  ranks,
  children,
}: {
  detail: FixtureDetail;
  ranks: { home: string; away: string } | null;
  children?: ReactNode;
}) {
  const { fixture, context } = detail;
  const outcome = fixture.score
    ? fixture.score.home > fixture.score.away
      ? "主胜"
      : fixture.score.home < fixture.score.away
        ? "客胜"
        : "平局"
    : null;
  return (
    <Card as="header" className="p-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-slate-300 transition-colors hover:text-blue-400"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          比赛研究台
        </Link>
        <span>{fixture.league.name}</span>
        <span>{fixtureState(detail)}</span>
      </div>
      <div className="mt-6 flex items-center justify-between gap-3 sm:gap-6">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {teamLogoCircle(context.teams.home, fixture.home_team, "home")}
          <span className="min-w-0">
            <strong className="block truncate text-xl font-bold text-white">
              {fixture.home_team.name}
            </strong>
            <small className="text-xs text-slate-400">主队{ranks?.home ? ` · ${ranks.home}` : ""}</small>
          </span>
        </div>
        <div className="flex shrink-0 flex-col items-center gap-1.5 text-center">
          <StatusBadge variant={fixtureStatusVariant(detail)}>
            {fixtureState(detail)}
          </StatusBadge>
          {fixture.score ? (
            <span
              className="font-mono text-4xl font-black tracking-wider text-white tabular-nums"
              aria-label={`${fixture.score.home} 比 ${fixture.score.away}`}
            >
              <span className={scoreToneClass(fixture.score.home, fixture.score.away)}>
                {fixture.score.home}
              </span>
              <span className="mx-1.5 text-slate-600">:</span>
              <span className={scoreToneClass(fixture.score.away, fixture.score.home)}>
                {fixture.score.away}
              </span>
            </span>
          ) : (
            <strong className="font-mono text-4xl font-black tracking-wider text-white tabular-nums">
              {new Intl.DateTimeFormat("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              }).format(new Date(fixture.kickoff))}
            </strong>
          )}
          <small className="font-mono text-xs text-slate-400">
            {outcome ? `${outcome} · ` : ""}
            {formatKickoff(fixture.kickoff)}
          </small>
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-3 text-right">
          <span className="min-w-0">
            <strong className="block truncate text-xl font-bold text-white">
              {fixture.away_team.name}
            </strong>
            <small className="text-xs text-slate-400">客队{ranks?.away ? ` · ${ranks.away}` : ""}</small>
          </span>
          {teamLogoCircle(context.teams.away, fixture.away_team, "away")}
        </div>
      </div>
      <div className="mt-6 border-t border-slate-800/80 pt-6">{children}</div>
    </Card>
  );
}

function evidenceSource(key: string) {
  return ["availability", "lineup", "odds"].includes(key)
    ? "懂球帝"
    : "TheSportsDB";
}

function useModelHitRate() {
  const [hitRate, setHitRate] = useState<{
    accuracy: number;
    samples: number;
  } | null>(null);
  useEffect(() => {
    let active = true;
    void fetchPredictionMetrics("", "chatgpt")
      .then((metrics) => {
        if (active && metrics.sample_size > 0) {
          setHitRate({
            accuracy: metrics.accuracy,
            samples: metrics.sample_size,
          });
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  return hitRate;
}

function DecisionReport({
  detail,
  onManualPredict,
  predicting,
}: {
  detail: FixtureDetail;
  onManualPredict: () => void;
  predicting: boolean;
}) {
  const report = deriveMatchReport(detail);
  const hitRate = useModelHitRate();
  const aggregate = report.models.length
    ? (["home", "draw", "away"] as const).map(
        (key) =>
          report.models.reduce(
            (sum, model) => sum + model.probabilities[key],
            0,
          ) / report.models.length,
      )
    : null;
  const predictedKey = aggregate
    ? (["home", "draw", "away"] as const)[
        aggregate.indexOf(Math.max(...aggregate))
      ]
    : null;
  const outcomeOf = (probabilities: {
    home: number;
    draw: number;
    away: number;
  }) =>
    (["home", "draw", "away"] as const)[
      (
        [probabilities.home, probabilities.draw, probabilities.away] as const
      ).indexOf(
        Math.max(probabilities.home, probabilities.draw, probabilities.away),
      )
    ];
  const baselineProbabilities =
    detail.prediction?.baseline?.probabilities ?? null;
  const baselineKey = baselineProbabilities
    ? outcomeOf(baselineProbabilities)
    : null;
  const modelOutcomes = report.models.map((model) => model.outcome);
  const agreementTag = !modelOutcomes.length
    ? null
    : modelOutcomes.every((key) => key === modelOutcomes[0])
      ? baselineKey && baselineKey !== modelOutcomes[0]
        ? { label: "模型一致 · 基线分歧", tone: "info" }
        : { label: "三方一致", tone: "success" }
      : { label: "存在分歧", tone: "warning" };
  const marketOdds = detail.context.odds;
  const implied = marketOdds
    ? (() => {
        const raw = [
          1 / marketOdds.home,
          1 / marketOdds.draw,
          1 / marketOdds.away,
        ];
        const total = raw[0] + raw[1] + raw[2];
        return raw.map((value) => value / total) as [number, number, number];
      })()
    : null;
  const eligible = canCreatePrediction(detail.fixture);
  const hasEvidence = Boolean(detail.context.synced_at);
  const predictionExists = report.models.length > 0;
  const homeAbsent = detail.context.availability.players
    .filter((player) => player.team === "home")
    .slice(0, 3);
  const awayAbsent = detail.context.availability.players
    .filter((player) => player.team === "away")
    .slice(0, 3);
  const risk =
    report.evidenceQuality < 0.67
      ? {
          label: "高风险",
          tone: "danger",
          note: "关键证据缺口较多，当前仅适合观察。",
        }
      : report.evidenceQuality < 1 || report.agreement === null
        ? {
            label: "中等风险",
            tone: "warning",
            note: "仍有证据待确认，不应视为直接执行信号。",
          }
        : report.agreement < 0.78
          ? {
              label: "模型分歧",
              tone: "danger",
              note: "模型方向或概率差异较大，需要人工复核。",
            }
          : {
              label: "低风险",
              tone: "ready",
              note: "证据完整且模型方向接近，仍需遵守资金纪律。",
            };
  const actionLabel =
    detail.fixture.status === "live"
      ? predictionExists
        ? "按当前赛况重算"
        : "按当前赛况预测"
      : predictionExists
        ? "重新生成"
        : "生成预测";
  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12">
      <div className="flex min-w-0 flex-col gap-6 lg:col-span-8">
        <Card
          className="p-5"
          aria-labelledby="evidence-audit-title"
        >
          <SectionTitle
            className="mb-4"
            eyebrow="01 / EVIDENCE AUDIT"
            title="证据完整度"
            titleId="evidence-audit-title"
            meta="先确认数据，再阅读结论"
          />
          <div className="grid gap-4 md:grid-cols-4">
            <div className="flex flex-col items-center justify-center rounded-xl border border-slate-800 bg-pitch-950 p-4 text-center">
              <strong className="block font-mono text-4xl font-black tabular-nums text-white">
                {report.evidenceReady} / {report.evidenceTotal}
              </strong>
              <span className="mt-1 block text-xs text-slate-400">
                当前证据
                {report.evidenceQuality >= 0.67
                  ? "可用于研究"
                  : "不足以形成判断"}
              </span>
              <div
                className="mt-3 h-1.5 w-full rounded-full bg-slate-800"
                aria-hidden="true"
              >
                <div
                  className="h-1.5 rounded-full bg-emerald-500"
                  style={{ width: percent(report.evidenceQuality) }}
                />
              </div>
              <small className="mt-2 block font-mono text-xs tabular-nums text-emerald-400">
                {percent(report.evidenceQuality)} 已就绪
              </small>
            </div>
            <div className="grid grid-cols-2 content-start gap-3 md:col-span-3 md:grid-cols-3">
              {report.evidence.map((item) => (
                <div
                  key={item.key}
                  className={`rounded-xl border p-3 text-xs ${
                    item.ready
                      ? "border-slate-800 bg-pitch-950"
                      : "border-amber-500/20 bg-amber-500/5"
                  }`}
                >
                  <span className="flex items-center justify-between gap-1.5">
                    <strong className="truncate text-xs font-semibold text-white">
                      {item.label}
                    </strong>
                    <span
                      className={`flex shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] ${
                        item.ready
                          ? "bg-emerald-500/20 text-emerald-400"
                          : "bg-amber-500/20 text-amber-400"
                      }`}
                    >
                      {item.ready ? (
                        <Check size={11} aria-label="已就绪" />
                      ) : (
                        <Clock3 size={11} aria-label="待同步" />
                      )}
                    </span>
                  </span>
                  <strong className="mt-1.5 block text-[11px] font-normal leading-relaxed text-slate-500">
                    {item.detail}
                  </strong>
                  <small className="mt-1 block font-mono text-[10px] text-slate-500">
                    {evidenceSource(item.key)} ·{" "}
                    {formatTimestamp(item.updatedAt)}
                  </small>
                </div>
              ))}
            </div>
          </div>
        </Card>

        {detail.match_preview ? (
          <Card className="p-5" aria-labelledby="preview-context-title">
            <SectionTitle
              className="mb-4"
              eyebrow="01 / PREVIEW"
              title="赛前态势"
              titleId="preview-context-title"
              meta="排名 · 赛程密度 · 赔率走势"
            />
            <MatchPreviewPanel preview={detail.match_preview} fixture={detail.fixture} />
            <div className="mt-4">
              <OddsMovementPanel fixtureId={detail.fixture.id} />
            </div>
          </Card>
        ) : null}

        <Card
          className="p-5"
          aria-labelledby="form-evidence-title"
        >
          <SectionTitle
            className="mb-4"
            eyebrow="02 / RECENT FORM"
            title="近期状态对照"
            titleId="form-evidence-title"
            meta="统一读取最近样本"
          />
          <RecentFormCompare
            homeTeam={{
              name: detail.fixture.home_team.name,
              logo: detail.fixture.home_team.logo ?? null,
              side: "home",
            }}
            awayTeam={{
              name: detail.fixture.away_team.name,
              logo: detail.fixture.away_team.logo ?? null,
              side: "away",
            }}
            recentForm={detail.context.recent_form}
          />
        </Card>

        {detail.prediction?.baseline?.markets_detail ? (
          <Card className="p-5" aria-labelledby="markets-detail-title">
            <SectionTitle
              className="mb-4"
              eyebrow="02B / MARKETS"
              title="进球与比分维度"
              titleId="markets-detail-title"
              meta="基线模型比分矩阵派生"
            />
            <MarketsDetailPanel
              marketsDetail={detail.prediction.baseline.markets_detail}
              currentLine={
                detail.prediction.baseline.asian_handicap?.line != null
                  ? String(detail.prediction.baseline.asian_handicap.line)
                  : null
              }
            />
          </Card>
        ) : null}

        <TeamStatsCard teamStats={detail.context.team_stats} />

        <Card
          className="p-5"
          aria-labelledby="availability-evidence-title"
        >
          <SectionTitle
            className="mb-4"
            eyebrow="03 / AVAILABILITY"
            title="伤停与阵容"
            titleId="availability-evidence-title"
            meta={
              detail.context.lineup.confirmed
                ? "正式首发已确认"
                : "预计阵容 · 开赛前复核"
            }
          />
          <div className="grid gap-3 md:grid-cols-2">
            {[
              {
                name: detail.fixture.home_team.name,
                missing: detail.context.availability.home_missing,
                strength: detail.context.lineup.home_strength,
                players: homeAbsent,
              },
              {
                name: detail.fixture.away_team.name,
                missing: detail.context.availability.away_missing,
                strength: detail.context.lineup.away_strength,
                players: awayAbsent,
              },
            ].map((team) => (
              <div key={team.name} className={innerPanelClass}>
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-sm font-semibold text-white">
                    {team.name}
                  </strong>
                  <span
                    className={`text-xs font-medium ${
                      team.missing ? "text-rose-400" : "text-emerald-400"
                    }`}
                  >
                    {team.missing ? "存在缺阵" : "阵容较完整"}
                  </span>
                </div>
                <dl className="mt-2.5 grid grid-cols-3 gap-2">
                  <div>
                    <dt className="text-[11px] text-slate-500">确认缺阵</dt>
                    <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-white">
                      {team.missing}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-slate-500">阵容强度</dt>
                    <dd className="mt-0.5 font-mono text-sm font-bold tabular-nums text-white">
                      {Math.round(team.strength * 100)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-slate-500">名单状态</dt>
                    <dd className="mt-0.5 text-sm font-semibold text-white">
                      {detail.context.lineup.confirmed ? "正式" : "预计"}
                    </dd>
                  </div>
                </dl>
                <p className="mt-2.5 text-xs leading-relaxed text-slate-400">
                  {team.players.length
                    ? team.players
                        .map((player) => `${to_chinese_player_name(player.name)}（${player.reason}）`)
                        .join("、")
                    : "暂无已确认的关键缺阵球员"}
                </p>
              </div>
            ))}
          </div>
        </Card>

        <Card
          className="p-5"
          aria-labelledby="market-evidence-title"
        >
          <SectionTitle
            className="mb-4"
            eyebrow="04 / MARKET"
            title="赔率与市场"
            titleId="market-evidence-title"
            meta={
              detail.context.odds
                ? `${detail.context.odds.bookmaker} · ${formatTimestamp(detail.context.odds.updated_at)}`
                : "当前不使用估算值"
            }
          />
          {detail.context.odds ? (
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <div className={innerPanelClass}>
                <span className="text-[11px] text-slate-500">主胜</span>
                <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
                  {detail.context.odds.home.toFixed(2)}
                </strong>
              </div>
              <div className={innerPanelClass}>
                <span className="text-[11px] text-slate-500">平局</span>
                <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
                  {detail.context.odds.draw.toFixed(2)}
                </strong>
              </div>
              <div className={innerPanelClass}>
                <span className="text-[11px] text-slate-500">客胜</span>
                <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
                  {detail.context.odds.away.toFixed(2)}
                </strong>
              </div>
              <div className={innerPanelClass}>
                <span className="text-[11px] text-slate-500">亚洲让球</span>
                <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
                  {detail.context.odds.asian_handicap === null
                    ? "-"
                    : formatHandicapSide(
                        detail.context.odds.asian_handicap,
                        "home",
                      )}
                </strong>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
              <CircleAlert
                size={18}
                className="mt-0.5 shrink-0 text-amber-400"
                aria-hidden="true"
              />
              <div>
                <strong className="block font-semibold">即时赔率尚未同步</strong>
                <p className="mt-0.5 text-amber-200/70">
                  当前模型判断不包含市场价格，不会使用估算赔率补齐。
                </p>
              </div>
            </div>
          )}
        </Card>

        <Card
          className="p-5"
          aria-labelledby="model-conclusion-title"
        >
          <SectionTitle
            className="mb-4"
            eyebrow="05 / MODEL CONCLUSION"
            title="模型综合判断"
            titleId="model-conclusion-title"
            meta={
              <>
                基于当前 {report.evidenceReady} 项有效证据
                {hitRate ? (
                  <span className="ml-2 rounded-md bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] tabular-nums text-emerald-400">
                    历史命中率 {percent(hitRate.accuracy)} · {hitRate.samples} 场
                  </span>
                ) : null}
              </>
            }
          />
          {aggregate && predictedKey ? (
            <div className="mb-3 rounded-xl border border-slate-800 bg-pitch-950 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 font-mono text-xs tabular-nums">
                {(["home", "draw", "away"] as const).map((key, index) => (
                  <span
                    key={key}
                    className={
                      key === predictedKey
                        ? "font-bold text-rose-400"
                        : "text-slate-400"
                    }
                  >
                    {key === "home" ? "主胜" : key === "draw" ? "平局" : "客胜"}{" "}
                    {percent(aggregate[index])}
                  </span>
                ))}
              </div>
              <div
                className="mt-2.5 flex h-3 w-full overflow-hidden rounded-full bg-slate-800"
                aria-hidden="true"
              >
                {(["home", "draw", "away"] as const).map((key, index) => {
                  const fallbackIndex = (
                    ["home", "draw", "away"] as const
                  ).filter((outcome) => outcome !== predictedKey).indexOf(key);
                  return (
                    <span
                      key={key}
                      className={
                        key === predictedKey
                          ? "bg-rose-500"
                          : fallbackIndex === 0
                            ? "bg-slate-600"
                            : "bg-slate-700"
                      }
                      style={{ width: percent(aggregate[index]) }}
                    />
                  );
                })}
              </div>
            </div>
          ) : null}
          {detail.prediction?.analysis_summary ? (
            <div className="mb-3 rounded-xl border border-slate-800 bg-pitch-950 p-4 text-xs leading-relaxed text-slate-300">
              <p className="mb-1 font-semibold text-slate-200">分析摘要：</p>
              {detail.prediction.analysis_summary}
            </div>
          ) : null}
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div className={innerPanelClass}>
              <span className={labelClass}>模型共识</span>
              <strong className="mt-1 block text-lg font-bold text-white">
                {report.consensus}
              </strong>
              <p className="mt-1 text-sm leading-relaxed text-slate-400">
                {report.consensusDetail}
              </p>
            </div>
            <dl className="grid content-start gap-2.5 sm:grid-cols-3 lg:grid-cols-1">
              <div className={innerPanelClass}>
                <dt className={labelClass}>一致度</dt>
                <dd className="mt-1 font-mono text-lg font-bold tabular-nums text-white">
                  {percent(report.agreement)}
                </dd>
              </div>
              <div className={innerPanelClass}>
                <dt className={labelClass}>关键变量</dt>
                <dd className="mt-1 text-sm font-semibold text-white">
                  {report.keyVariable}
                </dd>
              </div>
              <div className={innerPanelClass}>
                <dt className={labelClass}>市场观察</dt>
                <dd className="mt-1 text-sm font-semibold text-white">
                  {report.marketWatch}
                </dd>
              </div>
            </dl>
          </div>
          <div
            className="mt-3 overflow-hidden rounded-xl border border-slate-800 bg-pitch-950"
            aria-label="胜平负概率对照"
          >
            <div
              className={`${consensusGridClass} border-b border-slate-800 bg-pitch-950 px-3 py-2 font-mono text-[11px] uppercase tracking-wider text-slate-400`}
              aria-hidden="true"
            >
              <span>模型</span>
              <span>主胜</span>
              <span>平局</span>
              <span>客胜</span>
              <span>判断</span>
            </div>
            {report.models.length ? (
              <div className="divide-y divide-slate-800/60">
                {aggregate && predictedKey ? (
                  <div
                    className={`${consensusGridClass} bg-emerald-500/5 px-3 py-2.5`}
                  >
                    <strong className="text-sm font-semibold text-emerald-400">
                      综合预测
                    </strong>
                    {(["home", "draw", "away"] as const).map((key, index) => (
                      <span key={key}>
                        <b
                          className={`font-mono text-sm tabular-nums ${
                            key === predictedKey
                              ? "font-black text-emerald-400"
                              : "text-slate-300"
                          }`}
                        >
                          {percent(aggregate[index])}
                        </b>
                        <span className="mt-1 block h-1 rounded-full bg-slate-800">
                          <span
                            className={`block h-1 rounded-full ${
                              key === predictedKey
                                ? "bg-emerald-500"
                                : "bg-emerald-500/40"
                            }`}
                            style={{ width: percent(aggregate[index]) }}
                          />
                        </span>
                      </span>
                    ))}
                    <span className="flex flex-wrap items-center gap-1.5">
                      <mark className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-400">
                        {predictedKey === "home"
                          ? "主胜"
                          : predictedKey === "draw"
                            ? "平局"
                            : "客胜"}
                      </mark>
                      {agreementTag ? (
                        <em
                          className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium not-italic ${
                            agreementTag.tone === "success"
                              ? "bg-emerald-500/10 text-emerald-400"
                              : agreementTag.tone === "warning"
                                ? "bg-amber-500/10 text-amber-400"
                                : "bg-blue-500/10 text-blue-400"
                          }`}
                        >
                          {agreementTag.label}
                        </em>
                      ) : null}
                    </span>
                  </div>
                ) : null}
                {implied ? (
                  <div
                    className={`${consensusGridClass} px-3 py-2.5 hover:bg-slate-800/30`}
                  >
                    <strong className="text-sm font-semibold text-slate-300">
                      市场隐含
                    </strong>
                    {(["home", "draw", "away"] as const).map((key, index) => (
                      <span key={key}>
                        <b className="font-mono text-sm tabular-nums text-slate-300">
                          {percent(implied[index])}
                        </b>
                        {aggregate ? (
                          <small
                            className={`ml-1.5 font-mono text-[11px] tabular-nums ${
                              aggregate[index] - implied[index] > 0
                                ? "text-rose-400"
                                : aggregate[index] - implied[index] < 0
                                  ? "text-emerald-400"
                                  : "text-slate-500"
                            }`}
                          >
                            {aggregate[index] - implied[index] > 0 ? "+" : ""}
                            {(
                              (aggregate[index] - implied[index]) *
                              100
                            ).toFixed(1)}
                            %
                          </small>
                        ) : null}
                        <span className="mt-1 block h-1 rounded-full bg-slate-800">
                          <span
                            className="block h-1 rounded-full bg-slate-500"
                            style={{ width: percent(implied[index]) }}
                          />
                        </span>
                      </span>
                    ))}
                    <span>
                      <mark className="rounded-md bg-pitch-800 px-2 py-0.5 text-xs font-medium text-slate-400">
                        去水基准
                      </mark>
                    </span>
                  </div>
                ) : null}
                {report.models.map((model) => (
                  <div
                    className={`${consensusGridClass} px-3 py-2.5 hover:bg-slate-800/30`}
                    key={model.key}
                  >
                    <strong className="truncate text-sm font-semibold text-slate-200">
                      {model.label}
                    </strong>
                    {(["home", "draw", "away"] as const).map((key) => (
                      <span key={key}>
                        <b className="font-mono text-sm tabular-nums text-slate-300">
                          {percent(model.probabilities[key])}
                        </b>
                        <span className="mt-1 block h-1 rounded-full bg-slate-800">
                          <span
                            className="block h-1 rounded-full bg-emerald-500/40"
                            style={{
                              width: percent(model.probabilities[key]),
                            }}
                          />
                        </span>
                      </span>
                    ))}
                    <span>
                      <mark className="rounded-md bg-pitch-800 px-2 py-0.5 text-xs font-medium text-slate-200">
                        {model.outcome === "home"
                          ? "主胜"
                          : model.outcome === "draw"
                            ? "平局"
                            : "客胜"}
                      </mark>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center justify-center gap-2 px-4 py-6 text-sm text-slate-500">
                <Clock3 size={17} aria-hidden="true" />
                暂无当前提示词版本的模型结果
              </div>
            )}
          </div>
          <div className="mt-3 grid gap-2.5 md:grid-cols-3">
            <div className="rounded-xl border border-slate-800 border-l-2 border-l-emerald-500 bg-pitch-950 px-3 py-2.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                支持因素
              </span>
              <p className="mt-1 text-sm leading-relaxed text-slate-300">
                {report.factors.find(
                  (factor) => factor.tone === "home" || factor.tone === "away",
                )?.conclusion ?? "当前没有明显单边优势"}
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 border-l-2 border-l-rose-500 bg-pitch-950 px-3 py-2.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                反对因素
              </span>
              <p className="mt-1 text-sm leading-relaxed text-slate-300">
                {report.models.length > 1 && !report.consensus.includes("一致")
                  ? report.consensusDetail
                  : detail.context.odds
                    ? "市场价格需要结合临场变化复核"
                    : "缺少可验证的即时赔率"}
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 border-l-2 border-l-amber-500 bg-pitch-950 px-3 py-2.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-400">
                待确认项
              </span>
              <p className="mt-1 text-sm leading-relaxed text-slate-300">
                {report.evidence.find((item) => !item.ready)?.label ??
                  "主要证据已就绪"}
              </p>
            </div>
          </div>
          <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-4">
            <div className="flex items-center gap-2.5">
              {eligible ? (
                <Check size={16} className="text-emerald-400" aria-hidden="true" />
              ) : (
                <CircleAlert
                  size={16}
                  className="text-amber-400"
                  aria-hidden="true"
                />
              )}
              <span>
                <strong className="block text-sm font-semibold text-white">
                  {eligible
                    ? detail.fixture.status === "live"
                      ? "进行中仍可生成预测"
                      : "当前可生成预测"
                    : "本场预测已关闭"}
                </strong>
                <small className="block text-xs text-slate-500">
                  {eligible
                    ? "赛中预测只保存版本，不产生新的模拟下注"
                    : "完场、延期或取消状态不可创建新版本"}
                </small>
              </span>
            </div>
            {eligible && (
              <button
                className={primaryButtonClass}
                type="button"
                onClick={onManualPredict}
                disabled={predicting || !hasEvidence}
                title={!hasEvidence ? "等待赛前证据同步" : actionLabel}
              >
                {predicting ? (
                  <LoaderCircle className="animate-spin" size={16} aria-hidden="true" />
                ) : (
                  <Play size={16} fill="currentColor" aria-hidden="true" />
                )}
                {predicting
                  ? "计算中"
                  : !hasEvidence
                    ? "数据待同步"
                    : actionLabel}
              </button>
            )}
          </footer>
        </Card>
      </div>

      <aside
        className="flex min-w-0 flex-col gap-4 lg:col-span-4 lg:sticky lg:top-24 lg:self-start"
        aria-label="研究进度"
      >
        <section>
          <SectionTitle eyebrow="RESEARCH FLOW" title="研究进度" />
          <ol className="mt-3 space-y-2">
            {report.evidence.map((item, index) => (
              <li
                key={item.key}
                className="flex items-center justify-between gap-2.5 rounded-lg border border-slate-800 bg-pitch-950 p-2.5 text-xs"
              >
                <span className="flex min-w-0 items-center gap-2">
                  {item.ready ? (
                    <CheckCircle2
                      size={16}
                      className="shrink-0 text-emerald-400"
                      aria-hidden="true"
                    />
                  ) : (
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500/15 font-mono text-[11px] font-bold tabular-nums text-amber-400">
                      {index + 1}
                    </span>
                  )}
                  <strong
                    className={`truncate font-semibold ${
                      item.ready ? "text-slate-200" : "text-amber-400"
                    }`}
                  >
                    {item.label}
                  </strong>
                </span>
                <small className="shrink-0 text-[11px] text-slate-500">
                  {item.ready ? "已读取" : "待同步"}
                </small>
              </li>
            ))}
            <li className="flex items-center justify-between gap-2.5 rounded-lg border border-slate-800 bg-pitch-950 p-2.5 text-xs">
              <span className="flex min-w-0 items-center gap-2">
                {report.models.length ? (
                  <CheckCircle2
                    size={16}
                    className="shrink-0 text-emerald-400"
                    aria-hidden="true"
                  />
                ) : (
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500/15 font-mono text-[11px] font-bold tabular-nums text-amber-400">
                    7
                  </span>
                )}
                <strong
                  className={`truncate font-semibold ${
                    report.models.length ? "text-slate-200" : "text-amber-400"
                  }`}
                >
                  模型判断
                </strong>
              </span>
              <small className="shrink-0 text-[11px] text-slate-500">
                {report.models.length ? "已生成" : "待生成"}
              </small>
            </li>
          </ol>
        </section>
        <section
          className={`rounded-2xl border p-5 ${
            risk.tone === "danger"
              ? "border-rose-500/20 bg-rose-500/10"
              : risk.tone === "warning"
                ? "border-amber-500/20 bg-amber-500/10"
                : "border-emerald-500/20 bg-emerald-500/10"
          }`}
        >
          <strong
            className={`flex items-center gap-1.5 text-sm font-bold ${
              risk.tone === "danger"
                ? "text-rose-400"
                : risk.tone === "warning"
                  ? "text-amber-400"
                  : "text-emerald-400"
            }`}
          >
            {risk.tone === "ready" ? (
              <ShieldCheck size={15} aria-hidden="true" />
            ) : (
              <CircleAlert size={15} aria-hidden="true" />
            )}
            当前风险：{risk.label}
          </strong>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
            {risk.note}
          </p>
        </section>
        <section className="flex gap-3 rounded-xl border border-slate-800 bg-pitch-950 p-4">
          <Database size={16} className="mt-0.5 shrink-0 text-slate-500" aria-hidden="true" />
          <div className="min-w-0">
            <strong className="block text-sm font-semibold text-slate-200">
              业务数据源
            </strong>
            <p className="mt-0.5 text-xs text-slate-400">TheSportsDB · 懂球帝</p>
            <small className="mt-0.5 block font-mono text-[11px] tabular-nums text-slate-500">
              最近同步 {formatTimestamp(detail.context.synced_at ?? null)}
            </small>
          </div>
        </section>
      </aside>
    </div>
  );
}

function ManualPredictionEmpty({
  detail,
  onManualPredict,
  predicting,
}: {
  detail: FixtureDetail;
  onManualPredict: () => void;
  predicting: boolean;
}) {
  const eligible = canCreatePrediction(detail.fixture);
  const hasEvidence = Boolean(detail.context.synced_at);
  const messages = {
    finished: [
      "比赛已结束，不能重新预测",
      "终场后保留既有版本用于复盘，不再创建新判断。",
    ],
    postponed: ["比赛已延期，等待新赛程", "新开球时间同步后会重新开放预测。"],
    cancelled: [
      "比赛已取消，不能生成预测",
      "取消场次不会进入预测与模拟下注流程。",
    ],
  } as const;
  const blocked = messages[detail.fixture.status as keyof typeof messages];
  const title =
    blocked?.[0] ?? (hasEvidence ? "暂无当前版本预测" : "比赛证据待同步");
  const description =
    blocked?.[1] ??
    (hasEvidence
      ? "可使用当前结构化证据生成两个模型的独立判断。"
      : "近期状态、交锋和伤停就绪后再生成预测。");
  return (
    <EmptyState icon={<Clock3 size={20} aria-hidden="true" />}>
      <strong className="font-display text-base font-bold text-slate-200">
        {title}
      </strong>
      <p className="max-w-md text-center text-sm leading-relaxed text-slate-500">
        {description}
      </p>
      {eligible && (
        <button
          className={primaryButtonClass}
          type="button"
          onClick={onManualPredict}
          disabled={predicting || !hasEvidence}
        >
          {predicting ? (
            <LoaderCircle className="animate-spin" size={13} aria-hidden="true" />
          ) : (
            <Play size={13} fill="currentColor" aria-hidden="true" />
          )}
          {predicting
            ? "计算中"
            : detail.fixture.status === "live"
              ? "按当前赛况预测"
              : "生成预测"}
        </button>
      )}
    </EmptyState>
  );
}

function MatchOdds({ detail }: { detail: FixtureDetail }) {
  const odds = detail.context.odds;
  if (!odds)
    return (
      <EmptyState icon={<CircleAlert size={20} aria-hidden="true" />}>
        <strong className="font-display text-base font-bold text-slate-200">
          暂无可用赛前赔率
        </strong>
        <p className="text-sm text-slate-500">
          系统不会用估算赔率替代缺失的市场数据。
        </p>
      </EmptyState>
    );
  const handicap = odds.asian_handicap;
  return (
    <Card className="p-5" aria-label="赛前赔率">
      <SectionTitle
        className="mb-4"
        eyebrow="PRE-MATCH MARKET"
        title="赛前赔率"
        meta={`${odds.bookmaker} · ${formatTimestamp(odds.updated_at)}`}
      />
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
        <div className={innerPanelClass}>
          <span className="text-[11px] text-slate-500">主胜</span>
          <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
            {odds.home.toFixed(2)}
          </strong>
        </div>
        <div className={innerPanelClass}>
          <span className="text-[11px] text-slate-500">平局</span>
          <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
            {odds.draw.toFixed(2)}
          </strong>
        </div>
        <div className={innerPanelClass}>
          <span className="text-[11px] text-slate-500">客胜</span>
          <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
            {odds.away.toFixed(2)}
          </strong>
        </div>
        {handicap !== null && (
          <>
            <div className={innerPanelClass}>
              <span className="text-[11px] text-slate-500">
                {formatHandicapSide(handicap, "home")}
              </span>
              <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
                {odds.asian_handicap_home_odd?.toFixed(2) ?? "-"}
              </strong>
            </div>
            <div className={innerPanelClass}>
              <span className="text-[11px] text-slate-500">
                {formatHandicapSide(handicap, "away")}
              </span>
              <strong className="mt-0.5 block font-mono text-lg font-bold tabular-nums text-white">
                {odds.asian_handicap_away_odd?.toFixed(2) ?? "-"}
              </strong>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

function VerdictStrip({
  detail,
  ranks,
}: {
  detail: FixtureDetail;
  ranks: { home: string; away: string } | null;
}) {
  const prediction = detail.prediction;
  const report = deriveMatchReport(detail);
  const probabilities: Record<"home" | "draw" | "away", number | undefined> =
    prediction?.probabilities ?? { home: undefined, draw: undefined, away: undefined };
  const pick = (prediction?.forecast?.predicted_outcome ??
    prediction?.predicted_outcome ??
    null) as "home" | "draw" | "away" | null;
  const pickLabel = pick
    ? { home: "主胜", draw: "平局", away: "客胜" }[pick]
    : null;
  const execution = prediction?.execution ?? prediction?.decision;
  const waitingForOdds = (execution?.reason_codes ?? []).some((code) =>
    ["odds_pending", "stale_odds", "odds_age_missing", "odds_age_stale"].includes(code),
  );
  const executionText =
    execution?.status === "bet"
      ? "执行模拟下注"
      : waitingForOdds
        ? "等待赔率刷新"
        : execution?.reason
          ? "暂不下注"
          : "待预测";
  return (
    <div className="grid gap-4 md:grid-cols-3" aria-label="AI 结论速览">
      <div className="rounded-xl border border-slate-800 bg-pitch-950 p-4">
        <small className={labelClass}>AI 综合预测</small>
        <strong className="mt-1.5 block text-lg font-bold text-amber-400">
          {pick && probabilities[pick] != null ? (
            <>
              {pickLabel} ·{" "}
              <span className="font-mono tabular-nums">
                {Math.round(probabilities[pick] * 100)}%
              </span>
              <small className="ml-2 font-mono text-[11px] font-normal tabular-nums text-slate-400">
                主 {Math.round((probabilities.home ?? 0) * 100)}% / 平{" "}
                {Math.round((probabilities.draw ?? 0) * 100)}% / 客{" "}
                {Math.round((probabilities.away ?? 0) * 100)}%
              </small>
            </>
          ) : report.models.length ? (
            <span className="text-slate-500">生成中，暂无结论</span>
          ) : (
            <span className="text-slate-500">暂无预测</span>
          )}
        </strong>
      </div>
      <div className="rounded-xl border border-slate-800 bg-pitch-950 p-4">
        <small className={labelClass}>执行决定</small>
        <strong
          className={`mt-1.5 block text-lg font-bold ${
            execution?.status === "bet" ? "text-rose-400" : "text-slate-400"
          }`}
        >
          {executionText}
        </strong>
      </div>
      <div className="rounded-xl border border-slate-800 bg-pitch-950 p-4">
        <small className={labelClass}>联赛排名</small>
        <strong className="mt-1.5 block text-base font-medium text-slate-200">
          {ranks ? (
            <>
              {detail.fixture.home_team.name}{" "}
              <span className="font-mono tabular-nums">{ranks.home}</span> ·{" "}
              {detail.fixture.away_team.name}{" "}
              <span className="font-mono tabular-nums">{ranks.away}</span>
            </>
          ) : (
            <span className="text-slate-500">读取中</span>
          )}
        </strong>
      </div>
    </div>
  );
}

export function MatchCenter({ fixtureId }: { fixtureId: string }) {
  const [detail, setDetail] = useState<FixtureDetail | null>(null);
  const [activeTab, setActiveTab] = useState<MatchTab>("decision");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [predicting, setPredicting] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchFixtureDetail(fixtureId)
      .then((response) => {
        if (active) setDetail(response);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "比赛详情加载失败",
          );
      });
    return () => {
      active = false;
    };
  }, [fixtureId]);

  // 进行中比赛每 60s 静默刷新比分与状态（不闪加载态）。
  const liveStatus = detail?.fixture.status;
  useEffect(() => {
    if (liveStatus !== "live") return;
    const timer = setInterval(() => {
      void fetchFixtureDetail(fixtureId)
        .then((response) => setDetail(response))
        .catch(() => undefined);
    }, 60_000);
    return () => clearInterval(timer);
  }, [fixtureId, liveStatus]);

  const ranks = useLeagueRanks(detail);

  async function runManualPrediction() {
    if (!detail) return;
    setPredicting(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const response = await fetch("/api/admin/predict", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ fixtureId: detail.fixture.id }),
      });
      const payload = await readJson<{
        detail?: string;
        prediction?: { id?: string };
      }>(response);
      setDetail(await fetchFixtureDetail(detail.fixture.id));
      setActionMessage(
        `双模型预测已更新 ${payload.prediction?.id?.slice(0, 8) ?? ""}`.trim(),
      );
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "手动预测失败");
    } finally {
      setPredicting(false);
    }
  }

  if (error)
    return (
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <ErrorState>
          <strong className="block text-sm font-semibold">
            比赛详情暂不可用
          </strong>
          <span className="mt-0.5 block text-xs opacity-80">{error}</span>
        </ErrorState>
      </main>
    );
  if (!detail)
    return (
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <LoadingState>正在加载比赛研究报告</LoadingState>
      </main>
    );

  const hasPredictions =
    Object.values(detail.predictions ?? {}).some(Boolean) ||
    Boolean(detail.prediction);
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
      <MatchHeader detail={detail} ranks={ranks}>
        <VerdictStrip detail={detail} ranks={ranks} />
      </MatchHeader>
      <div className="sticky top-14 z-30 -mx-4 mt-6 border-b border-slate-800 bg-pitch-900/90 px-4 pb-2 pt-2 backdrop-blur-md">
        <Tabs
          className="w-full border-none bg-transparent p-0"
          ariaLabel="比赛研究页签"
          value={activeTab}
          onChange={setActiveTab}
          items={tabs.map((tab) => ({ value: tab.key, label: tab.label }))}
        />
      </div>
      <div className="mt-5 flex flex-col gap-4">
        {actionError && (
          <div
            className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2.5 text-sm text-rose-300"
            role="alert"
          >
            <CircleAlert size={15} className="shrink-0 text-rose-400" aria-hidden="true" />
            {actionError}
          </div>
        )}
        {actionMessage && (
          <div
            className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-300"
            role="status"
          >
            <ShieldCheck
              size={15}
              className="shrink-0 text-emerald-400"
              aria-hidden="true"
            />
            {actionMessage}
          </div>
        )}
        {activeTab === "decision" && (
          <DecisionReport
            detail={detail}
            onManualPredict={runManualPrediction}
            predicting={predicting}
          />
        )}
        {activeTab === "models" && (
          <div className="flex min-w-0 flex-col gap-5">
            {hasPredictions ? (
              <DualProbabilityPanels
                detail={detail}
                onManualPredict={runManualPrediction}
                predicting={predicting}
              />
            ) : (
              <ManualPredictionEmpty
                detail={detail}
                onManualPredict={runManualPrediction}
                predicting={predicting}
              />
            )}
          </div>
        )}
        {activeTab === "form" && (
          <div className="flex min-w-0 flex-col gap-5">
            <AnalysisSnapshot detail={detail} />
            <EvidenceDetails detail={detail} sections={["form"]} />
          </div>
        )}
        {activeTab === "h2h" && (
          <div className="flex min-w-0 flex-col gap-5">
            <EvidenceDetails detail={detail} sections={["h2h"]} />
          </div>
        )}
        {activeTab === "squads" && (
          <div className="flex min-w-0 flex-col gap-5">
            <EvidenceDetails
              detail={detail}
              sections={["availability", "lineup"]}
            />
            <PlayerImpactPanel detail={detail} />
            <TeamProfiles detail={detail} showProfiles={false} />
          </div>
        )}
        {activeTab === "odds" && <MatchOdds detail={detail} />}
        {activeTab === "teams" && (
          <TeamProfiles detail={detail} showSquads={false} />
        )}
      </div>
    </main>
  );
}

function TeamStatsCard({ teamStats }: { teamStats: FixtureDetail["context"]["team_stats"] }) {
  if (!teamStats) {
    return null;
  }
  const metrics: Array<{ label: string; key: "shots_for" | "shots_on_target_for" | "corners_for" | "goals_for" }> = [
    { label: "场均射门", key: "shots_for" },
    { label: "场均射正", key: "shots_on_target_for" },
    { label: "场均角球", key: "corners_for" },
    { label: "场均进球", key: "goals_for" },
  ];
  return (
    <Card className="p-5" aria-labelledby="team-stats-title">
      <SectionTitle
        className="mb-4"
        eyebrow="02C / TEAM PROFILE"
        title="球队统计画像"
        titleId="team-stats-title"
        meta={`football-data 历史 · 截至 ${teamStats.as_of.slice(0, 10)}`}
      />
      <div className="space-y-3 text-xs">
        {metrics.map((metric) => {
          const home = teamStats.home[metric.key] ?? 0;
          const away = teamStats.away[metric.key] ?? 0;
          const total = home + away || 1;
          return (
            <div key={metric.label}>
              <div className="flex items-baseline justify-between font-mono tabular-nums">
                <span className="font-bold text-slate-200">{home.toFixed(1)}</span>
                <span className="text-[11px] text-slate-500">{metric.label}</span>
                <span className="font-bold text-slate-200">{away.toFixed(1)}</span>
              </div>
              <div className="mt-1 flex h-1.5 gap-0.5" aria-hidden="true">
                <div
                  className="h-1.5 rounded-l-full bg-amber-500/80"
                  style={{ width: `${(home / total) * 100}%` }}
                />
                <div
                  className="h-1.5 flex-1 rounded-r-full bg-sky-500/80"
                  style={{ width: `${(away / total) * 100}%` }}
                />
              </div>
            </div>
          );
        })}
        <p className="text-[11px] text-slate-500">
          主队样本 {teamStats.home.matches} 场 · 客队样本 {teamStats.away.matches} 场
          （football-data 历史场均，仅统计开球前数据）
        </p>
      </div>
    </Card>
  );
}
