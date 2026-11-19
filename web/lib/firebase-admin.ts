import { cert, getApps, initializeApp, type ServiceAccount } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getFirestore } from "firebase-admin/firestore";

function getAdminApp() {
  const existing = getApps()[0];
  if (existing) return existing;

  const rawCredentials = process.env.SIMAPI_FIREBASE_SERVICE_ACCOUNT_JSON;
  if (!rawCredentials) {
    throw new Error("SIMAPI_FIREBASE_SERVICE_ACCOUNT_JSON is not configured.");
  }

  let credentials: Record<string, unknown>;
  try {
    credentials = JSON.parse(rawCredentials);
  } catch {
    throw new Error("SIMAPI_FIREBASE_SERVICE_ACCOUNT_JSON must contain valid JSON.");
  }
  return initializeApp({
    credential: cert(credentials as ServiceAccount),
    projectId: String(credentials.project_id || "simapi-dev"),
  });
}

export function getFirebaseAdminAuth() {
  return getAuth(getAdminApp());
}

export function getFirebaseAdminFirestore() {
  return getFirestore(getAdminApp());
}
