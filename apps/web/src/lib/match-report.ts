import type { Fixture, FixtureDetail, ModelKey, Prediction } from "./types";

export type MatchOutcome = "home" | "draw" | "away";

export interface ReportModelRow {
  key: ModelKey | "current";
  label: string;
  outcome: MatchOutcome;
  probabilities: Record<MatchOutcome, number>;
  confidence: number;
}

export interface ReportEvidenceRow {
  key: string;
  label: string;
  ready: boolean;
  detail: string;
  updatedAt: string | null;
}

export interface ReportFactor {
  label: string;
  value: string;
  conclusion: string;
  tone: "home" | "away" | "neutral" | "warning";
}

export interface MatchReport {
  consensus: string;
  consensusDetail: string;
  consensusOutcome: MatchOutcome | null;
  agreement: number | null;
  confidence: number | null;
  probabilities: Record<MatchOutcome, number> | null;
  models: ReportModelRow[];
  evidence: ReportEvidenceRow[];
  evidenceReady: number;
  evidenceTotal: number;
  evidenceQuality: number;
  keyVariable: string;
  marketWatch: string;
  factors: ReportFactor[];
}

const outcomeLabels: Record<MatchOutcome, string> = {
  home: "主胜",
  draw: "平局",
  away: "客胜",
};

export function canCreatePrediction(fixture: Fixture) {
  return fixture.status === "scheduled" || fixture.status === "live";
}

function predictionOutcome(prediction: Prediction): MatchOutcome {
  const forecast = prediction.forecast?.predicted_outcome ?? prediction.predicted_outcome;
  if (forecast === "home" || forecast === "draw" || forecast === "away") return forecast;
  return (Object.entries(prediction.probabilities) as Array<[MatchOutcome, number]>)
    .reduce((best, current) => current[1] > best[1] ? current : best)[0];
}

function modelRows(detail: FixtureDetail): ReportModelRow[] {
  const rows: ReportModelRow[] = (Object.entries(detail.predictions ?? {}) as Array<[ModelKey, Prediction | null | undefined]>)
    .filter((entry): entry is [ModelKey, Prediction] => Boolean(entry[1]))
    .map(([key, prediction]) => ({
      key,
      label: key === "deepseek" ? "DeepSeek" : "GPT-5.6 Sol",
      outcome: predictionOutcome(prediction),
      probabilities: prediction.probabilities,
      confidence: prediction.forecast_confidence ?? Math.max(...Object.values(prediction.probabilities)),
    }));
  if (!rows.length && detail.prediction) {
    rows.push({
      key: "current",
      label: detail.prediction.model_version,
      outcome: predictionOutcome(detail.prediction),
      probabilities: detail.prediction.probabilities,
      confidence: detail.prediction.forecast_confidence ?? Math.max(...Object.values(detail.prediction.probabilities)),
    });
  }
  return rows;
}

function averageProbabilities(rows: ReportModelRow[]): Record<MatchOutcome, number> | null {
  if (!rows.length) return null;
  return {
    home: rows.reduce((total, row) => total + row.probabilities.home, 0) / rows.length,
    draw: rows.reduce((total, row) => total + row.probabilities.draw, 0) / rows.length,
    away: rows.reduce((total, row) => total + row.probabilities.away, 0) / rows.length,
  };
}

function latestTimestamp(values: Array<string | null | undefined>) {
  return values.filter((value): value is string => Boolean(value)).sort().at(-1) ?? null;
}

function hasProfile(value: object | undefined) {
  return Boolean(value && Object.values(value).some((item) => item !== null && item !== "" && item !== undefined));
}

function evidenceRows(detail: FixtureDetail): ReportEvidenceRow[] {
  const { context } = detail;
  const profilesReady = hasProfile(context.teams?.home) && hasProfile(context.teams?.away);
  return [
    {
      key: "form",
      label: "近期状态",
      ready: Boolean(context.recent_form.home.length && context.recent_form.away.length),
      detail: context.recent_form.home.length || context.recent_form.away.length ? `双方各取最近 ${Math.max(context.recent_form.home.length, context.recent_form.away.length)} 场` : "暂无有效样本",
      updatedAt: context.recent_form.updated_at,
    },
    {
      key: "h2h",
      label: "历史交锋",
      ready: context.head_to_head.length > 0,
      detail: context.head_to_head.length ? `已收录 ${context.head_to_head.length} 场` : "暂无交锋记录",
      updatedAt: context.synced_at ?? null,
    },
    {
      key: "availability",
      label: "伤停信息",
      ready: Boolean(context.availability.updated_at),
      detail: context.availability.updated_at ? `已知缺阵 ${context.availability.home_missing + context.availability.away_missing} 人` : "等待数据源确认",
      updatedAt: context.availability.updated_at,
    },
    {
      key: "teams",
      label: "球队资料",
      ready: profilesReady,
      detail: profilesReady ? "双方档案已获取" : "档案仍有缺口",
      updatedAt: latestTimestamp([context.synced_at]),
    },
    {
      key: "lineup",
      label: "首发阵容",
      ready: context.lineup.confirmed,
      detail: context.lineup.confirmed ? "确认首发已纳入" : "开赛前一小时复核",
      updatedAt: context.lineup.updated_at,
    },
    {
      key: "odds",
      label: "市场赔率",
      ready: Boolean(context.odds),
      detail: context.odds ? `${context.odds.bookmaker} 胜平负` : "无可验证赔率",
      updatedAt: context.odds?.updated_at ?? null,
    },
  ];
}

function keyVariable(detail: FixtureDetail, evidence: ReportEvidenceRow[]) {
  const missing = evidence.find((item) => !item.ready);
  if (missing) return `${missing.label}尚未就绪`;
  const { context, fixture } = detail;
  const formGap = (context.recent_form.home_points_per_game ?? 0) - (context.recent_form.away_points_per_game ?? 0);
  const missingGap = context.availability.home_missing - context.availability.away_missing;
  const strengthGap = context.lineup.home_strength - context.lineup.away_strength;
  const candidates = [
    { score: Math.abs(formGap) / 3, text: formGap >= 0 ? `${fixture.home_team.name}近期效率占优` : `${fixture.away_team.name}近期效率占优` },
    { score: Math.abs(missingGap) / 5, text: missingGap > 0 ? `${fixture.home_team.name}伤停压力更高` : `${fixture.away_team.name}伤停压力更高` },
    { score: Math.abs(strengthGap), text: strengthGap >= 0 ? `${fixture.home_team.name}阵容强度占优` : `${fixture.away_team.name}阵容强度占优` },
  ];
  const strongest = candidates.sort((left, right) => right.score - left.score)[0];
  return strongest.score >= 0.04 ? strongest.text : "双方结构数据接近";
}

function marketWatch(detail: FixtureDetail) {
  const odds = detail.context.odds;
  if (!odds) return "赔率待同步";
  const options = [
    { label: detail.fixture.home_team.name, value: odds.home },
    { label: "平局", value: odds.draw },
    { label: detail.fixture.away_team.name, value: odds.away },
  ];
  const favorite = options.reduce((best, item) => item.value < best.value ? item : best);
  return `${favorite.label} ${favorite.value.toFixed(2)}`;
}

function reportFactors(detail: FixtureDetail): ReportFactor[] {
  const { fixture, context } = detail;
  const formGap = (context.recent_form.home_points_per_game ?? 0) - (context.recent_form.away_points_per_game ?? 0);
  const missingGap = context.availability.home_missing - context.availability.away_missing;
  const strengthGap = context.lineup.home_strength - context.lineup.away_strength;
  return [
    {
      label: "近期效率",
      value: `${(context.recent_form.home_points_per_game ?? 0).toFixed(2)} : ${(context.recent_form.away_points_per_game ?? 0).toFixed(2)}`,
      conclusion: Math.abs(formGap) < 0.2 ? "双方近期取分效率接近" : `${formGap > 0 ? fixture.home_team.name : fixture.away_team.name}更高`,
      tone: Math.abs(formGap) < 0.2 ? "neutral" : formGap > 0 ? "home" : "away",
    },
    {
      label: "已知伤停",
      value: `${context.availability.home_missing} : ${context.availability.away_missing}`,
      conclusion: missingGap === 0 ? "双方缺阵人数相同" : `${missingGap > 0 ? fixture.home_team.name : fixture.away_team.name}缺阵更多`,
      tone: missingGap === 0 ? "neutral" : missingGap > 0 ? "warning" : "away",
    },
    {
      label: "阵容强度",
      value: `${Math.round(context.lineup.home_strength * 100)} : ${Math.round(context.lineup.away_strength * 100)}`,
      conclusion: context.lineup.confirmed ? (Math.abs(strengthGap) < 0.03 ? "确认首发强度接近" : `${strengthGap > 0 ? fixture.home_team.name : fixture.away_team.name}更完整`) : "首发未确认，仍需复核",
      tone: context.lineup.confirmed ? (Math.abs(strengthGap) < 0.03 ? "neutral" : strengthGap > 0 ? "home" : "away") : "warning",
    },
    {
      label: "交锋样本",
      value: `${context.head_to_head.length} 场`,
      conclusion: context.head_to_head.length ? "可用于背景校验" : "不纳入方向判断",
      tone: context.head_to_head.length ? "neutral" : "warning",
    },
  ];
}

export function deriveMatchReport(detail: FixtureDetail): MatchReport {
  const models = modelRows(detail);
  const probabilities = averageProbabilities(models);
  const consensusOutcome = probabilities
    ? (Object.entries(probabilities) as Array<[MatchOutcome, number]>).reduce((best, current) => current[1] > best[1] ? current : best)[0]
    : null;
  const outcomes = new Set(models.map((model) => model.outcome));
  const agreement = models.length > 1
    ? 1 - Math.max(...(["home", "draw", "away"] as MatchOutcome[]).map((key) => Math.abs(models[0].probabilities[key] - models[1].probabilities[key])))
    : models.length === 1 ? 1 : null;
  const confidence = models.length ? models.reduce((total, model) => total + model.confidence, 0) / models.length : null;
  const evidence = evidenceRows(detail);
  const evidenceReady = evidence.filter((item) => item.ready).length;
  const consensus = !models.length
    ? "等待模型判断"
    : outcomes.size === 1
      ? `${models.length > 1 ? "双模型一致" : "当前模型倾向"}：${outcomeLabels[models[0].outcome]}`
      : "模型存在分歧";
  const consensusDetail = !models.length
    ? "当前没有可审计的预测版本"
    : outcomes.size === 1
      ? `${models.map((model) => model.label).join(" 与 ")}给出相同赛果方向`
      : models.map((model) => `${model.label} ${outcomeLabels[model.outcome]}`).join("，");
  return {
    consensus,
    consensusDetail,
    consensusOutcome,
    agreement,
    confidence,
    probabilities,
    models,
    evidence,
    evidenceReady,
    evidenceTotal: evidence.length,
    evidenceQuality: evidenceReady / evidence.length,
    keyVariable: keyVariable(detail, evidence),
    marketWatch: marketWatch(detail),
    factors: reportFactors(detail),
  };
}
