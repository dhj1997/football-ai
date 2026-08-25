import type { DateFilter, Fixture, FixtureDetail, LeagueFilter } from "./types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

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
