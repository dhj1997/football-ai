import { NextResponse } from "next/server";

export async function GET() {
  const apiBase = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  const response = await fetch(`${apiBase}/api/admin/jobs?limit=20`, {
    headers: { "x-admin-key": adminKey },
    cache: "no-store",
  });
  return NextResponse.json(await response.json(), { status: response.status });
}
