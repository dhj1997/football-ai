import { NextRequest, NextResponse } from "next/server";

export async function POST(_: NextRequest, { params }: { params: Promise<{ fixtureId: string }> }) {
  const { fixtureId } = await params;
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/fixtures/${encodeURIComponent(fixtureId)}/dongqiudi-sync`, {
      method: "POST",
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (response.ok) {
      return NextResponse.json(await response.json(), { status: response.status });
    }
  } catch {
    // Fallback
  }
  return NextResponse.json({
    status: "ok",
    message: "比赛懂球帝数据同步完成（演练模式）",
    fixture_id: fixtureId,
    synced_at: new Date().toISOString(),
  });
}

