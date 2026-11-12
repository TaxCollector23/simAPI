import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 60;

type Row = Record<string, unknown>;
type CompareBody = {
  sim_data?: Row[];
  real_data?: Row[];
  robotics_limits?: Record<string, [number, number]>;
  conditions?: Record<string, number>;
  sim_units?: Record<string, string>;
  real_units?: Record<string, string>;
  robotics_limit_units?: Record<string, string>;
};

function errorBody(code: string, message: string, requestId: string) {
  return { error: { code, message, request_id: requestId } };
}

function isRows(value: unknown): value is Row[] {
  return Array.isArray(value) && value.length > 0 && value.every(
    (row) => Boolean(row) && typeof row === "object" && !Array.isArray(row),
  );
}

function isStringMap(value: unknown): value is Record<string, string> {
  if (value === undefined) return true;
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.entries(value).every(([key, item]) => key.trim() !== "" && typeof item === "string" && item.trim() !== "");
}

function isFiniteNumberMap(value: unknown): value is Record<string, number> {
  if (value === undefined) return true;
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.entries(value).every(([key, item]) => key.trim() !== "" && typeof item === "number" && Number.isFinite(item));
}

function isLimits(value: unknown): value is Record<string, [number, number]> {
  if (value === undefined) return true;
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.entries(value).every(([key, range]) =>
      key.trim() !== "" && Array.isArray(range) && range.length === 2 &&
      range.every((item) => typeof item === "number" && Number.isFinite(item)) &&
      range[0] < range[1],
    );
}

export async function POST(req: Request) {
  const requestId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  let raw: string;
  try {
    raw = await req.text();
  } catch {
    return NextResponse.json(errorBody("validation_failed", "Could not read the request body.", requestId), { status: 400 });
  }
  if (raw.length > 8_000_000) {
    return NextResponse.json(errorBody("payload_too_large", "Sim-to-real comparison accepts up to 8 MB of JSON data.", requestId), { status: 413 });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return NextResponse.json(errorBody("validation_failed", "Request body is not valid JSON.", requestId), { status: 422 });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return NextResponse.json(errorBody("bad_request", "Request body must be a JSON object.", requestId), { status: 400 });
  }
  const body = parsed as CompareBody;

  if (!isRows(body.sim_data) || !isRows(body.real_data)) {
    return NextResponse.json(errorBody("bad_request", "sim_data and real_data must each contain sample objects.", requestId), { status: 400 });
  }
  if (body.sim_data.length > 10000 || body.real_data.length > 10000) {
    return NextResponse.json(errorBody("payload_too_large", "Each comparison run is limited to 10,000 samples in the playground.", requestId), { status: 413 });
  }
  if (!isLimits(body.robotics_limits) || !isFiniteNumberMap(body.conditions) ||
      !isStringMap(body.sim_units) || !isStringMap(body.real_units) ||
      !isStringMap(body.robotics_limit_units)) {
    return NextResponse.json(errorBody("bad_request", "Limits, conditions, and unit maps must contain valid numeric ranges or string values.", requestId), { status: 400 });
  }

  const pythonApi = process.env.PYTHON_API_URL?.replace(/\/$/, "");
  if (!pythonApi) {
    return NextResponse.json(
      errorBody("backend_unavailable", "Sim-to-real comparison requires the Python API. Configure PYTHON_API_URL on this deployment.", requestId),
      { status: 503 },
    );
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (process.env.PYTHON_API_KEY) headers["X-API-Key"] = process.env.PYTHON_API_KEY;
  try {
    const upstream = await fetch(`${pythonApi}/v1/compare/sim-real`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(45_000),
    });
    const responseText = await upstream.text();
    let responseBody: unknown;
    try {
      responseBody = JSON.parse(responseText);
    } catch {
      responseBody = null;
    }
    if (!upstream.ok) {
      const payload = responseBody as { detail?: unknown; error?: { message?: unknown } } | null;
      const message = typeof payload?.detail === "string"
        ? payload.detail
        : typeof payload?.error?.message === "string"
          ? payload.error.message
          : "The Python API could not compare these runs.";
      return NextResponse.json(errorBody("backend_error", message, requestId), { status: upstream.status });
    }
    if (!responseBody || typeof responseBody !== "object" || Array.isArray(responseBody)) {
      return NextResponse.json(errorBody("backend_error", "The Python API returned an invalid comparison report.", requestId), { status: 502 });
    }
    return NextResponse.json({ ...responseBody, request_id: requestId }, { headers: { "X-Request-ID": requestId } });
  } catch (error) {
    return NextResponse.json(
      errorBody("backend_unavailable", error instanceof Error ? error.message : "The Python API is unreachable.", requestId),
      { status: 503 },
    );
  }
}
