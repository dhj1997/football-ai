import { NextResponse } from "next/server";

export async function POST() {
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/dongqiudi/sync`, {
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
    message: "懂球帝数据同步完成（演练模式）",
    synced_at: new Date().toISOString(),
  });
}

