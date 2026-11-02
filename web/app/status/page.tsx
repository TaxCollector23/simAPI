"use client";

import { useEffect, useState } from "react";

type Health = { status: string; engine: string; python_backend: boolean; domains: number };

export default function StatusPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/v1/health", { cache: "no-store", signal: AbortSignal.timeout(6000) })
      .then(async (response) => {
        if (!response.ok) throw new Error("Health check failed");
        return response.json() as Promise<Health>;
      })
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="container-tight pb-24 pt-36 sm:pt-44">
      <div className="max-w-3xl">
        <p className="text-sm font-medium text-accent-cyan">Service status</p>
        <h1 className="mt-5 text-4xl font-medium text-white sm:text-5xl">What the site can reach</h1>
        <p className="mt-5 text-base leading-7 text-white/65">This page checks the current website API from your browser. It does not measure historical uptime.</p>
        <div className="mt-10 divide-y divide-white/10 rounded-xl border border-white/10 bg-ink-900">
          <div className="flex flex-wrap items-center justify-between gap-3 p-5">
            <span className="text-white/80">Website API</span>
            <span className={error ? "text-fail" : health ? "text-pass" : "text-white/50"}>
              {error ? "Unavailable" : health ? "Responding" : "Checking"}
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 p-5">
            <span className="text-white/80">Validation engine</span>
            <span className="font-mono text-sm text-white/65">
              {health ? (health.python_backend ? "Python dimensional engine" : "TypeScript fallback") : "Unknown"}
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 p-5">
            <span className="text-white/80">Domains reported by health check</span>
            <span className="font-mono text-sm text-white/65">{health?.domains ?? "Unknown"}</span>
          </div>
        </div>
        {health && !health.python_backend && (
          <p className="mt-5 text-sm leading-6 text-white/60">The full Python backend is not connected to this site; validation uses the TypeScript fallback.</p>
        )}
      </div>
    </div>
  );
}
