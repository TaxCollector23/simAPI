import { createHash, randomBytes } from "node:crypto";
import { NextResponse } from "next/server";
import { getFirebaseAdminAuth, getFirebaseAdminFirestore } from "@/lib/firebase-admin";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const authorization = req.headers.get("authorization") || "";
  const match = authorization.match(/^Bearer\s+(.+)$/i);
  if (!match) return NextResponse.json({ error: "Sign in with Google to create an MCP key." }, { status: 401 });

  let adminAuth: ReturnType<typeof getFirebaseAdminAuth>;
  try {
    adminAuth = getFirebaseAdminAuth();
  } catch {
    return NextResponse.json({ error: "MCP key creation is not configured on this deployment yet." }, { status: 503 });
  }

  let decoded: { uid: string };
  try {
    decoded = await adminAuth.verifyIdToken(match[1]);
  } catch {
    return NextResponse.json({ error: "Your sign-in expired. Please sign in again." }, { status: 401 });
  }

  let label = "Claude MCP";
  try {
    const body = await req.json();
    if (typeof body?.label === "string" && body.label.trim()) label = body.label.trim().slice(0, 64);
  } catch {
    // A default label is sufficient.
  }

  const apiKey = `sk_live_${randomBytes(32).toString("base64url")}`;
  const keyHash = createHash("sha256").update(apiKey).digest("hex");
  try {
    await getFirebaseAdminFirestore().collection("mcpKeys").doc(keyHash).create({
      uid: decoded.uid,
      label,
      prefix: apiKey.slice(0, 14),
      createdAt: new Date(),
      revoked: false,
    });
  } catch {
    return NextResponse.json({ error: "Key creation is temporarily unavailable. Please try again later." }, { status: 503 });
  }

  return NextResponse.json({
    api_key: apiKey,
    label,
    created_at: new Date().toISOString(),
    message: "Store this key securely. It is shown only once.",
  }, { headers: { "Cache-Control": "no-store" } });
}
