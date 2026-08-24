import { NextResponse } from "next/server";

export async function POST() {
  const apiBase = process.env.API_BASE_URL ?? "http://localhost:8000";
  const adminKey = process.env.ADMIN_API_KEY ?? "dev-admin-key";
  const response = await fetch(`${apiBase}/api/admin/sync`, {
    method: "POST",
    headers: { "x-admin-key": adminKey },
    cache: "no-store",
  });
  const payload = await response.json();
  return NextResponse.json(payload, { status: response.status });
}
