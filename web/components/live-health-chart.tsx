"use client";

import { useEffect, useState } from "react";

interface HealthResponse {
  status: string;
  engine?: string;
  domains?: number;
  python_backend?: boolean;
  ai_enabled?: boolean;
}

interface HealthSample {
  at: number;
  milliseconds: number;
}

const SAMPLE_INTERVAL_MS = 15_000;
const MAX_SAMPLES = 6;

function clockTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function LiveHealthChart() {
  const [samples, setSamples] = useState<HealthSample[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [latestCheck, setLatestCheck] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    let mounted = true;
    let requestInProgress = false;
    let activeController: AbortController | null = null;

    const check = async () => {
      if (requestInProgress) return;
      requestInProgress = true;
      const controller = new AbortController();
      activeController = controller;
      const timeoutId = window.setTimeout(() => controller.abort(), 5_000);
      const start = performance.now();
      try {
        const response = await fetch("/api/v1/health", {
          cache: "no-store",
          signal: controller.signal,
        });
        const data = (await response.json()) as HealthResponse;
        const finished = performance.now();
        if (!response.ok || data.status !== "ok") {
          throw new Error("Health endpoint returned an unsuccessful response.");
        }
        if (!mounted) return;
        setHealth(data);
        setLatestCheck("online");
        setSamples((previous) => [
          ...previous,
          { at: Date.now(), milliseconds: Math.max(0, finished - start) },
        ].slice(-MAX_SAMPLES));
      } catch {
        if (mounted) setLatestCheck("offline");
      } finally {
        window.clearTimeout(timeoutId);
        if (activeController === controller) activeController = null;
        requestInProgress = false;
      }
    };

    void check();
    const interval = window.setInterval(check, SAMPLE_INTERVAL_MS);
    return () => {
      mounted = false;
      activeController?.abort();
      window.clearInterval(interval);
    };
  }, []);

  const maxObserved = Math.max(...samples.map((sample) => sample.milliseconds), 0);
  const scaleMax = Math.max(50, Math.ceil(maxObserved / 50) * 50);
  const plot = { left: 56, right: 584, top: 22, bottom: 198 };
  const plotHeight = plot.bottom - plot.top;
  const firstAt = samples[0]?.at ?? 0;
  const lastAt = samples[samples.length - 1]?.at ?? firstAt;
  const span = lastAt - firstAt;
  const points = samples.map((sample, index) => {
    const x = samples.length === 1
      ? (plot.left + plot.right) / 2
      : plot.left + (span > 0 ? (sample.at - firstAt) / span : index / (samples.length - 1)) * (plot.right - plot.left);
    const y = plot.bottom - (sample.milliseconds / scaleMax) * plotHeight;
    return { x, y, sample };
  });
  const polyline = points.map(({ x, y }) => `${x},${y}`).join(" ");
  const latest = samples[samples.length - 1];
  const checkStatus = latestCheck === "online" ? "Responding" : latestCheck === "offline" ? "Unavailable" : "Checking";
  const windowLabel = samples.length === 0
    ? `Up to ${MAX_SAMPLES} successful checks, one every ${SAMPLE_INTERVAL_MS / 1000} seconds.`
    : samples.length === 1
      ? "1 successful check recorded in this visit so far."
      : `${samples.length} successful checks over ${((lastAt - firstAt) / 1000).toFixed(0)} seconds; one request every ${SAMPLE_INTERVAL_MS / 1000} seconds.`;

  return (
    <figure className="live-health-card" aria-labelledby="live-health-title">
      <div className="live-health-heading">
        <div>
          <p className="live-health-eyebrow">Live service check</p>
          <h2 id="live-health-title">Health response time</h2>
        </div>
        <span className={`live-health-status live-health-status-${latestCheck}`} role="status">
          <span aria-hidden="true" />
          {checkStatus}
        </span>
      </div>

      <div className="live-health-current">
        <strong>{latest ? `${latest.milliseconds.toFixed(1)} ms` : "—"}</strong>
        <span>latest successful check from this browser</span>
      </div>

      <div className="live-health-chart-wrap">
        {samples.length === 0 ? (
          <div className="live-health-empty" role="status">
            {latestCheck === "offline"
              ? "No successful health checks have been recorded in this visit."
              : "Waiting for the first health response. No sample data is preloaded."}
          </div>
        ) : (
          <svg
            className="live-health-chart"
            viewBox="0 0 620 250"
            role="img"
            aria-label={`Browser-measured response times for the live SimAPI health endpoint: ${samples.map((sample) => `${sample.milliseconds.toFixed(1)} milliseconds`).join(", ")}.`}
          >
            <title>Actual response-time measurements from this browser</title>
            {[0, 0.5, 1].map((fraction) => {
              const y = plot.bottom - fraction * plotHeight;
              const tickValue = Math.round(fraction * scaleMax);
              return (
                <g key={fraction}>
                  <line x1={plot.left} y1={y} x2={plot.right} y2={y} className="live-health-gridline" />
                  <text x={plot.left - 10} y={y + 4} textAnchor="end" className="live-health-axis-label">
                    {tickValue}
                  </text>
                </g>
              );
            })}
            <line x1={plot.left} y1={plot.top} x2={plot.left} y2={plot.bottom} className="live-health-axis" />
            <line x1={plot.left} y1={plot.bottom} x2={plot.right} y2={plot.bottom} className="live-health-axis" />
            {points.length > 1 && (
              <polyline points={polyline} className="live-health-line" />
            )}
            {points.map(({ x, y, sample }, index) => (
              <circle key={`${sample.at}-${index}`} cx={x} cy={y} r="5" className="live-health-point">
                <title>{`${sample.milliseconds.toFixed(1)} ms at ${clockTime(sample.at)}`}</title>
              </circle>
            ))}
            <text x={plot.left} y="225" className="live-health-axis-label">{clockTime(firstAt)}</text>
            {samples.length > 1 && (
              <text x={plot.right} y="225" textAnchor="end" className="live-health-axis-label">{clockTime(lastAt)}</text>
            )}
            <text x="320" y="244" textAnchor="middle" className="live-health-axis-label">Request time (local)</text>
            <text x="15" y="112" textAnchor="middle" transform="rotate(-90 15 112)" className="live-health-axis-label">milliseconds</text>
          </svg>
        )}
      </div>

      <figcaption className="live-health-caption">
        <p><strong>Source:</strong> GET <code>/api/v1/health</code></p>
        <p><strong>Metric:</strong> this browser&rsquo;s round-trip time to receive the health response.</p>
        <p><strong>Window:</strong> {windowLabel}</p>
        <p>This measures service response time, not robot motion or a validation run.</p>
      </figcaption>

      {health && (
        <dl className="live-health-facts" aria-label="Current service facts from the health response">
          <div><dt>Engine</dt><dd>{health.engine ?? "Unknown"}</dd></div>
          <div><dt>Domains</dt><dd>{health.domains ?? "Unknown"}</dd></div>
          <div><dt>Python API</dt><dd>{health.python_backend ? "Connected" : "Not connected"}</dd></div>
        </dl>
      )}
    </figure>
  );
}
