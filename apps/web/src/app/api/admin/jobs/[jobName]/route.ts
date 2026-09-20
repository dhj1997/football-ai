import { NextRequest, NextResponse } from "next/server";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

export async function POST(_: NextRequest, { params }: { params: Promise<{ jobName: string }> }) {
  const { jobName } = await params;
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  try {
    const response = await fetch(`${apiBase}/api/admin/jobs/${encodeURIComponent(jobName)}/run`, {
      method: "POST",
      headers: { "x-admin-key": adminKey },
      cache: "no-store",
      signal: AbortSignal.timeout(210_000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) {
      return gatewayError(error, `/api/admin/jobs/${jobName}/run`);
    }
  }
  return NextResponse.json({
    status: "ok",
    mode: "demo",
    job: jobName,
    message: `任务 ${jobName} 触发成功（演练模式）`,
    triggered_at: new Date().toISOString(),
  });
}

