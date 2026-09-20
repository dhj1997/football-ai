import { NextRequest, NextResponse } from "next/server";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

export async function POST(request: NextRequest) {
  let fixtureId: string | undefined;
  try {
    ({ fixtureId } = (await request.json()) as { fixtureId?: string });
  } catch {
    return NextResponse.json({ detail: "请求格式无效" }, { status: 400 });
  }
  if (!fixtureId) {
    return NextResponse.json({ detail: "缺少比赛编号" }, { status: 400 });
  }

  const apiBase = (process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/fixtures/${encodeURIComponent(fixtureId)}/predictions`, {
      method: "POST",
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(210_000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) {
      return gatewayError(error, `/api/admin/fixtures/${fixtureId}/predictions`);
    }
  }
  return NextResponse.json({
    status: "ok",
    mode: "demo",
    message: "预测生成完成（演练模式）",
    fixture_id: fixtureId,
    created_at: new Date().toISOString(),
  });
}

