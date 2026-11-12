"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import {
  compareSimReal,
  DEMO_KEY,
  type SimRealComparison,
} from "@/lib/api";
import { parseCsv, type Row } from "@/lib/robotics-workflow.js";

const MAX_FILE_BYTES = 4_000_000;
const MAX_ROWS = 10_000;

type LoadedRun = { name: string; rows: Row[] };

function parseJsonRows(text: string): Row[] {
  const value: unknown = JSON.parse(text);
  const rows = Array.isArray(value)
    ? value
    : value && typeof value === "object"
      ? ((value as { data?: unknown; trials?: unknown }).data ?? (value as { trials?: unknown }).trials)
      : null;
  if (
    !Array.isArray(rows) ||
    rows.length === 0 ||
    rows.length > MAX_ROWS ||
    rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))
  ) {
    throw new Error(`Provide 1–${MAX_ROWS.toLocaleString()} sample objects in a JSON array.`);
  }
  return rows as Row[];
}

async function readRun(file: File): Promise<LoadedRun> {
  if (file.size > MAX_FILE_BYTES) throw new Error("Comparison files must be under 4 MB each.");
  const text = await file.text();
  const rows = /\.csv$/i.test(file.name) ? parseCsv(text) : parseJsonRows(text);
  if (!rows.length || rows.length > MAX_ROWS) {
    throw new Error(`Choose a run with 1–${MAX_ROWS.toLocaleString()} samples.`);
  }
  return { name: file.name, rows };
}

function parseUnitMap(value: string, label: string): Record<string, string> {
  if (!value.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must be a JSON object, such as {"joint_1_position":"deg"}.`);
  }
  if (
    !parsed || typeof parsed !== "object" || Array.isArray(parsed) ||
    Object.entries(parsed).some(([signal, unit]) => !signal.trim() || typeof unit !== "string" || !unit.trim())
  ) {
    throw new Error(`${label} must map signal names to unit strings.`);
  }
  return parsed as Record<string, string>;
}

function displayNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(Number(value.toPrecision(4))) : "—";
}

function RunPicker({
  label,
  loaded,
  onChange,
}: {
  label: string;
  loaded: LoadedRun | null;
  onChange: (run: LoadedRun | null) => void;
}) {
  const [error, setError] = useState("");
  return (
    <div className="rounded-lg border border-white/[0.1] bg-ink-900/40 p-4">
      <label className="block text-sm font-medium">
        {label}
        <span className="mt-2 flex flex-wrap items-center gap-3">
          <span className="landing-button landing-button-secondary">
            <Upload size={15} />
            Choose CSV or JSON
          </span>
          <input
            aria-label={`${label} CSV or JSON file`}
            className="sr-only"
            type="file"
            accept=".csv,.json"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              setError("");
              try {
                onChange(await readRun(file));
              } catch (cause) {
                onChange(null);
                setError(cause instanceof Error ? cause.message : "Could not read this run.");
              }
            }}
          />
        </span>
      </label>
      <p className="mt-3 text-sm text-white/65">
        {loaded ? `${loaded.name} · ${loaded.rows.length.toLocaleString()} samples` : "No run selected"}
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-red-300">{error}</p>}
    </div>
  );
}

export function SimRealComparisonPanel({
  roboticsLimits,
  conditions,
  enabled = true,
}: {
  roboticsLimits: Record<string, [number, number]>;
  conditions: Record<string, number>;
  enabled?: boolean;
}) {
  const [simRun, setSimRun] = useState<LoadedRun | null>(null);
  const [realRun, setRealRun] = useState<LoadedRun | null>(null);
  const [simUnits, setSimUnits] = useState("");
  const [realUnits, setRealUnits] = useState("");
  const [completed, setCompleted] = useState<{ report: SimRealComparison; profileKey: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const profileKey = JSON.stringify({ roboticsLimits, conditions, enabled });
  const result = completed?.profileKey === profileKey ? completed.report : null;

  async function runComparison() {
    if (!simRun || !realRun) return;
    setBusy(true);
    setError("");
    setCompleted(null);
    try {
      const comparison = await compareSimReal(
        {
          sim_data: simRun.rows,
          real_data: realRun.rows,
          robotics_limits: roboticsLimits,
          conditions,
          sim_units: parseUnitMap(simUnits, "Simulation units"),
          real_units: parseUnitMap(realUnits, "Robot units"),
        },
        DEMO_KEY,
      );
      setCompleted({ report: comparison, profileKey });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not compare these runs.");
    } finally {
      setBusy(false);
    }
  }

  const signalEntries = Object.entries(result?.signals ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const mismatchedChecks = Object.entries(result?.check_statuses ?? {}).filter(([, values]) => values.sim !== values.real);
  const unitConversions = result?.unit_conversions;
  const verdictLabel = result?.verdict === "aligned"
    ? "Distributions aligned"
    : result?.verdict === "drift_detected"
      ? "Drift detected"
      : "Insufficient shared signals";

  return (
    <section className="robotics-panel mt-8" aria-label="Sim-to-real comparison">
      <div className="max-w-3xl">
        <h2 className="text-xl font-medium">Compare simulation with a robot run</h2>
        <p className="mt-2 text-sm leading-6 text-white/65">
          Compare each signal’s 5th–95th percentile range and the validation checks on both runs. The API flags range overlap below 50% as drift.
          Declared units are converted before comparison. Alignment is a data screening result; it does not prove sim-to-real transfer or safe execution.
        </p>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <RunPicker
          label="Simulation run"
          loaded={simRun}
          onChange={(run) => { setSimRun(run); setCompleted(null); setError(""); }}
        />
        <RunPicker
          label="Real-robot run"
          loaded={realRun}
          onChange={(run) => { setRealRun(run); setCompleted(null); setError(""); }}
        />
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          Simulation units (optional JSON)
          <textarea
            aria-label="Simulation units JSON"
            value={simUnits}
            onChange={(event) => { setSimUnits(event.target.value); setCompleted(null); setError(""); }}
            placeholder={'{"joint_1_position":"rad"}'}
            spellCheck={false}
            className="mt-2 min-h-20 w-full font-mono text-xs"
          />
        </label>
        <label className="block text-sm">
          Robot units (optional JSON)
          <textarea
            aria-label="Robot units JSON"
            value={realUnits}
            onChange={(event) => { setRealUnits(event.target.value); setCompleted(null); setError(""); }}
            placeholder={'{"joint_1_position":"deg"}'}
            spellCheck={false}
            className="mt-2 min-h-20 w-full font-mono text-xs"
          />
        </label>
      </div>
      <p className="mt-3 text-xs leading-5 text-white/50">
        The active arm profile’s limits and trajectory conditions are applied to both runs. Leave units blank when both files already use canonical units.
      </p>
      {!enabled && (
        <p className="mt-3 text-sm text-amber-200">Select the Arm / manipulator profile to compare robotics runs.</p>
      )}
      <button
        className="landing-button landing-button-primary mt-5 disabled:cursor-not-allowed disabled:opacity-50"
        onClick={runComparison}
        disabled={!enabled || !simRun || !realRun || busy}
      >
        {busy ? "Comparing runs…" : "Compare runs"}
      </button>
      {error && <p role="alert" className="mt-4 text-sm text-red-300">{error}</p>}

      {result && (
        <div className="mt-6 space-y-5" aria-live="polite">
          <div className={`rounded-lg border p-4 ${result.verdict === "drift_detected" ? "border-amber-300/30 bg-amber-300/[0.06]" : "border-white/[0.1] bg-ink-900/40"}`}>
            <h3 className="text-lg font-medium">{verdictLabel}</h3>
            <p className="mt-2 text-sm text-white/65">
              Simulation: {result.sim.rows.toLocaleString()} samples, {result.sim.status}; robot: {result.real.rows.toLocaleString()} samples, {result.real.status}.
            </p>
            {result.comparison_note && <p className="mt-2 text-sm">{result.comparison_note}</p>}
          </div>

          <div>
            <h3 className="font-medium">Shared signal ranges</h3>
            {signalEntries.length ? (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[580px] text-left text-sm">
                  <thead className="text-white/55">
                    <tr>
                      <th className="p-2 font-medium">Signal</th>
                      <th className="p-2 font-medium">Simulation p5–p95</th>
                      <th className="p-2 font-medium">Robot p5–p95</th>
                      <th className="p-2 font-medium">Overlap</th>
                      <th className="p-2 font-medium">Finding</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signalEntries.map(([signal, values]) => (
                      <tr key={signal} className="border-t border-white/[0.08]">
                        <th className="p-2 font-mono font-normal">{signal}</th>
                        <td className="p-2">{displayNumber(values.sim.p5)} – {displayNumber(values.sim.p95)}</td>
                        <td className="p-2">{displayNumber(values.real.p5)} – {displayNumber(values.real.p95)}</td>
                        <td className="p-2">{Math.round(values.overlap * 100)}%</td>
                        <td className={`p-2 ${values.drift ? "text-amber-200" : "text-white/65"}`}>
                          {values.drift ? "Distribution drift" : "No drift flagged"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-2 text-sm text-white/60">No shared numeric signals were available to compare.</p>
            )}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h3 className="font-medium">Only in simulation</h3>
              <p className="mt-2 text-sm text-white/65">{result.signals_only_in_sim.length ? result.signals_only_in_sim.join(", ") : "None"}</p>
            </div>
            <div>
              <h3 className="font-medium">Only in robot run</h3>
              <p className="mt-2 text-sm text-white/65">{result.signals_only_in_real.length ? result.signals_only_in_real.join(", ") : "None"}</p>
            </div>
          </div>

          {unitConversions && (
            <div className="grid gap-4 md:grid-cols-2">
              {(["sim", "real"] as const).map((side) => {
                const entries = Object.entries(unitConversions[side] ?? {});
                return (
                  <div key={side}>
                    <h3 className="font-medium">{side === "sim" ? "Simulation" : "Robot"} unit conversions</h3>
                    <ul className="mt-2 space-y-1 text-sm text-white/65">
                      {entries.length
                        ? entries.map(([signal, conversion]) => <li key={signal}><span className="font-mono">{signal}</span>: {conversion}</li>)
                        : <li>No unit conversion applied.</li>}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}

          <div>
            <h3 className="font-medium">Validation check differences</h3>
            {mismatchedChecks.length ? (
              <ul className="mt-2 space-y-1 text-sm text-amber-100">
                {mismatchedChecks.map(([name, values]) => <li key={name}><span className="font-mono">{name}</span>: simulation {values.sim}, robot {values.real}</li>)}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-white/65">No check-status differences.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
