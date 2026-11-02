"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  LayoutDashboard, Activity, FlaskConical, BookOpen, Settings as SettingsIcon,
  Trash2, ExternalLink, BarChart3, ScrollText, Radar,
} from "lucide-react";
import {
  usageStats, listRuns as listRunHistory,
  type UsageStats, type RunRecord,
} from "@/lib/run-history";
import { ValidationDashboard } from "./validation-dashboard";
import { AnalyticsPanel } from "./analytics-panel";
import { LogsPanel } from "./logs-panel";
import { RequestInspectorPanel } from "./request-inspector-panel";
import { cn } from "@/lib/utils";
import { site } from "@/lib/site";

type Section = "overview" | "usage" | "analytics" | "logs" | "inspector" | "run" | "settings";

const NAV: { id: Section; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "inspector", label: "Request Inspector", icon: Radar },
  { id: "usage", label: "Usage", icon: Activity },
  { id: "run", label: "Playground", icon: FlaskConical },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

export function DashboardApp() {
  const [section, setSection] = useState<Section>("overview");
  const [inspectRunId, setInspectRunId] = useState<string | null>(null);

  function goInspect(id: string) {
    setInspectRunId(id);
    setSection("inspector");
  }

  return (
    <div className="dashboard-theme">
      <div className="container-tight pb-24 pt-32">
        <div className="grid gap-8 lg:grid-cols-[240px_1fr]">
        {/* Sidebar */}
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <p className="px-3 text-sm font-medium text-white/55">Workspace</p>
          <nav className="mt-3 space-y-0.5">
            {NAV.map((item) => (
              <button
                key={item.id}
                onClick={() => setSection(item.id)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-colors",
                  section === item.id ? "bg-white/[0.06] text-white" : "text-white/55 hover:bg-white/[0.03] hover:text-white",
                )}
              >
                <item.icon className="h-4 w-4" /> {item.label}
              </button>
            ))}
            <a
              href="/docs"
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-white/55 transition-colors hover:bg-white/[0.03] hover:text-white"
            >
              <BookOpen className="h-4 w-4" /> Documentation
            </a>
          </nav>
        </aside>

        {/* Content */}
        <div>
          {section === "overview" && <Overview onNavigate={setSection} />}
          {section === "analytics" && <AnalyticsPanel />}
          {section === "logs" && <LogsPanel onInspect={goInspect} />}
          {section === "inspector" && (
            <RequestInspectorPanel runId={inspectRunId} onBack={() => setInspectRunId(null)} />
          )}
          {section === "usage" && <Usage />}
          {section === "run" && <RunSimulation />}
          {section === "settings" && <SettingsPanel />}
        </div>
        </div>
      </div>
    </div>
  );
}

// ── Overview ──────────────────────────────────────────────────────────────────
function Overview({ onNavigate }: { onNavigate: (s: Section) => void }) {
  const [stats, setStats] = useState<UsageStats | null>(null);

  useEffect(() => {
    setStats(usageStats());
  }, []);

  if (!stats) return null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Overview</h1>
        <p className="mt-1 text-sm text-white/60">Validations saved in this browser.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Requests today" value={String(stats.requestsToday)} />
        <Stat label="Total validations" value={String(stats.totalValidations)} />
        <Stat label="Pass rate" value={stats.totalValidations ? `${stats.successRate}%` : "—"} />
      </div>

      <div>
        <h2 className="text-lg font-medium text-white">Validate a simulation run</h2>
        <p className="mt-1 text-sm text-white/50">
          Choose a domain, adjust conditions, and inspect the checks here.
        </p>
        <button onClick={() => onNavigate("run")} className="btn-accent mt-4">
          <FlaskConical className="h-4 w-4" /> Open validator
        </button>

        <p className="mb-3 mt-8 text-sm text-white/60">Or call SimAPI from Python</p>
        <div className="card overflow-hidden">
          <div className="border-b border-white/[0.06] px-4 py-2 font-mono text-xs text-white/40">python</div>
          <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-white/70">
{`from simapi import SimAPI

client = SimAPI(api_key="sk_live_...")
result = client.validate("simulation.json", simulation_type="robotics")

print(result.status)          # "passed" | "warning" | "failed"
print(result.violations)`}
          </pre>
        </div>
      </div>

      <RecentRuns runs={stats.recent} onRun={() => onNavigate("run")} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-ink-900 p-5">
      <p className="text-sm text-white/60">{label}</p>
      <p className="mt-2 font-mono text-3xl font-medium text-white tabular-nums">{value}</p>
    </div>
  );
}

function RecentRuns({ runs, onRun }: { runs: RunRecord[]; onRun: () => void }) {
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Recent validations</h2>
        <button onClick={onRun} className="text-xs text-accent-cyan hover:text-white">Run a validation →</button>
      </div>
      {runs.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 py-10 text-center text-sm text-white/35">
          No validations yet. Run one from the Playground tab.
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-white/[0.07]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.07] bg-white/[0.02] text-left text-xs text-white/45">
                <th className="p-3 font-medium">Type</th>
                <th className="p-3 font-medium">Status</th>
                <th className="p-3 font-medium">Trials</th>
                <th className="p-3 font-medium">Time</th>
                <th className="p-3 font-medium">When</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-white/[0.05] last:border-0">
                  <td className="p-3 text-white/70">{r.simulationType}</td>
                  <td className="p-3"><StatusPill status={r.status} /></td>
                  <td className="p-3 text-white/60">{r.trials_submitted - r.trials_excluded} / {r.trials_submitted}</td>
                  <td className="p-3 text-white/50">{r.executionMs ? `${r.executionMs}ms` : "—"}</td>
                  <td className="p-3 text-white/40">{timeAgo(r.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    passed: "bg-pass/15 text-pass",
    warning: "bg-warn/15 text-warn",
    failed: "bg-fail/15 text-fail",
  };
  return <span className={cn("text-sm font-medium", map[status])}>{status}</span>;
}

// ── Usage ─────────────────────────────────────────────────────────────────────
function Usage() {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [stats, setStats] = useState<UsageStats | null>(null);

  useEffect(() => {
    setRuns(listRunHistory());
    setStats(usageStats());
  }, []);

  if (!stats) return null;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Usage</h1>
        <p className="mt-1 text-sm text-white/50">Derived from validations you&apos;ve run in this browser.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-4">
        <Stat label="Requests today" value={String(stats.requestsToday)} />
        <Stat label="Total validations" value={String(stats.totalValidations)} />
        <Stat label="Pass rate" value={stats.totalValidations ? `${stats.successRate}%` : "—"} />
        <Stat label="Avg. exclusion rate" value={stats.totalValidations ? `${stats.avgExclusionRate}%` : "—"} />
      </div>
      <RecentRuns runs={runs.slice(0, 20)} onRun={() => { /* stays on usage */ }} />
    </div>
  );
}

// ── Run Simulation ────────────────────────────────────────────────────────────
function RunSimulation() {
  return <ValidationDashboard />;
}

// ── Settings ──────────────────────────────────────────────────────────────────
function SettingsPanel() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Settings</h1>
        <p className="mt-1 text-sm text-white/60">Run history in this dashboard is stored in this browser.</p>
      </div>

      <div className="card p-5">
        <h2 className="mb-4 text-sm font-semibold text-white">Local data</h2>
        <dl className="space-y-3 text-sm">
          <Row label="Validation runs stored" value={String(listRunHistory().length)} />
          <Row label="Storage" value="Browser localStorage (this device only)" />
        </dl>
      </div>

      <div className="card p-5">
        <h2 className="mb-1 text-sm font-semibold text-white">Danger zone</h2>
        <p className="mb-4 text-sm text-white/55">Clears validation history stored in this browser.</p>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => {
              if (confirm("Clear validation history stored in this browser?")) {
                localStorage.removeItem("simapi.runs.local");
                location.reload();
              }
            }}
            className="btn-ghost"
          >
            <Trash2 className="h-4 w-4" /> Clear local data
          </button>
        </div>
      </div>

      <Link href={site.github} className="inline-flex items-center gap-1.5 text-sm text-white/45 hover:text-white">
        View the source on GitHub <ExternalLink className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-white/[0.05] pb-3 last:border-0 last:pb-0">
      <dt className="text-white/45">{label}</dt>
      <dd className="text-white/75">{value}</dd>
    </div>
  );
}

function timeAgo(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
