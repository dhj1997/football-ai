import { NextRequest, NextResponse } from "next/server";

const apiBase = (process.env.API_BASE_URL ?? "http://127.0.0.1:8001").replace(/\/+$/, "");

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = `${apiBase}/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
  const response = await fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });
  return new NextResponse(response.body, {
    status: response.status,
    headers: response.headers,
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
