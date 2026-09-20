import { NextResponse } from "next/server";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

export async function GET() {
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/activation-status`, {
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) return gatewayError(error, "/api/admin/activation-status");
  }

  return NextResponse.json({
    status: "attention",
    mode: "demo",
    blocking_reasons: [],
    attention_reasons: ["demo_mode"],
    database: { backend: "demo", status: "test_only", backup: { status: "unavailable" } },
    player_impact: { status: "pending", active_rule_count: 0, upcoming_fixture_count: 0, covered_fixture_count: 0 },
    providers: {
      sources: [
        { key: "player_values", label: "球员身价", status: "not_run" },
        { key: "prematch_news", label: "赛前新闻", status: "unavailable", reason: "provider_required" },
      ],
      telemetry: [],
    },
    ensemble: { status: "pending", count: 0, items: [] },
    evaluation: {
      status: "pending",
      backtests: { passing_count: 0, recent: [] },
      research: { passing_count: 0, exploratory_count: 0, confirmatory_count: 0, recent: [] },
    },
  });
}
