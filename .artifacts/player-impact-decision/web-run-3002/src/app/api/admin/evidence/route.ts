import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const { fixtureId } = (await request.json()) as { fixtureId?: string };
  if (!fixtureId) {
    return NextResponse.json({ detail: "缺少比赛编号" }, { status: 400 });
  }

  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  const response = await fetch(`${apiBase}/api/admin/fixtures/${fixtureId}/evidence`, {
    method: "POST",
    headers: { "x-admin-key": adminKey },
    cache: "no-store",
  });
  const payload = await response.json();
  return NextResponse.json(payload, { status: response.status });
}
