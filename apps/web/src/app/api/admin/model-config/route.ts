import { NextRequest, NextResponse } from "next/server";

const apiBase = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";

async function forward(request: NextRequest) {
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
  const response = await fetch(`${apiBase}/api/admin/model-config`, {
    method: request.method,
    headers: {
      "x-admin-key": adminKey,
      ...(request.method === "GET" ? {} : { "content-type": "application/json" }),
    },
    body,
    cache: "no-store",
  });
  return NextResponse.json(await response.json(), { status: response.status });
}

export const GET = forward;
export const PUT = forward;
