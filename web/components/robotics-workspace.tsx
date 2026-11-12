"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Plus, Trash2, Upload } from "lucide-react";
import { validate, DEMO_KEY, type ValidationResult } from "@/lib/api";
import { listRuns, recordRun } from "@/lib/run-history";
import {
  compareReports,
  parseCsv,
  repairPreview,
  rowKeys,
  toCsv,
  validateProfile,
  type Profile,
  type RepairPlan,
  type ReportDiff,
  type Row,
} from "@/lib/robotics-workflow.js";
import type { Recording } from "@/lib/robotics-import.js";
import { FTC_DEFAULT_LIMITS, FTC_PROFILE } from "@/lib/ftc-frc.js";
import { RoboticsRunReport } from "./robotics-run-report";
import { SimRealComparisonPanel } from "./sim-real-comparison-panel";
import { TrajectoryExplorer } from "./trajectory-explorer";

type Limit = { signal: string; min: string; max: string };
type FtcLimit = number | [number, number];
const PROFILE_KEY = "simapi.robotics.profiles.v1";
const options = [
  { key: "max_time_step", label: "Maximum sample interval", unit: "s" },
  {
    key: "velocity_tolerance",
    label: "Position / velocity tolerance",
    unit: "velocity units",
  },
  {
    key: "acceleration_tolerance",
    label: "Velocity / acceleration tolerance",
    unit: "acceleration units",
  },
];
function download(name: string, value: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([value], { type })),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function parseRows(text: string): Row[] {
  const parsed = JSON.parse(text),
    rows = Array.isArray(parsed) ? parsed : (parsed.data ?? parsed.trials);
  if (
    !Array.isArray(rows) ||
    !rows.length ||
    rows.length > 10000 ||
    rows.some((r) => !r || typeof r !== "object" || Array.isArray(r))
  )
    throw new Error("Provide 1–10,000 sample objects in a JSON array.");
  return rows;
}
function draftLimits(drafts: Limit[]) {
  const entries = drafts.map((d) => {
    if (!d.signal.trim() || !d.min.trim() || !d.max.trim())
      throw new Error(
        "Complete the signal name and both bounds, or remove the unfinished limit.",
      );
    return [d.signal.trim(), [Number(d.min), Number(d.max)]];
  });
  if (new Set(entries.map(([key]) => key)).size !== entries.length)
    throw new Error("Each signal can have only one limit.");
  return Object.fromEntries(entries);
}

function FtcLimitsEditor({
  limits,
  onChange,
}: {
  limits: Record<string, FtcLimit>;
  onChange: (value: Record<string, FtcLimit>) => void;
}) {
  const labels: Record<string, string> = {
    motor_power: "Motor power range",
    battery_voltage: "Battery voltage warning band (V)",
    battery_sag_voltage: "Battery sag threshold (V)",
    sag_min_total_power: "Total power for sag detection",
    velocity_tolerance: "Encoder velocity tolerance (ticks/s)",
    min_moving_speed: "Minimum moving speed (ticks/s)",
    max_speed: "Maximum odometry speed (units/s)",
    heading_jump_deg: "Maximum unwrapped heading step (degrees)",
  };
  return (
    <fieldset className="mt-6 space-y-4">
      <legend className="mb-4 text-base font-medium">FTC / FRC limits</legend>
      {Object.entries(limits).map(([key, value]) => (
        <label key={key} className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span>{labels[key] ?? key}</span>
          {Array.isArray(value) ? (
            <span className="flex items-center gap-2">
              <input aria-label={`${labels[key]} minimum`} type="number" step="any" value={value[0]} onChange={(e) => onChange({ ...limits, [key]: [Number(e.target.value), value[1]] })} />
              <span>to</span>
              <input aria-label={`${labels[key]} maximum`} type="number" step="any" value={value[1]} onChange={(e) => onChange({ ...limits, [key]: [value[0], Number(e.target.value)] })} />
            </span>
          ) : (
            <input aria-label={labels[key] ?? key} className="w-28" type="number" min="0" step="any" value={value} onChange={(e) => onChange({ ...limits, [key]: Number(e.target.value) })} />
          )}
        </label>
      ))}
    </fieldset>
  );
}

export function RoboticsWorkspace({
  example,
  onOtherDomain,
  domains,
}: {
  example: Row[];
  onOtherDomain: (value: string) => void;
  domains: { value: string; label: string }[];
}) {
  const [rows, setRows] = useState<Row[]>([]),
    [raw, setRaw] = useState("[]"),
    [source, setSource] = useState(""),
    [pending, setPending] = useState<{ rows: Row[]; source: string } | null>(
      null,
    );
  const [profileKind, setProfileKind] = useState<"robotics" | "ftc">("robotics"),
    [ftcLimits, setFtcLimits] = useState<Record<string, FtcLimit>>(() => structuredClone(FTC_DEFAULT_LIMITS)),
    [limits, setLimits] = useState<Limit[]>([]),
    [conditions, setConditions] = useState<Record<string, number>>({}),
    [metadata, setMetadata] = useState<Partial<Profile>>({}),
    [name, setName] = useState("Arm profile");
  const [library, setLibrary] = useState<Profile[]>([]),
    [savedName, setSavedName] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null),
    [baselineReport, setBaselineReport] = useState<unknown>(null),
    [baselineRows, setBaselineRows] = useState<Row[]>([]),
    [baselineName, setBaselineName] = useState("");
  const [busy, setBusy] = useState(false),
    [importing, setImporting] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [repair, setRepair] = useState<RepairPlan | null>(null);
  const [recording, setRecording] = useState<{
      file: File;
      topics: Recording["topics"];
    } | null>(null),
    [topic, setTopic] = useState("");
  const [history, setHistory] = useState<
    { id: string; label: string; raw: unknown }[]
  >([]);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(PROFILE_KEY) || "[]");
      if (Array.isArray(saved)) setLibrary(saved.map(validateProfile));
    } catch {
      /* A corrupt local library never blocks loading a file. */
    }
    refreshHistory();
  }, []);
  function refreshHistory() {
    setHistory(
      listRuns()
        .filter((r) => r.simulationType === "robotics" && r.raw)
        .map((r) => ({
          id: r.id,
          label: `${r.id} · ${r.status} · ${new Date(r.ts).toLocaleString()}`,
          raw: r.raw,
        })),
    );
  }
  const revision = useRef(0);
  function invalidate() {
    revision.current++;
    setResult(null);
    setError("");
    setRepair(null);
  }
  function useRows(next: Row[], label: string) {
    setRows(next);
    setRaw(JSON.stringify(next, null, 2));
    setSource(label);
    setPending(null);
    invalidate();
  }
  function currentProfile() {
    return validateProfile({
      ...metadata,
      name,
      schema_version: 1,
      robotics_profile: profileKind,
      ...(profileKind === "ftc" ? { ftc_limits: ftcLimits } : {}),
      robotics_limits: profileKind === "ftc" ? {} : draftLimits(limits),
      conditions,
    });
  }
  function applyProfile(profile: Profile) {
    const nextKind = profile.robotics_profile === "ftc" ? "ftc" : "robotics";
    setProfileKind(nextKind);
    setFtcLimits({ ...structuredClone(FTC_DEFAULT_LIMITS), ...(profile.ftc_limits || {}) });
    setName(profile.name);
    setLimits(
      Object.entries(profile.robotics_limits).map(([signal, range]) => ({
        signal,
        min: String(range[0]),
        max: String(range[1]),
      })),
    );
    setConditions(profile.conditions);
    setMetadata(profile);
    invalidate();
  }
  let chartLimits: Record<string, [number, number]> = {};
  try {
    chartLimits = currentProfile().robotics_limits;
  } catch {
    /* Incomplete drafts are reported when saving/running. */
  }
  let diff: ReportDiff | null = null;
  try {
    if (result && baselineReport) diff = compareReports(baselineReport, result);
  } catch {
    /* File input reports invalid reports separately. */
  }
  async function loadRecording(file: File, selected?: string) {
    setImporting(true);
    setError("");
    try {
      const { readRecording } = await import("@/lib/robotics-import.js");
      const value = await readRecording(
        new Uint8Array(await file.arrayBuffer()),
        file.name,
        { topic: selected, profile: currentProfile() },
      );
      setRecording({ file, topics: value.topics });
      if (!value.requires_topic) {
        setTopic(value.topic || "");
        setPending({
          rows: value.rows,
          source: `${file.name} · ${value.topic}`,
        });
      } else {
        setTopic("");
        setPending(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read recording.");
    } finally {
      setImporting(false);
    }
  }
  async function loadData(file: File) {
    if (file.size > 100 * 1024 * 1024) {
      setError("Choose a recording under 100 MB.");
      return;
    }
    setError("");
    setNotice("");
    setPending(null);
    setRecording(null);
    if (/\.(mcap|bag)$/i.test(file.name)) return loadRecording(file);
    try {
      const text = await file.text(),
        next = /\.csv$/i.test(file.name) ? parseCsv(text) : parseRows(text);
      if (!next.length || next.length > 10000)
        throw new Error("Choose 1–10,000 samples.");
      setPending({ rows: next, source: file.name });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load data.");
    }
  }
  async function runChecks() {
    const requestedRevision = ++revision.current;
    setBusy(true);
    setError("");
    setNotice("");
    setResult(null);
    try {
      if (!rows.length)
        throw new Error("Load data or use the arm example first.");
      const profile = currentProfile();
      const report = await validate(
        {
          data: rows,
          simulation_type: "robotics",
          conditions: profile.conditions,
          robotics_limits: profile.robotics_limits,
          ...(profile.robotics_profile === "ftc" ? { robotics_profile: "ftc", ftc_limits: profile.ftc_limits } : {}),
          ...(profile.units ? { units: profile.units } : {}),
          run_ai: false,
        },
        DEMO_KEY,
      );
      if (revision.current !== requestedRevision) return;
      setResult(report);
      recordRun(
        {
          simulationType: "robotics",
          status: report.status,
          engine: report.robotics_summary?.engine_version ?? "robotics",
          executionMs: report.processing_ms,
          trials_submitted: report.trials_submitted,
          trials_excluded: report.trials_excluded,
          unique_checks: report.unique_checks ?? report.all_checks,
          issues: report.issues.map((i) => ({
            name: i.name,
            human_name: i.human_name,
            status: i.status,
          })),
          raw: report,
        },
        source,
      );
      refreshHistory();
    } catch (e) {
      if (revision.current !== requestedRevision) return;
      setError(e instanceof Error ? e.message : "Validation failed.");
    } finally {
      setBusy(false);
    }
  }
  const command =
    "simapi validate run.json --profile arm-profile.json --no-ai --format github --report report.json --fail-on failed";
  const missingSignals = Object.keys(chartLimits).filter(
    (key) => rows.length && !rows.some((r) => key in r),
  );
  return (
    <div className="robotics-workspace">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div>
          <h1 className="text-3xl font-medium">Robotics validation</h1>
          <p className="mt-3 max-w-2xl text-base leading-7">
            Check joint motion, timing, and data quality against the limits you
            choose.
          </p>
        </div>
        <button
          onClick={runChecks}
          disabled={busy || importing || !rows.length}
          className="landing-button landing-button-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Play size={17} />
          {busy ? "Running checks…" : "Run checks"}
        </button>
      </div>
      <section className="robotics-panel mt-8" aria-label="Load robotics data">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-xl font-medium">Run data</h2>
          <div className="flex flex-wrap gap-5">
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium">
              <Upload size={16} />
              Load CSV, JSON, bag, or MCAP
              <input
                className="sr-only"
                type="file"
                accept=".csv,.json,.bag,.mcap"
                disabled={importing || busy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void loadData(f);
                  e.target.value = "";
                }}
              />
            </label>
            <button
              className="text-sm font-medium"
              disabled={busy || importing}
              onClick={() => {
                setRecording(null);
                setPending({ rows: example, source: "Arm example" });
              }}
            >
              Use arm example
            </button>
          </div>
        </div>
        {importing && (
          <p role="status" className="mt-5 text-base">
            Reading the recording locally…
          </p>
        )}
        {recording && recording.topics.length > 1 && (
          <label className="mt-5 flex flex-wrap items-center gap-3 text-sm">
            JointState topic
            <select
              value={topic}
              disabled={importing}
              onChange={(e) => {
                setTopic(e.target.value);
                setPending(null);
                if (e.target.value)
                  void loadRecording(recording.file, e.target.value);
              }}
            >
              <option value="">Choose a topic</option>
              {recording.topics.map((t) => (
                <option key={t.topic} value={t.topic}>
                  {t.topic} · {t.samples} samples
                </option>
              ))}
            </select>
          </label>
        )}
        {pending && (
          <div className="mt-6">
            <p className="text-base">
              {pending.source} · {pending.rows.length.toLocaleString()} samples
            </p>
            <div className="mt-4 max-h-56 overflow-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">
                  First five imported samples
                </caption>
                <thead>
                  <tr>
                    {Object.keys(pending.rows[0] ?? {}).map((key) => (
                      <th
                        key={key}
                        className="whitespace-nowrap p-2 font-medium"
                      >
                        {key}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {pending.rows.slice(0, 5).map((r, i) => (
                    <tr key={i} className="border-t border-white/10">
                      {Object.keys(pending.rows[0]).map((k) => (
                        <td key={k} className="whitespace-nowrap p-2">
                          {String(r[k] ?? "Unavailable")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex gap-5">
              <button
                className="landing-button landing-button-primary"
                onClick={() => useRows(pending.rows, pending.source)}
              >
                Use imported data
              </button>
              <button
                className="text-sm"
                onClick={() => {
                  setPending(null);
                  setRecording(null);
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {!pending && (
          <p className="mt-4 text-base">
            {rows.length
              ? `${source} · ${rows.length.toLocaleString()} samples`
              : "Load a run to begin. Recordings are decoded in your browser; validation sends the extracted samples to SimAPI."}
          </p>
        )}
        <details className="mt-5">
          <summary className="cursor-pointer text-sm font-medium">
            Edit JSON data
          </summary>
          <textarea
            aria-label="Robotics sample JSON"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            spellCheck={false}
            className="mt-4 min-h-52 w-full font-mono text-sm"
          />
          <button
            className="mt-3 text-sm font-medium"
            onClick={() => {
              try {
                useRows(parseRows(raw), "Edited JSON");
              } catch (e) {
                setError(e instanceof Error ? e.message : "Invalid JSON.");
              }
            }}
          >
            Apply JSON
          </button>
        </details>
      </section>
      <div className="mt-6 grid items-start gap-6 xl:grid-cols-[minmax(320px,.8fr)_minmax(0,1.4fr)]">
        <section className="robotics-panel" aria-label="Robotics profile">
          <fieldset disabled={busy || importing} className="min-w-0">
            <label className="block text-sm">
              Built-in profile
              <select
                aria-label="Built-in robotics profile"
                className="mt-2 w-full"
                value={profileKind}
                onChange={(e) => {
                  setSavedName("");
                  if (e.target.value === "ftc") {
                    applyProfile(validateProfile(FTC_PROFILE));
                  } else {
                    applyProfile(validateProfile({
                      schema_version: 1,
                      name: "Arm profile",
                      robotics_profile: "robotics",
                      robotics_limits: {},
                      conditions: {},
                    }));
                  }
                }}
              >
                <option value="robotics">Arm / manipulator</option>
                <option value="ftc">FTC / FRC (school robotics)</option>
              </select>
            </label>
            <h2 className="mt-4 text-xl font-medium">{profileKind === "ftc" ? "FTC / FRC profile" : "Arm profile"}</h2>
            <label className="mt-5 block text-sm">
              Profile name
              <input
                className="mt-2 w-full"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={64}
              />
            </label>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              <label className="inline-flex cursor-pointer items-center gap-2 font-medium">
                <Upload size={16} />
                Import URDF or JSON
                <input
                  type="file"
                  className="sr-only"
                  accept=".urdf,.json"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    try {
                      if (f.size > 5_000_000)
                        throw new Error("Profiles must be under 5 MB.");
                      const text = await f.text();
                      applyProfile(
                        /\.urdf$/i.test(f.name)
                          ? (
                              await import("@/lib/robotics-import.js")
                            ).profileFromUrdf(text)
                          : validateProfile(JSON.parse(text)),
                      );
                      setNotice(`Loaded ${f.name}`);
                    } catch (err) {
                      setError(
                        err instanceof Error
                          ? err.message
                          : "Could not load profile.",
                      );
                    }
                    e.target.value = "";
                  }}
                />
              </label>
              <button
                onClick={() => {
                  try {
                    const profile = currentProfile(),
                      next = [
                        ...library.filter((p) => p.name !== profile.name),
                        profile,
                      ];
                    localStorage.setItem(PROFILE_KEY, JSON.stringify(next));
                    setLibrary(next);
                    setSavedName(profile.name);
                    setNotice(`Saved ${profile.name} in this browser.`);
                  } catch (e) {
                    setError(
                      e instanceof Error
                        ? e.message
                        : "Could not save profile.",
                    );
                  }
                }}
              >
                Save in browser
              </button>
              <button
                onClick={() => {
                  try {
                    download(
                      profileKind === "ftc" ? "ftc-frc-profile.json" : "arm-profile.json",
                      JSON.stringify(currentProfile(), null, 2),
                    );
                  } catch (e) {
                    setError(
                      e instanceof Error
                        ? e.message
                        : "Could not export profile.",
                    );
                  }
                }}
              >
                Download JSON
              </button>
            </div>
            {!!library.length && (
              <div className="mt-5 flex items-center gap-3">
                <select
                  aria-label="Saved profile"
                  value={savedName}
                  className="min-w-0 flex-1"
                  onChange={(e) => {
                    setSavedName(e.target.value);
                    const p = library.find((p) => p.name === e.target.value);
                    if (p) applyProfile(p);
                  }}
                >
                  <option value="">Saved profiles</option>
                  {library.map((p) => (
                    <option key={p.name}>{p.name}</option>
                  ))}
                </select>
                <button
                  aria-label="Delete saved profile"
                  disabled={!savedName}
                  onClick={() => {
                    try {
                      const next = library.filter((p) => p.name !== savedName);
                      localStorage.setItem(PROFILE_KEY, JSON.stringify(next));
                      setLibrary(next);
                      setSavedName("");
                    } catch {
                      setError("Could not update the saved profile library.");
                    }
                  }}
                >
                  <Trash2 size={17} />
                </button>
              </div>
            )}
            {profileKind === "ftc" ? (
              <FtcLimitsEditor limits={ftcLimits} onChange={(next) => { setFtcLimits(next); invalidate(); }} />
            ) : (
              <>
            <div className="mt-6 space-y-3">
              {limits.map((limit, index) => (
                <div
                  className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_24px] items-center gap-2 border-b border-white/10 pb-4"
                  key={index}
                >
                  <input
                    className="col-span-3 w-full"
                    aria-label={`Signal ${index + 1}`}
                    list="robotics-signals"
                    value={limit.signal}
                    onChange={(e) => {
                      setLimits(
                        limits.map((l, i) =>
                          i === index ? { ...l, signal: e.target.value } : l,
                        ),
                      );
                      invalidate();
                    }}
                    placeholder="Signal"
                  />
                  <input
                    aria-label={`Minimum for ${limit.signal || index + 1}`}
                    type="number"
                    step="any"
                    value={limit.min}
                    placeholder="Min"
                    onChange={(e) => {
                      setLimits(
                        limits.map((l, i) =>
                          i === index ? { ...l, min: e.target.value } : l,
                        ),
                      );
                      invalidate();
                    }}
                  />
                  <input
                    aria-label={`Maximum for ${limit.signal || index + 1}`}
                    type="number"
                    step="any"
                    value={limit.max}
                    placeholder="Max"
                    onChange={(e) => {
                      setLimits(
                        limits.map((l, i) =>
                          i === index ? { ...l, max: e.target.value } : l,
                        ),
                      );
                      invalidate();
                    }}
                  />
                  <button
                    aria-label={`Remove ${limit.signal || "limit"}`}
                    onClick={() => {
                      setLimits(limits.filter((_, i) => i !== index));
                      invalidate();
                    }}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
            <datalist id="robotics-signals">
              {[...new Set(rows.flatMap(Object.keys))]
                .filter((s) => /joint|tool|gripper|end_effector/.test(s))
                .map((s) => (
                  <option key={s} value={s} />
                ))}
            </datalist>
            <button
              className="mt-4 inline-flex items-center gap-2 text-sm font-medium"
              onClick={() => {
                setLimits([...limits, { signal: "", min: "", max: "" }]);
                invalidate();
              }}
            >
              <Plus size={16} />
              Add limit
            </button>
            {missingSignals.length > 0 && (
              <p className="mt-4 text-sm text-red-400">
                Missing configured signals: {missingSignals.join(", ")}. Match
                names before running checks.
              </p>
            )}
            {metadata.warnings?.length ? (
              <details className="mt-5 text-sm">
                <summary className="cursor-pointer font-medium">
                  URDF import notes
                </summary>
                <ul className="mt-3 space-y-2">
                  {metadata.warnings.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </details>
            ) : null}
              </>
            )}
            {profileKind === "robotics" && <fieldset className="mt-6 space-y-4">
              <legend className="mb-4 text-base font-medium">
                Timing and motion checks
              </legend>
              {options.map((option) => (
                <label
                  key={option.key}
                  className="flex items-center justify-between gap-4 text-sm"
                >
                  <span>
                    {option.label} ({option.unit})
                  </span>
                  <input
                    className="w-28"
                    aria-label={option.label}
                    type="number"
                    min="0"
                    step="any"
                    value={conditions[option.key] ?? ""}
                    placeholder="Optional"
                    onChange={(e) => {
                      const next = { ...conditions };
                      if (e.target.value === "") delete next[option.key];
                      else next[option.key] = Number(e.target.value);
                      setConditions(next);
                      invalidate();
                    }}
                  />
                </label>
              ))}
            </fieldset>}
            {profileKind === "robotics" ? (
              <p className="mt-5 text-sm leading-6">
                Timestamps use seconds. Use consistent units and unwrapped joint
                positions. URDF supplies declared position, velocity, and effort
                limits; acceleration limits are entered manually.
              </p>
            ) : (
              <p className="mt-5 text-sm leading-6">
                FTC/FRC checks use motor power, encoder motion, battery voltage,
                gyro heading, and odometry. Power and voltage limits below are
                editable before validation.
              </p>
            )}
          </fieldset>
        </section>
        <div className="min-w-0 space-y-6">
          <TrajectoryExplorer
            rows={rows}
            baseline={baselineRows}
            limits={chartLimits}
            excluded={result?.exclusions.map((e) => e.trial_index)}
            units={metadata.units}
          />
          <div className="robotics-panel flex flex-wrap items-center gap-5 text-sm">
            <label className="cursor-pointer font-medium">
              Overlay another run
              <input
                type="file"
                className="sr-only"
                accept=".csv,.json"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  try {
                    if (f.size > 4_000_000)
                      throw new Error("Comparison data must be under 4 MB.");
                    const text = await f.text(),
                      data = f.name.endsWith(".csv")
                        ? parseCsv(text)
                        : parseRows(text);
                    setBaselineRows(data);
                    setBaselineName(f.name);
                  } catch (err) {
                    setError(
                      err instanceof Error
                        ? err.message
                        : "Invalid comparison file.",
                    );
                  }
                  e.target.value = "";
                }}
              />
            </label>
            {baselineRows.length > 0 && (
              <>
                <span>{baselineName}</span>
                <button
                  onClick={() => {
                    setBaselineRows([]);
                    setBaselineName("");
                  }}
                >
                  Remove overlay
                </button>
              </>
            )}
          </div>
        </div>
      </div>
      <SimRealComparisonPanel
        roboticsLimits={profileKind === "robotics" ? chartLimits : {}}
        conditions={conditions}
        enabled={profileKind === "robotics"}
      />
      <div className="mt-6 flex flex-wrap items-center gap-5">
        <button
          onClick={runChecks}
          disabled={busy || importing || !rows.length}
          className="landing-button landing-button-primary disabled:opacity-50"
        >
          {busy ? "Running checks…" : "Run checks"}
        </button>
        <button
          disabled={!rows.length || busy}
          className="text-sm font-medium"
          onClick={() => {
            try {
              setRepair(repairPreview(rows));
              setError("");
            } catch (e) {
              setError(
                e instanceof Error ? e.message : "Could not preview repairs.",
              );
            }
          }}
        >
          Preview data repairs
        </button>
      </div>
      {error && (
        <p
          role="alert"
          className="mt-6 rounded-lg border border-red-400/20 p-4 text-base text-red-400"
        >
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-4 text-sm">
          {notice}
        </p>
      )}
      {repair && (
        <section className="robotics-panel mt-6">
          <h2 className="text-xl font-medium">Repair preview</h2>
          <p className="mt-3 text-base">
            {repair.original_samples} original samples ·{" "}
            {repair.repaired_samples} after proposed changes
          </p>
          <ul className="mt-4 space-y-3 text-sm">
            {repair.proposals.map((p, i) => (
              <li key={i}>
                <p>{p.description}</p>
                {p.changes.slice(0, 5).map((c, j) => (
                  <p className="mt-1 font-mono" key={j}>
                    Sample {c.row + 1}, {c.column}: {String(c.before)} →{" "}
                    {String(c.after)}
                  </p>
                ))}
              </li>
            ))}
            {repair.unrepairable.map((p, i) => (
              <li key={`u${i}`}>{p.reason}</li>
            ))}
          </ul>
          {!repair.proposals.length ? (
            <p className="mt-4">No automatic changes proposed.</p>
          ) : (
            <div className="mt-5 flex flex-wrap gap-5">
              <button
                className="text-sm font-medium"
                onClick={() =>
                  download(
                    "run.repaired.json",
                    JSON.stringify(repair.repaired_data, null, 2),
                  )
                }
              >
                Download repaired copy
              </button>
              <button
                className="text-sm font-medium"
                onClick={() => {
                  useRows(repair.repaired_data, "Repaired copy");
                  setNotice(
                    "Repaired data loaded. Run checks again to review it.",
                  );
                }}
              >
                Use repaired copy
              </button>
            </div>
          )}
          <button className="mt-5 text-sm" onClick={() => setRepair(null)}>
            Close preview
          </button>
        </section>
      )}
      {result && (
        <div className="mt-8 space-y-6">
          <div className="robotics-panel">
            <h2 className="text-2xl font-medium">
              {result.status === "failed"
                ? "Checks failed"
                : result.status === "warning"
                  ? "Review needed"
                  : "No blocking checks"}
            </h2>
            <p className="mt-3 text-base">
              {result.trials_submitted} samples · {result.trials_excluded}{" "}
              excluded · {result.failed} failed checks · {result.warnings}{" "}
              warnings
            </p>
            <p className="mt-3 text-sm leading-6">
              A passing report supports data review. It does not certify
              hardware, policies, or a trajectory for safe execution.
            </p>
          </div>
          <RoboticsRunReport result={result} rows={rows} />
          <section className="robotics-panel">
            <h2 className="text-xl font-medium">Compare reports</h2>
            <div className="mt-5 flex flex-wrap items-center gap-4">
              <select
                aria-label="Baseline validation report"
                className="max-w-full"
                defaultValue=""
                onChange={(e) => {
                  setBaselineReport(
                    history.find((r) => r.id === e.target.value)?.raw ?? null,
                  );
                }}
              >
                <option value="">Choose a previous robotics run</option>
                {history.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
              <label className="cursor-pointer text-sm font-medium">
                Load report JSON
                <input
                  type="file"
                  accept=".json"
                  className="sr-only"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    try {
                      const r = JSON.parse(await f.text());
                      compareReports(r, result);
                      setBaselineReport(r);
                    } catch (err) {
                      setError(
                        err instanceof Error ? err.message : "Invalid report.",
                      );
                    }
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {diff && (
              <div className="mt-5 space-y-3 text-sm">
                <p>
                  {diff.status_before} → {diff.status_after} · excluded sample
                  change {diff.exclusion_delta >= 0 ? "+" : ""}
                  {diff.exclusion_delta}
                </p>
                <p>
                  {diff.same_configuration === null
                    ? "Configuration is unavailable in the older report."
                    : diff.same_configuration
                      ? "Both reports used the same settings."
                      : "Settings differ. Review the profiles before judging a regression."}
                </p>
                {[
                  ["New or worse", diff.introduced],
                  ["Resolved or improved", diff.resolved],
                  ["Persisting", diff.persisting],
                ].map(([label, entries]) => (
                  <div key={String(label)}>
                    <h3 className="font-medium">
                      {String(label)} (
                      {(entries as ReportDiff["introduced"]).length})
                    </h3>
                    <ul className="mt-2 space-y-1">
                      {(entries as ReportDiff["introduced"]).map((i) => (
                        <li key={i.name}>
                          {i.name}: {i.before} → {i.after}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {diff.episode_changes.map((e) => (
                  <p key={e.episode_id}>
                    Episode {e.episode_id}:{" "}
                    {e.before?.flagged_samples ?? "absent"} →{" "}
                    {e.after?.flagged_samples ?? "absent"} flagged samples
                  </p>
                ))}
                <button
                  onClick={() =>
                    download(
                      "report-comparison.json",
                      JSON.stringify(diff, null, 2),
                    )
                  }
                >
                  Download comparison
                </button>
              </div>
            )}
          </section>
        </div>
      )}
      <details className="robotics-panel mt-6">
        <summary className="cursor-pointer text-base font-medium">
          Use these checks in the CLI or CI
        </summary>
        <pre className="mt-5 overflow-x-auto whitespace-pre-wrap font-mono text-sm leading-7">
          {command}
        </pre>
        <div className="mt-5 flex flex-wrap gap-5 text-sm">
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(command);
                setNotice("Command copied.");
              } catch {
                setError(
                  "Clipboard access was unavailable. Select and copy the command above.",
                );
              }
            }}
          >
            Copy command
          </button>
          <button
            onClick={() => {
              try {
                download(
                  "arm-profile.json",
                  JSON.stringify(currentProfile(), null, 2),
                );
              } catch (e) {
                setError(e instanceof Error ? e.message : "Invalid profile.");
              }
            }}
          >
            Download profile
          </button>
          <button
            disabled={!rows.length}
            onClick={() => download("run.json", JSON.stringify(rows, null, 2))}
          >
            Download run JSON
          </button>
          <button
            disabled={!rows.length}
            onClick={() => download("run.csv", toCsv(rows), "text/csv")}
          >
            Download run CSV
          </button>
        </div>
      </details>
      <details className="mt-8">
        <summary className="cursor-pointer text-sm">
          Other validation domains
        </summary>
        <select
          className="mt-4"
          aria-label="Other validation domains"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) onOtherDomain(e.target.value);
          }}
        >
          <option value="">Choose a domain</option>
          {domains
            .filter((d) => d.value !== "robotics")
            .map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
        </select>
      </details>
    </div>
  );
}
