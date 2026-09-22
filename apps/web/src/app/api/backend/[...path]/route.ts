import { NextRequest, NextResponse } from "next/server";
import {
  getMockBacktest,
  getMockBankroll,
  getMockBets,
  getMockDecisions,
  getMockFixtureDetail,
  getMockFixtures,
  getMockMetrics,
  getMockModelEvaluation,
  getMockRuntimeConfig,
  getMockStandings,
  getMockStrategyPerformance,
  getMockTeamDetail,
} from "@/lib/mock-data";
import type { DateFilter, FixtureLeagueFilter } from "@/lib/types";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

const apiBase = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
// These read-only reports scan settlement/prediction tables and can take
// longer than the short 4s budget used by interactive fixture mutations.
const reportReadPaths = new Set([
  "api/bankroll",
  "api/bets",
  "api/decisions",
  "api/strategy-performance",
  "api/metrics/predictions",
  "api/backtest/three-leagues",
  "api/model-evaluation",
]);

function handleMockFallback(path: string[], searchParams: URLSearchParams) {
  const pathStr = path.join("/");

  if (pathStr === "api/fixtures" || pathStr === "fixtures") {
    const date = (searchParams.get("date") ?? "upcoming") as DateFilter;
    const league = (searchParams.get("league") ?? "all") as FixtureLeagueFilter;
    const items = getMockFixtures(date, league);
    return NextResponse.json({
      items,
      mode: "demo",
      schedule_provider: "内置演示源",
      schedule_provider_configured: true,
      sync_status: "fresh",
      league_counts: {
        all: 7,
        epl: 3,
        laliga: 2,
        csl: 2,
      },
      last_synced_at: new Date().toISOString(),
      dongqiudi_last_synced_at: new Date().toISOString(),
    });
  }

  if (path[0] === "api" && path[1] === "fixtures" && path[2]) {
    const fixtureId = path[2];
    return NextResponse.json(getMockFixtureDetail(fixtureId));
  }

  if (pathStr === "api/standings" || pathStr === "standings") {
    return NextResponse.json(getMockStandings());
  }

  if (path[0] === "api" && path[1] === "teams" && path[2] && path[3]) {
    return NextResponse.json(getMockTeamDetail(path[2], path[3]));
  }

  if (pathStr === "api/bankroll" || pathStr === "bankroll") {
    return NextResponse.json(getMockBankroll());
  }

  if (pathStr === "api/bets" || pathStr === "bets") {
    return NextResponse.json(getMockBets());
  }

  if (pathStr === "api/decisions" || pathStr === "decisions") {
    return NextResponse.json(getMockDecisions());
  }

  if (pathStr === "api/strategy-performance" || pathStr === "strategy-performance") {
    return NextResponse.json(getMockStrategyPerformance());
  }

  if (pathStr === "api/backtest/three-leagues" || pathStr === "backtest/three-leagues") {
    return NextResponse.json(getMockBacktest());
  }

  if (pathStr === "api/metrics/predictions" || pathStr === "metrics/predictions") {
    return NextResponse.json(getMockMetrics());
  }

  if (pathStr === "api/model-evaluation" || pathStr === "model-evaluation") {
    return NextResponse.json(getMockModelEvaluation());
  }

  if (pathStr === "api/admin/model-config" || pathStr === "admin/model-config") {
    return NextResponse.json(getMockRuntimeConfig());
  }

  return NextResponse.json({
    status: "ok",
    mode: "demo",
    message: "演练模式下请求已处理",
  });
}

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const pathStr = path.join("/");
  const target = `${apiBase}/${pathStr}${request.nextUrl.search}`;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(
        request.method === "GET" && reportReadPaths.has(pathStr) ? 30_000 : 4000,
      ),
    });

    return forwardUpstream(response);
  } catch (error) {
    if (webDemoModeEnabled()) {
      return handleMockFallback(path, request.nextUrl.searchParams);
    }
    return gatewayError(error, `/${path.join("/")}`);
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;

