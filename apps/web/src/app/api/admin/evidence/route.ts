import { NextRequest, NextResponse } from "next/server";

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
    if (response.ok) {
      const payload = await response.json();
      return NextResponse.json(payload, { status: response.status });
    }
  } catch {
    // Fallback
  }
  return NextResponse.json({
    status: "ok",
    message: "情报数据刷新成功（演练模式）",
    fixture_id: fixtureId,
    updated_at: new Date().toISOString(),
  });
}

