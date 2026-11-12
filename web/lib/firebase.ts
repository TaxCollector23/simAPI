import { getApp, getApps, initializeApp } from "firebase/app";

// Keep the Firebase API key in Vercel's NEXT_PUBLIC_FIREBASE_API_KEY setting
// instead of source control; browser Firestore access is controlled separately
// by firestore.rules.
const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
  authDomain: "simapi-dev.firebaseapp.com",
  projectId: "simapi-dev",
  storageBucket: "simapi-dev.firebasestorage.app",
  messagingSenderId: "438492423116",
  appId: "1:438492423116:web:3a0505d8a14f07250cf369",
  measurementId: "G-NRN1VT68S4",
};

export async function initializeFirebaseAnalytics(): Promise<void> {
  if (typeof window === "undefined" || !firebaseConfig.apiKey) return;

  const analytics = await import("firebase/analytics");
  if (!(await analytics.isSupported())) return;

  const app = getApps().length ? getApp() : initializeApp(firebaseConfig);
  analytics.getAnalytics(app);
}
