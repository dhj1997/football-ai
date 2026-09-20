import { NextRequest, NextResponse } from "next/server";
import { getMockRuntimeConfig } from "@/lib/mock-data";
import { forwardUpstream, gatewayError, webDemoModeEnabled } from "@/lib/server-proxy";

const apiBase = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";

async function forward(request: NextRequest) {
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
  try {
    const response = await fetch(`${apiBase}/api/admin/model-config`, {
      method: request.method,
      headers: {
        "x-admin-key": adminKey,
        ...(request.method === "GET" ? {} : { "content-type": "application/json" }),
      },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return forwardUpstream(response);
  } catch (error) {
    if (!webDemoModeEnabled()) return gatewayError(error, "/api/admin/model-config");
  }

  if (request.method === "GET") {
    return NextResponse.json({ ...getMockRuntimeConfig(), mode: "demo" });
  }
  return NextResponse.json({ status: "ok", mode: "demo", message: "模型配置已更新（演练模式）" });
}

export const GET = forward;
export const PUT = forward;

