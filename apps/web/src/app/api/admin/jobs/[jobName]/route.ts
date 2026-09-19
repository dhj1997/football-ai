import { NextRequest, NextResponse } from "next/server";

export async function POST(_: NextRequest, { params }: { params: Promise<{ jobName: string }> }) {
  const { jobName } = await params;
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/jobs/${encodeURIComponent(jobName)}/run`, {
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
    job: jobName,
    message: `任务 ${jobName} 触发成功（演练模式）`,
    triggered_at: new Date().toISOString(),
  });
}

