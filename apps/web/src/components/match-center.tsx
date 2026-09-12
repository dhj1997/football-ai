"use client";

import {
  ArrowLeft,
  BarChart3,
  CalendarDays,
  Check,
  CircleAlert,
  Clock3,
  Database,
  Gauge,
  HeartPulse,
  LoaderCircle,
  MapPin,
  Play,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

import {
  AnalysisSnapshot,
  DualProbabilityPanels,
  EvidenceDetails,
  PlayerImpactPanel,
  Scoreline,
  TeamLogo,
  TeamProfiles,
} from "@/components/fixture-workspace";
import { Tabs } from "@/components/ui";
import {
  fetchFixtureDetail,
  fetchPredictionMetrics,
  fetchStandings,
  readJson,
} from "@/lib/api";
import { formatHandicapSide } from "@/lib/handicap";
import { canCreatePrediction, deriveMatchReport } from "@/lib/match-report";
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

function MatchHeader({ detail }: { detail: FixtureDetail }) {
  const { fixture, context } = detail;
  const outcome = fixture.score
    ? fixture.score.home > fixture.score.away
      ? "主胜"
      : fixture.score.home < fixture.score.away
        ? "客胜"
        : "平局"
    : null;
  return (
    <header className="match-center-header research-match-header">
      <div className="match-breadcrumb">
        <Link href="/">
          <ArrowLeft size={15} aria-hidden="true" />
          比赛研究台
        </Link>
        <span>{fixture.league.name}</span>
        <span>{fixtureState(detail)}</span>
      </div>
      <div className="match-center-scoreboard">
        <div className="match-side home">
          <TeamLogo
            profile={context.teams.home ?? {}}
            team={fixture.home_team}
            tone="home"
          />
          <strong>{fixture.home_team.name}</strong>
          <small>主队</small>
        </div>
        <div className="match-score">
          <span className={`match-state ${fixture.status}`}>
            {fixtureState(detail)}
          </span>
          {fixture.score ? (
            <Scoreline
              home={fixture.score.home}
              away={fixture.score.away}
              large
            />
          ) : (
            <strong>
              {new Intl.DateTimeFormat("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              }).format(new Date(fixture.kickoff))}
            </strong>
          )}
          <small>{outcome ?? "北京时间"}</small>
        </div>
        <div className="match-side away">
          <TeamLogo
            profile={context.teams.away ?? {}}
            team={fixture.away_team}
            tone="away"
          />
          <strong>{fixture.away_team.name}</strong>
          <small>客队</small>
        </div>
      </div>
      <div className="match-meta">
        <span>
          <CalendarDays size={14} aria-hidden="true" />
          {formatKickoff(fixture.kickoff)}
        </span>
        <span>
          <MapPin size={14} aria-hidden="true" />
          {fixture.venue || "场地待定"}
        </span>
        <span>
          <Database size={14} aria-hidden="true" />
          {context.synced_at
            ? `数据 ${formatTimestamp(context.synced_at)}`
            : "数据待同步"}
        </span>
      </div>
    </header>
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
    <div className="evidence-first-layout">
      <div className="evidence-first-main">
        <section
          className="evidence-workbench-block evidence-audit"
          aria-labelledby="evidence-audit-title"
        >
          <header className="evidence-block-heading">
            <div>
              <span>01 / EVIDENCE AUDIT</span>
              <h2 id="evidence-audit-title">证据完整度</h2>
            </div>
            <small>先确认数据，再阅读结论</small>
          </header>
          <div className="evidence-audit-body">
            <div className="evidence-audit-score">
              <strong>
                {report.evidenceReady} / {report.evidenceTotal}
              </strong>
              <span>
                当前证据
                {report.evidenceQuality >= 0.67
                  ? "可用于研究"
                  : "不足以形成判断"}
              </span>
              <i aria-hidden="true">
                <em style={{ width: percent(report.evidenceQuality) }} />
              </i>
              <small>{percent(report.evidenceQuality)} 已就绪</small>
            </div>
            <div className="evidence-source-grid">
              {report.evidence.map((item) => (
                <div
                  className={item.ready ? "ready" : "waiting"}
                  key={item.key}
                >
                  <span>
                    {item.ready ? (
                      <Check size={14} aria-label="已就绪" />
                    ) : (
                      <Clock3 size={14} aria-label="待同步" />
                    )}
                    {item.label}
                  </span>
                  <strong>{item.detail}</strong>
                  <small>
                    {evidenceSource(item.key)} ·{" "}
                    {formatTimestamp(item.updatedAt)}
                  </small>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section
          className="evidence-workbench-block"
          aria-labelledby="form-evidence-title"
        >
          <header className="evidence-block-heading">
            <div>
              <span>02 / RECENT FORM</span>
              <h2 id="form-evidence-title">近期状态对照</h2>
            </div>
            <small>统一读取最近样本</small>
          </header>
          <div className="form-evidence-grid">
            {[
              {
                name: detail.fixture.home_team.name,
                side: "主队",
                ppg: detail.context.recent_form.home_points_per_game ?? 0,
                matches: detail.context.recent_form.home,
              },
              {
                name: detail.fixture.away_team.name,
                side: "客队",
                ppg: detail.context.recent_form.away_points_per_game ?? 0,
                matches: detail.context.recent_form.away,
              },
            ].map((team) => (
              <div key={team.side}>
                <header>
                  <span>{team.side}</span>
                  <strong>{team.name}</strong>
                  <small>{team.matches.length} 场样本</small>
                </header>
                <div>
                  <b>{team.ppg.toFixed(2)}</b>
                  <span>场均积分</span>
                  <i aria-hidden="true">
                    <em
                      style={{
                        width: `${Math.min(100, (team.ppg / 3) * 100)}%`,
                      }}
                    />
                  </i>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section
          className="evidence-workbench-block"
          aria-labelledby="availability-evidence-title"
        >
          <header className="evidence-block-heading">
            <div>
              <span>03 / AVAILABILITY</span>
              <h2 id="availability-evidence-title">伤停与阵容</h2>
            </div>
            <small>
              {detail.context.lineup.confirmed
                ? "正式首发已确认"
                : "预计阵容 · 开赛前复核"}
            </small>
          </header>
          <div className="availability-evidence-grid">
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
              <div key={team.name}>
                <div className="availability-team-title">
                  <strong>{team.name}</strong>
                  <span>{team.missing ? "存在缺阵" : "阵容较完整"}</span>
                </div>
                <dl>
                  <div>
                    <dt>确认缺阵</dt>
                    <dd>{team.missing}</dd>
                  </div>
                  <div>
                    <dt>阵容强度</dt>
                    <dd>{Math.round(team.strength * 100)}%</dd>
                  </div>
                  <div>
                    <dt>名单状态</dt>
                    <dd>{detail.context.lineup.confirmed ? "正式" : "预计"}</dd>
                  </div>
                </dl>
                <p>
                  {team.players.length
                    ? team.players
                        .map((player) => `${player.name}（${player.reason}）`)
                        .join("、")
                    : "暂无已确认的关键缺阵球员"}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section
          className="evidence-workbench-block"
          aria-labelledby="market-evidence-title"
        >
          <header className="evidence-block-heading">
            <div>
              <span>04 / MARKET</span>
              <h2 id="market-evidence-title">赔率与市场</h2>
            </div>
            <small>
              {detail.context.odds
                ? `${detail.context.odds.bookmaker} · ${formatTimestamp(detail.context.odds.updated_at)}`
                : "当前不使用估算值"}
            </small>
          </header>
          {detail.context.odds ? (
            <div className="market-evidence-grid">
              <div>
                <span>主胜</span>
                <strong>{detail.context.odds.home.toFixed(2)}</strong>
              </div>
              <div>
                <span>平局</span>
                <strong>{detail.context.odds.draw.toFixed(2)}</strong>
              </div>
              <div>
                <span>客胜</span>
                <strong>{detail.context.odds.away.toFixed(2)}</strong>
              </div>
              <div>
                <span>亚洲让球</span>
                <strong>
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
            <div className="market-evidence-empty">
              <CircleAlert size={18} aria-hidden="true" />
              <div>
                <strong>即时赔率尚未同步</strong>
                <p>当前模型判断不包含市场价格，不会使用估算赔率补齐。</p>
              </div>
            </div>
          )}
        </section>

        <section
          className="evidence-workbench-block model-conclusion"
          aria-labelledby="model-conclusion-title"
        >
          <header className="evidence-block-heading">
            <div>
              <span>05 / MODEL CONCLUSION</span>
              <h2 id="model-conclusion-title">模型综合判断</h2>
            </div>
            <small>
              基于当前 {report.evidenceReady} 项有效证据
              {hitRate ? (
                <span className="hit-rate-badge">
                  历史命中率 {percent(hitRate.accuracy)} · {hitRate.samples} 场
                </span>
              ) : null}
            </small>
          </header>
          <div className="model-conclusion-summary">
            <div>
              <span>模型共识</span>
              <strong>{report.consensus}</strong>
              <p>{report.consensusDetail}</p>
            </div>
            <dl>
              <div>
                <dt>一致度</dt>
                <dd>{percent(report.agreement)}</dd>
              </div>
              <div>
                <dt>关键变量</dt>
                <dd>{report.keyVariable}</dd>
              </div>
              <div>
                <dt>市场观察</dt>
                <dd>{report.marketWatch}</dd>
              </div>
            </dl>
          </div>
          <div
            className="consensus-board evidence-consensus"
            aria-label="胜平负概率对照"
          >
            <div className="consensus-columns" aria-hidden="true">
              <span>模型</span>
              <span>主胜</span>
              <span>平局</span>
              <span>客胜</span>
              <span>判断</span>
            </div>
            {report.models.length ? (
              <div className="consensus-rows">
                {aggregate && predictedKey ? (
                  <div className="consensus-row consensus-prediction">
                    <strong>综合预测</strong>
                    {(["home", "draw", "away"] as const).map((key, index) => (
                      <span
                        key={key}
                        className={
                          key === predictedKey ? "predicted" : undefined
                        }
                      >
                        <b>{percent(aggregate[index])}</b>
                        <i>
                          <em
                            style={
                              {
                                "--report-probability": percent(
                                  aggregate[index],
                                ),
                              } as CSSProperties
                            }
                          />
                        </i>
                      </span>
                    ))}
                    <mark className="prediction-mark">
                      {predictedKey === "home"
                        ? "主胜"
                        : predictedKey === "draw"
                          ? "平局"
                          : "客胜"}
                    </mark>
                    {agreementTag ? (
                      <em className={`agreement-tag ${agreementTag.tone}`}>
                        {agreementTag.label}
                      </em>
                    ) : null}
                  </div>
                ) : null}
                {implied ? (
                  <div className="consensus-row consensus-market">
                    <strong>市场隐含</strong>
                    {(["home", "draw", "away"] as const).map((key, index) => (
                      <span key={key}>
                        <b>{percent(implied[index])}</b>
                        {aggregate ? (
                          <small
                            className={
                              aggregate[index] - implied[index] > 0
                                ? "edge-positive"
                                : aggregate[index] - implied[index] < 0
                                  ? "edge-negative"
                                  : undefined
                            }
                          >
                            {aggregate[index] - implied[index] > 0 ? "+" : ""}
                            {(
                              (aggregate[index] - implied[index]) *
                              100
                            ).toFixed(1)}
                            %
                          </small>
                        ) : null}
                        <i>
                          <em
                            className="market-bar"
                            style={
                              {
                                "--report-probability": percent(implied[index]),
                              } as CSSProperties
                            }
                          />
                        </i>
                      </span>
                    ))}
                    <mark className="market-mark">去水基准</mark>
                  </div>
                ) : null}
                {report.models.map((model) => (
                  <div className="consensus-row" key={model.key}>
                    <strong>{model.label}</strong>
                    {(["home", "draw", "away"] as const).map((key) => (
                      <span key={key}>
                        <b>{percent(model.probabilities[key])}</b>
                        <i>
                          <em
                            style={
                              {
                                "--report-probability": percent(
                                  model.probabilities[key],
                                ),
                              } as CSSProperties
                            }
                          />
                        </i>
                      </span>
                    ))}
                    <mark>
                      {model.outcome === "home"
                        ? "主胜"
                        : model.outcome === "draw"
                          ? "平局"
                          : "客胜"}
                    </mark>
                  </div>
                ))}
              </div>
            ) : (
              <div className="report-empty-line">
                <Clock3 size={17} aria-hidden="true" />
                暂无当前提示词版本的模型结果
              </div>
            )}
          </div>
          <div className="decision-arguments">
            <div className="support">
              <span>支持因素</span>
              <p>
                {report.factors.find(
                  (factor) => factor.tone === "home" || factor.tone === "away",
                )?.conclusion ?? "当前没有明显单边优势"}
              </p>
            </div>
            <div className="against">
              <span>反对因素</span>
              <p>
                {report.models.length > 1 && !report.consensus.includes("一致")
                  ? report.consensusDetail
                  : detail.context.odds
                    ? "市场价格需要结合临场变化复核"
                    : "缺少可验证的即时赔率"}
              </p>
            </div>
            <div className="pending">
              <span>待确认项</span>
              <p>
                {report.evidence.find((item) => !item.ready)?.label ??
                  "主要证据已就绪"}
              </p>
            </div>
          </div>
          <footer className="decision-action-row">
            <div>
              {eligible ? (
                <Check size={16} aria-hidden="true" />
              ) : (
                <CircleAlert size={16} aria-hidden="true" />
              )}
              <span>
                <strong>
                  {eligible
                    ? detail.fixture.status === "live"
                      ? "进行中仍可生成预测"
                      : "当前可生成预测"
                    : "本场预测已关闭"}
                </strong>
                <small>
                  {eligible
                    ? "赛中预测只保存版本，不产生新的模拟下注"
                    : "完场、延期或取消状态不可创建新版本"}
                </small>
              </span>
            </div>
            {eligible && (
              <button
                className="report-predict-button"
                type="button"
                onClick={onManualPredict}
                disabled={predicting || !hasEvidence}
                title={!hasEvidence ? "等待赛前证据同步" : actionLabel}
              >
                {predicting ? (
                  <LoaderCircle className="spin" size={16} aria-hidden="true" />
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
        </section>
      </div>

      <aside className="research-progress-rail" aria-label="研究进度">
        <section>
          <header>
            <span>RESEARCH FLOW</span>
            <h2>研究进度</h2>
          </header>
          <ol>
            {report.evidence.map((item, index) => (
              <li className={item.ready ? "ready" : "waiting"} key={item.key}>
                <i>
                  {item.ready ? (
                    <Check size={12} aria-hidden="true" />
                  ) : (
                    index + 1
                  )}
                </i>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.ready ? "已读取" : "待同步"}</small>
                </span>
              </li>
            ))}
            <li className={report.models.length ? "ready" : "waiting"}>
              <i>
                {report.models.length ? (
                  <Check size={12} aria-hidden="true" />
                ) : (
                  7
                )}
              </i>
              <span>
                <strong>模型判断</strong>
                <small>{report.models.length ? "已生成" : "待生成"}</small>
              </span>
            </li>
          </ol>
        </section>
        <section className={`research-risk ${risk.tone}`}>
          <strong>当前风险：{risk.label}</strong>
          <p>{risk.note}</p>
        </section>
        <section className="research-source-note">
          <Database size={16} aria-hidden="true" />
          <div>
            <strong>业务数据源</strong>
            <p>TheSportsDB · 懂球帝</p>
            <small>
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
    <section className="match-empty manual-prediction-empty">
      <Clock3 size={20} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
        {eligible && (
          <button
            className="manual-predict-button"
            type="button"
            onClick={onManualPredict}
            disabled={predicting || !hasEvidence}
          >
            {predicting ? (
              <LoaderCircle className="spin" size={13} aria-hidden="true" />
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
      </div>
    </section>
  );
}

function MatchOdds({ detail }: { detail: FixtureDetail }) {
  const odds = detail.context.odds;
  if (!odds)
    return (
      <section className="match-empty">
        <CircleAlert size={20} aria-hidden="true" />
        <div>
          <strong>暂无可用赛前赔率</strong>
          <p>系统不会用估算赔率替代缺失的市场数据。</p>
        </div>
      </section>
    );
  const handicap = odds.asian_handicap;
  return (
    <section className="market-board" aria-label="赛前赔率">
      <div className="market-board-heading">
        <div>
          <span>PRE-MATCH MARKET</span>
          <h2>赛前赔率</h2>
        </div>
        <small>
          {odds.bookmaker} · {formatTimestamp(odds.updated_at)}
        </small>
      </div>
      <div className="market-grid">
        <div>
          <span>主胜</span>
          <strong>{odds.home.toFixed(2)}</strong>
        </div>
        <div>
          <span>平局</span>
          <strong>{odds.draw.toFixed(2)}</strong>
        </div>
        <div>
          <span>客胜</span>
          <strong>{odds.away.toFixed(2)}</strong>
        </div>
        {handicap !== null && (
          <>
            <div>
              <span>{formatHandicapSide(handicap, "home")}</span>
              <strong>{odds.asian_handicap_home_odd?.toFixed(2) ?? "-"}</strong>
            </div>
            <div>
              <span>{formatHandicapSide(handicap, "away")}</span>
              <strong>{odds.asian_handicap_away_odd?.toFixed(2) ?? "-"}</strong>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function VerdictStrip({ detail }: { detail: FixtureDetail }) {
  const [ranks, setRanks] = useState<{ home: string; away: string } | null>(
    null,
  );
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
  const executionText =
    execution?.status === "bet"
      ? "执行模拟下注"
      : execution?.reason
        ? "暂不下注"
        : "待预测";
  useEffect(() => {
    let active = true;
    void fetchStandings()
      .then((response) => {
        if (!active) return;
        const snapshot = (response.items ?? []).find(
          (item) =>
            detail.fixture.league_key &&
            item.league_key === detail.fixture.league_key,
        );
        const rows = snapshot?.standings ?? [];
        const find = (name?: string) => {
          const row = rows.find(
            (item) =>
              name &&
              (item.team.name === name ||
                item.team.name.includes(name) ||
                (name ?? "").includes(item.team.name)),
          );
          return row ? `第 ${row.rank} 位 · ${row.points} 分` : "暂无";
        };
        setRanks({
          home: find(detail.fixture.home_team.name),
          away: find(detail.fixture.away_team.name),
        });
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [
    detail.fixture.league_key,
    detail.fixture.home_team.name,
    detail.fixture.away_team.name,
  ]);
  return (
    <div className="verdict-strip" aria-label="AI 结论速览">
      <div>
        <small>AI 综合预测</small>
        <strong>
          {pick && probabilities[pick] != null ? (
            <>
              <span className="verdict-pick">{pickLabel}</span> ·{" "}
              {Math.round(probabilities[pick] * 100)}%
              <small style={{ marginLeft: 8 }}>
                主 {Math.round((probabilities.home ?? 0) * 100)}% / 平{" "}
                {Math.round((probabilities.draw ?? 0) * 100)}% / 客{" "}
                {Math.round((probabilities.away ?? 0) * 100)}%
              </small>
            </>
          ) : report.models.length ? (
            "生成中，暂无结论"
          ) : (
            "暂无预测"
          )}
        </strong>
      </div>
      <div>
        <small>执行决定</small>
        <strong
          className={
            execution?.status === "bet" ? "verdict-bet" : "verdict-no-bet"
          }
        >
          {executionText}
        </strong>
      </div>
      <div>
        <small>联赛排名</small>
        <strong>
          {ranks
            ? `${detail.fixture.home_team.name} ${ranks.home} · ${detail.fixture.away_team.name} ${ranks.away}`
            : "读取中"}
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
      <main className="match-center-page">
        <section className="match-empty">
          <CircleAlert size={20} aria-hidden="true" />
          <div>
            <strong>比赛详情暂不可用</strong>
            <p>{error}</p>
          </div>
        </section>
      </main>
    );
  if (!detail)
    return (
      <main className="match-center-page">
        <div
          className="match-report-skeleton"
          aria-label="正在加载比赛研究报告"
        >
          <div className="skeleton-scoreboard">
            <i />
            <i />
            <i />
          </div>
          <div className="skeleton-tabs" />
          <div className="skeleton-report">
            <i />
            <i />
            <i />
            <i />
          </div>
        </div>
      </main>
    );

  const hasPredictions =
    Object.values(detail.predictions ?? {}).some(Boolean) ||
    Boolean(detail.prediction);
  return (
    <main className="match-center-page research-match-page">
      <MatchHeader detail={detail} />
      <VerdictStrip detail={detail} />
      <Tabs
        className="match-tabs"
        ariaLabel="比赛研究页签"
        value={activeTab}
        onChange={setActiveTab}
        items={tabs.map((tab) => ({ value: tab.key, label: tab.label }))}
      />
      <div className="match-content">
        {actionError && (
          <div className="match-action-message error" role="alert">
            <CircleAlert size={15} aria-hidden="true" />
            {actionError}
          </div>
        )}
        {actionMessage && (
          <div className="match-action-message success" role="status">
            <ShieldCheck size={15} aria-hidden="true" />
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
          <div className="match-tab-stack">
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
          <div className="match-tab-stack">
            <AnalysisSnapshot detail={detail} />
            <EvidenceDetails detail={detail} sections={["form"]} />
          </div>
        )}
        {activeTab === "h2h" && (
          <div className="match-tab-stack">
            <EvidenceDetails detail={detail} sections={["h2h"]} />
          </div>
        )}
        {activeTab === "squads" && (
          <div className="match-tab-stack">
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
