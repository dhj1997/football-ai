import "server-only";

import { NextResponse } from "next/server";

export function webDemoModeEnabled(): boolean {
  return process.env.WEB_DEMO_MODE?.trim().toLowerCase() === "true";
}

export function forwardUpstream(response: Response): NextResponse {
  return new NextResponse(response.body, {
    status: response.status,
    headers: response.headers,
  });
}

export function gatewayError(error: unknown, targetPath: string): NextResponse {
  const name = error instanceof Error ? error.name : "UnknownError";
  const timeout = name === "TimeoutError" || name === "AbortError";
  return NextResponse.json(
    {
      detail: timeout ? "后端请求超时" : "无法连接后端服务",
      category: timeout ? "upstream_timeout" : "upstream_connection_error",
      target_path: targetPath,
    },
    { status: timeout ? 504 : 502 },
  );
}
