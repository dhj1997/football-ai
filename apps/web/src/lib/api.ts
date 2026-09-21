import type {
  BacktestResponse,
  BankrollSummary,
  DateFilter,
  DecisionAudit,
  Fixture,
  FixtureDetail,
  FixtureLeagueFilter,
  ModelEvaluationResponse,
  ModelKey,
  PredictionMetrics,
  RuntimeConfigResponse,
  SimulatedBet,
  StandingsResponse,
  StrategyPerformance,
  TeamDetailResponse,
} from "./types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend";
const fixtureCachePrefix = "football-ai:fixtures:";
const fixtureCacheTtlMs = 15 * 60 * 1000;

export type FixtureListResponse = {
  items: Fixture[];
  mode: "cached" | "demo" | "empty" | "error" | "unconfigured";
  schedule_provider: string;
  schedule_provider_configured: boolean;
  sync_status: "fresh" | "updated" | "stale" | "failed" | "unconfigured";
  league_counts: Record<string, number>;
  national_competitions?: Array<{
    key: string;
    name: string;
    confederation: string;
    competition_type: string;
    gender: "men";
    age_group: "senior" | "u23";
    fixture_count: number;
    logo_url: string | null;
    logo_source: string | null;
  }>;
  last_synced_at: string | null;
  dongqiudi_last_synced_at?: string | null;
};

type CachedFixtureList = { cached_at: number; response: FixtureListResponse };

function fixtureCacheKey(date: DateFilter, league: FixtureLeagueFilter) {
  return `${fixtureCachePrefix}${date}:${league}`;
}

export function readCachedFixtures(
  date: DateFilter,
  league: FixtureLeagueFilter,
): FixtureListResponse | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(fixtureCacheKey(date, league));
    if (!raw) return null;
    const cached = JSON.parse(raw) as CachedFixtureList;
    return cached.response?.items && Array.isArray(cached.response.items)
      ? cached.response
      : null;
  } catch {
    return null;
  }
}

function hasFreshFixtureCache(date: DateFilter, league: FixtureLeagueFilter) {
  if (typeof window === "undefined") return false;
  try {
    const raw = window.localStorage.getItem(fixtureCacheKey(date, league));
    if (!raw) return false;
    const cached = JSON.parse(raw) as CachedFixtureList;
    return (
      Number.isFinite(cached.cached_at) &&
      Date.now() - cached.cached_at < fixtureCacheTtlMs
    );
  } catch {
    return false;
  }
}

function writeCachedFixtures(
  date: DateFilter,
  league: FixtureLeagueFilter,
  response: FixtureListResponse,
) {
  if (typeof window === "undefined") return;
  try {
    // The list only needs row fields; keep large evidence/squad payloads out of
    // localStorage so the cache remains reliable on multi-match days.
    const compact: FixtureListResponse = {
      ...response,
      items: response.items.map(
        ({
          id,
          provider_id,
          fixture_date,
          league_key,
          league,
          kickoff,
          status,
          home_team,
          away_team,
          score,
          venue,
          lineup_confirmed,
          is_demo,
          evidence_summary,
          has_prediction,
        }) => ({
          id,
          provider_id,
          fixture_date,
          league_key,
          league,
          kickoff,
          status,
          home_team,
          away_team,
          score,
          venue,
          lineup_confirmed,
          is_demo,
          evidence_summary,
          has_prediction,
        }),
      ),
    };
    window.localStorage.setItem(
      fixtureCacheKey(date, league),
      JSON.stringify({
        cached_at: Date.now(),
        response: compact,
      } satisfies CachedFixtureList),
    );
  } catch {
    // Storage is optional; quota and privacy-mode failures must not affect live loading.
  }
}

export function prefetchFixtures(
  date: DateFilter,
  league: FixtureLeagueFilter,
) {
  if (hasFreshFixtureCache(date, league)) return;
  void fetchFixtures(date, league).catch(() => undefined);
}

export async function readJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();
  let payload: unknown = null;

  if (body && contentType.includes("application/json")) {
    try {
      payload = JSON.parse(body);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail =
      payload &&
      typeof payload === "object" &&
      "detail" in payload &&
      typeof payload.detail === "string"
        ? payload.detail
        : response.status === 404
          ? "请求接口不存在或已被服务器拦截，请检查 Web 服务版本"
          : "数据请求失败";
    throw new Error(detail);
  }

  if (!contentType.includes("application/json") || payload === null) {
    throw new Error("服务器返回了非 JSON 响应，请检查 Web 服务路由");
  }
  return payload as T;
}

export async function fetchFixtures(
  date: DateFilter,
  league: FixtureLeagueFilter,
  specificDate?: string,
): Promise<FixtureListResponse> {
  const dateQuery =
    specificDate
      ? `date_from=${specificDate}&date_to=${specificDate}`
      : `date=${date}`;
  const response = await fetch(
    `${apiBase}/api/fixtures?${dateQuery}&league=${league}`,
    { cache: "no-store" },
  );
  const payload = await readJson<FixtureListResponse>(response);
  writeCachedFixtures(date, league, payload);
  return payload;
}

export async function fetchFixtureDetail(id: string): Promise<FixtureDetail> {
  const response = await fetch(`${apiBase}/api/fixtures/${id}`, {
    cache: "no-store",
  });
  return readJson(response);
}

export async function fetchStandings(): Promise<StandingsResponse> {
  const response = await fetch(`${apiBase}/api/standings`, {
    cache: "no-store",
  });
  return readJson(response);
}

export async function fetchTeamDetail(
  leagueKey: string,
  teamId: string,
): Promise<TeamDetailResponse> {
  const response = await fetch(
    `${apiBase}/api/teams/${encodeURIComponent(leagueKey)}/${encodeURIComponent(teamId)}`,
    {
      cache: "no-store",
    },
  );
  return readJson(response);
}

export async function fetchBankroll(): Promise<BankrollSummary> {
  return readJson(
    await fetch(`${apiBase}/api/bankroll`, { cache: "no-store" }),
  );
}

export async function fetchBets(
  model?: ModelKey,
): Promise<{ items: SimulatedBet[]; count: number; is_simulated: true }> {
  const query = model ? `?model=${model}` : "";
  return readJson(
    await fetch(`${apiBase}/api/bets${query}`, { cache: "no-store" }),
  );
}

export async function fetchDecisionAudits(
  parameters = "",
  model?: ModelKey | "all",
): Promise<{ items: DecisionAudit[]; count: number; is_simulated: true }> {
  const query = new URLSearchParams(parameters);
  if (model) query.set("model", model);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return readJson(
    await fetch(`${apiBase}/api/decisions${suffix}`, { cache: "no-store" }),
  );
}

export async function fetchStrategyPerformance(
  parameters = "",
): Promise<{
  items: StrategyPerformance[];
  count: number;
  ranking: string;
  is_simulated: true;
}> {
  const suffix = parameters ? `?${parameters}` : "";
  return readJson(
    await fetch(`${apiBase}/api/strategy-performance${suffix}`, {
      cache: "no-store",
    }),
  );
}

export async function fetchBacktestReport(): Promise<BacktestResponse> {
  return readJson(
    await fetch(`${apiBase}/api/backtest/three-leagues`, { cache: "no-store" }),
  );
}

export async function fetchPredictionMetrics(
  parameters = "",
  model?: ModelKey,
): Promise<PredictionMetrics> {
  const query = new URLSearchParams(parameters);
  if (model) query.set("model", model);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return readJson(
    await fetch(`${apiBase}/api/metrics/predictions${suffix}`, {
      cache: "no-store",
    }),
  );
}

export async function fetchModelEvaluation(): Promise<ModelEvaluationResponse> {
  return readJson(
    await fetch(`${apiBase}/api/model-evaluation`, { cache: "no-store" }),
  );
}

export async function fetchRuntimeConfig(): Promise<RuntimeConfigResponse> {
  return readJson(
    await fetch("/api/admin/model-config", { cache: "no-store" }),
  );
}

export async function updateRuntimeConfig(
  payload: unknown,
): Promise<RuntimeConfigResponse> {
  return readJson(
    await fetch("/api/admin/model-config", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    }),
  );
}
