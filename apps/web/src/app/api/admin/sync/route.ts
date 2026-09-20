import { NextResponse } from "next/server";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

export async function POST() {
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/sync`, {
      method: "POST",
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) return gatewayError(error, "/api/admin/sync");
  }
  return NextResponse.json({
    status: "ok",
    mode: "demo",
    message: "数据同步成功（演练模式）",
    synced_at: new Date().toISOString(),
  });
}

