import { NextResponse } from "next/server";
import { PYTHON_API } from "@/lib/python-backend";
export const dynamic = "force-dynamic";

/** GET /api/v1/health — liveness for the public validation endpoint. */
export const runtime = "nodejs";

export async function GET() {
  let pythonBackend = false;

  if (PYTHON_API) {
    try {
      const res = await fetch(`${PYTHON_API}/v1/health`, { signal: AbortSignal.timeout(55000), cache: "no-store" });
      pythonBackend = res.ok;
    } catch {
      pythonBackend = false;
    }
  }

  return NextResponse.json({
    status: pythonBackend ? "ok" : "degraded",
    fallback: !pythonBackend,
    version: "3.1.0",
    engine: pythonBackend ? "python-dimensional" : "typescript-20-checks-fallback",
    domains: pythonBackend ? 21 : 5,
    python_backend: pythonBackend,
    ai_enabled: !!process.env.OPENROUTER_API_KEY,
  });
}
