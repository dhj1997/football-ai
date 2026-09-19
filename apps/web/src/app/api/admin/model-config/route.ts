import { NextRequest, NextResponse } from "next/server";
import { getMockRuntimeConfig } from "@/lib/mock-data";

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
    if (response.ok) {
      return NextResponse.json(await response.json(), { status: response.status });
    }
  } catch {
    // Fallback
  }

  if (request.method === "GET") {
    return NextResponse.json(getMockRuntimeConfig());
  }
  return NextResponse.json({ status: "ok", message: "模型配置已更新（演练模式）" });
}

export const GET = forward;
export const PUT = forward;

