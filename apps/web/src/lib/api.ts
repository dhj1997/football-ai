import type { BankrollSummary, DateFilter, DecisionAudit, Fixture, FixtureDetail, LeagueFilter, ModelEvaluationResponse, ModelKey, PredictionMetrics, SimulatedBet, StandingsResponse, StrategyPerformance, TeamDetailResponse } from "./types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(payload.detail ?? "数据请求失败");
  }
  return response.json() as Promise<T>;
}

export async function fetchFixtures(date: DateFilter, league: LeagueFilter): Promise<{
  items: Fixture[];
  mode: "cached" | "demo" | "empty" | "error" | "unconfigured";
  schedule_provider: string;
  schedule_provider_configured: boolean;
  sync_status: "fresh" | "updated" | "stale" | "failed" | "unconfigured";
  league_counts: Record<Exclude<LeagueFilter, "all">, number>;
  last_synced_at: string | null;
}> {
  const response = await fetch(`${apiBase}/api/fixtures?date=${date}&league=${league}`, { cache: "no-store" });
  return readJson(response);
}

export async function fetchFixtureDetail(id: string): Promise<FixtureDetail> {
  const response = await fetch(`${apiBase}/api/fixtures/${id}`, { cache: "no-store" });
  return readJson(response);
}

export async function fetchStandings(): Promise<StandingsResponse> {
  const response = await fetch(`${apiBase}/api/standings`, { cache: "no-store" });
  return readJson(response);
}

export async function fetchTeamDetail(leagueKey: string, teamId: string): Promise<TeamDetailResponse> {
  const response = await fetch(`${apiBase}/api/teams/${encodeURIComponent(leagueKey)}/${encodeURIComponent(teamId)}`, {
    cache: "no-store",
  });
  return readJson(response);
}

export async function fetchBankroll(): Promise<BankrollSummary> {
  return readJson(await fetch(`${apiBase}/api/bankroll`, { cache: "no-store" }));
}

export async function fetchBets(model?: ModelKey): Promise<{ items: SimulatedBet[]; count: number; is_simulated: true }> {
  const query = model ? `?model=${model}` : "";
  return readJson(await fetch(`${apiBase}/api/bets${query}`, { cache: "no-store" }));
}

export async function fetchDecisionAudits(parameters = "", model?: ModelKey): Promise<{ items: DecisionAudit[]; count: number; is_simulated: true }> {
  const query = new URLSearchParams(parameters);
  if (model) query.set("model", model);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return readJson(await fetch(`${apiBase}/api/decisions${suffix}`, { cache: "no-store" }));
}

export async function fetchStrategyPerformance(parameters = ""): Promise<{ items: StrategyPerformance[]; count: number; ranking: string; is_simulated: true }> {
  const suffix = parameters ? `?${parameters}` : "";
  return readJson(await fetch(`${apiBase}/api/strategy-performance${suffix}`, { cache: "no-store" }));
}

export async function fetchPredictionMetrics(parameters = "", model?: ModelKey): Promise<PredictionMetrics> {
  const query = new URLSearchParams(parameters);
  if (model) query.set("model", model);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return readJson(await fetch(`${apiBase}/api/metrics/predictions${suffix}`, { cache: "no-store" }));
}

export async function fetchModelEvaluation(): Promise<ModelEvaluationResponse> {
  return readJson(await fetch(`${apiBase}/api/model-evaluation`, { cache: "no-store" }));
}
