import { NextRequest, NextResponse } from "next/server";

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

  const apiBase = (process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001").replace(/\/+$/, "");
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/fixtures/${encodeURIComponent(fixtureId)}/predictions`, {
      method: "POST",
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(210_000),
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
      return NextResponse.json({ detail: "预测服务暂时不可用，请稍后重试" }, { status: 502 });
    }
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "预测服务暂时不可用，请稍后重试" }, { status: 502 });
  }
}
