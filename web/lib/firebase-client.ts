"use client";

import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

// Firebase web config is public. Authorization is enforced by Firebase Auth and
// server-side Firebase Admin; no secrets belong in this module.
const firebaseConfig = {
  apiKey: "AIzaSyBiQssuBVZmCYF9E5BpHCo60ftWcnYc_gI",
  authDomain: "simapi-dev.firebaseapp.com",
  projectId: "simapi-dev",
  storageBucket: "simapi-dev.firebasestorage.app",
  messagingSenderId: "438492423116",
  appId: "1:438492423116:web:3a0505d8a14f07250cf369",
  measurementId: "G-NRN1VT68S4",
};

const app = getApps().length ? getApp() : initializeApp(firebaseConfig);
export const firebaseAuth = getAuth(app);
