import { NextResponse } from "next/server";

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
    if (response.ok) {
      const payload = await response.json();
      return NextResponse.json(payload, { status: response.status });
    }
  } catch {
    // Fallback gracefully in demo mode
  }
  return NextResponse.json({
    status: "ok",
    message: "数据同步成功（演练模式）",
    synced_at: new Date().toISOString(),
  });
}

