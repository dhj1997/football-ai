import { NextResponse } from "next/server";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

export async function GET() {
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/jobs?limit=20`, {
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) return gatewayError(error, "/api/admin/jobs");
  }
  return NextResponse.json({
    items: [],
    count: 0,
    enabled: false,
    analysis_enabled: false,
    mode: "demo",
  });
}

