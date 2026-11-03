import { NextResponse } from "next/server";
import { repairPreview } from "@/lib/robotics-workflow.js";

export const runtime = "nodejs";
export const maxDuration = 30;

/** Deterministic, episode-aware repair. Returns a new dataset only with apply=true. */
export async function POST(req: Request) {
  const requestId = crypto.randomUUID();
  try {
    const text = await req.text();
    if (text.length > 4_000_000)
      return NextResponse.json(
        { error: { code: "too_large", message: "Repair accepts up to 4 MB." } },
        { status: 413 },
      );
    const body = JSON.parse(text);
    if (
      !Array.isArray(body.data) ||
      !body.data.length ||
      body.data.length > 10000
    )
      throw new Error("data must contain 1–10,000 sample objects.");
    if (body.apply !== undefined && typeof body.apply !== "boolean")
      throw new Error("apply must be a boolean.");
    const { repaired_data, ...plan } = repairPreview(body.data);
    return NextResponse.json(
      {
        ...plan,
        repaired_data: body.apply ? repaired_data : null,
        request_id: requestId,
      },
      { headers: { "X-Request-ID": requestId } },
    );
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          code: "bad_request",
          message:
            error instanceof Error ? error.message : "Invalid repair request.",
          request_id: requestId,
        },
      },
      { status: 400 },
    );
  }
}
