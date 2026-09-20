import { NextRequest, NextResponse } from "next/server";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

export async function POST(request: NextRequest) {
  const { fixtureId } = (await request.json()) as { fixtureId?: string };
  if (!fixtureId) {
    return NextResponse.json({ detail: "缺少比赛编号" }, { status: 400 });
  }

  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/fixtures/${fixtureId}/evidence`, {
      method: "POST",
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) {
      return gatewayError(error, `/api/admin/fixtures/${fixtureId}/evidence`);
    }
  }
  return NextResponse.json({
    status: "ok",
    mode: "demo",
    message: "情报数据刷新成功（演练模式）",
    fixture_id: fixtureId,
    updated_at: new Date().toISOString(),
  });
}

