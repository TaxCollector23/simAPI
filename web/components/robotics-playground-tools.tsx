"use client";

import { useMemo, useState } from "react";
import { Download, Plus, Trash2, Upload } from "lucide-react";

export type RobotLimitDraft = { signal: string; min: string; max: string };
type Row = Record<string, unknown>;
const trajectoryOptions = [
  { key: "max_time_step", label: "Maximum sample interval", unit: "seconds" },
  { key: "velocity_tolerance", label: "Position / velocity agreement", unit: "velocity units" },
  { key: "acceleration_tolerance", label: "Velocity / acceleration agreement", unit: "acceleration units" },
];
const numericValue = (value: unknown) => typeof value === "number" || (typeof value === "string" && value.trim()) ? Number(value) : NaN;

function readRows(raw: string): Row[] {
  try {
    const value = JSON.parse(raw);
    return Array.isArray(value) ? value.filter((row): row is Row => Boolean(row) && typeof row === "object" && !Array.isArray(row)) : [];
  } catch { return []; }
}

export function csvToRows(source: string): Row[] {
  const matrix: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') { cell += '"'; i++; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell.length === 0) quoted = true;
    else if (char === ",") { row.push(cell); cell = ""; }
    else if (char === "\n" || char === "\r") {
      if (char === "\r" && source[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((item) => item.trim())) matrix.push(row);
      row = [];
    } else cell += char;
  }
  row.push(cell);
  if (row.some((item) => item.trim())) matrix.push(row);
  if (quoted || matrix.length < 2) throw new Error("Choose a CSV with a header and at least one sample row.");
  const headers = matrix[0].map((header, i) => header.trim().replace(i === 0 ? /^\uFEFF/ : /$^/, ""));
  if (headers.some((header) => !header) || new Set(headers).size !== headers.length) {
    throw new Error("CSV column names must be present and unique.");
  }
  return matrix.slice(1).map((values, index) => {
    if (values.length !== headers.length) throw new Error(`CSV row ${index + 2} has the wrong number of columns.`);
    return Object.fromEntries(headers.map((header, i) => {
      const value = values[i].trim();
      if (!value) return [header, null];
      if (["episode_id", "episode", "trajectory_id", "sequence_id"].includes(header.toLowerCase())) return [header, value];
      const numeric = Number(value);
      return [header, Number.isFinite(numeric) ? numeric : value];
    }));
  });
}

export function RoboticsPlaygroundTools({
  rawInput, limits, onLimitsChange, excluded = [], onCsvLoaded, conditions, onConditionsChange,
}: {
  rawInput: string;
  limits: RobotLimitDraft[];
  onLimitsChange: (rows: RobotLimitDraft[]) => void;
  excluded?: number[];
  onCsvLoaded: (json: string) => void;
  conditions: Record<string, number>;
  onConditionsChange: (conditions: Record<string, number>) => void;
}) {
  const rows = useMemo(() => readRows(rawInput), [rawInput]);
  const signals = useMemo(() => {
    const names = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    return names.filter((name) => rows.some((row) => {
      const value = row[name];
      return typeof value === "number" || (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value)));
    }));
  }, [rows]);
  const groupKey = ["episode_id", "episode", "trajectory_id", "sequence_id"].find((key) => rows.some((row) => key in row));
  const episodes = useMemo(() => {
    const map = new Map<string, { name: string; indices: number[] }>();
    rows.forEach((row, index) => {
      const name = groupKey ? String(row[groupKey] ?? "(missing episode)") : "Episode 1";
      if (!map.has(name)) map.set(name, { name, indices: [] });
      map.get(name)!.indices.push(index);
    });
    return [...map.values()];
  }, [rows, groupKey]);
  const [signalChoice, setSignalChoice] = useState("");
  const [episodeChoice, setEpisodeChoice] = useState("");
  const [csvError, setCsvError] = useState("");
  const [profileError, setProfileError] = useState("");
  const excludedSet = new Set(excluded);
  const signal = signals.includes(signalChoice) ? signalChoice : signals.find((name) => /joint|end_effector|tool|gripper/i.test(name)) ?? signals[0];
  const episode = episodes.find((item) => item.name === episodeChoice) ?? episodes[0];
  const activeLimit = limits.find((item) => item.signal === signal);
  const minLimit = activeLimit && activeLimit.min !== "" ? Number(activeLimit.min) : undefined;
  const maxLimit = activeLimit && activeLimit.max !== "" ? Number(activeLimit.max) : undefined;
  const timeColumn = ["time", "timestamp", "simulation_time", "sim_time", "elapsed_time"].find((key) => rows.some((row) => key in row));
  const samples = episode?.indices.map((index) => ({
    index,
    time: timeColumn ? numericValue(rows[index]?.[timeColumn]) : NaN,
    value: numericValue(rows[index]?.[signal ?? ""]),
  })).filter((item) => Number.isFinite(item.value)) ?? [];
  const extents = [
    ...samples.map((sample) => sample.value),
    ...(minLimit === undefined ? [] : [minLimit]),
    ...(maxLimit === undefined ? [] : [maxLimit]),
  ];
  const rawMin = Math.min(...extents), rawMax = Math.max(...extents);
  const pad = (rawMax - rawMin || Math.abs(rawMax) * 0.1 || 1) * 0.12;
  const low = rawMin - pad, high = rawMax + pad;
  const timeAxis = samples.length > 1 && samples.every((sample, index) => Number.isFinite(sample.time) && (!index || sample.time > samples[index - 1].time));
  const x = (index: number) => samples.length < 2 ? 360 : timeAxis ? 38 + (samples[index].time - samples[0].time) * 644 / (samples[samples.length - 1].time - samples[0].time) : 38 + index * 644 / (samples.length - 1);
  const y = (value: number) => 18 + (high - value) * 204 / (high - low || 1);
  const path = samples.map((sample, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(sample.value).toFixed(1)}`).join(" ");

  function addLimit() {
    const available = signals.filter((name) => !limits.some((limit) => limit.signal === name));
    const signal = available.find((name) => /joint|end_effector|tool|gripper/i.test(name)) ?? available[0] ?? "";
    onLimitsChange([...limits, { signal, min: "", max: "" }]);
  }

  return (
    <section className="mt-4 space-y-4" aria-label="Robotics trajectory tools">
      <div className="rounded-xl border border-white/[0.08] bg-ink-900/60 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-white">Arm limits</h3>
            <p className="mt-1 text-xs leading-5 text-white/55">Enter ranges from your robot model or controller. SimAPI does not infer safe limits.</p>
          </div>
          <div className="flex items-center gap-4">
            <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-white/60 hover:text-white">
              Load profile
              <input className="sr-only" type="file" accept="application/json,.json" onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                try {
                  const parsed = JSON.parse(await file.text());
                  const source = parsed.robotics_limits ?? parsed;
                  if (!source || typeof source !== "object" || Array.isArray(source)) throw new Error("Profile must contain a robotics_limits map.");
                  const next = Object.entries(source).map(([signal, range]) => {
                    if (!Array.isArray(range) || range.length !== 2 || !range.every((value) => typeof value === "number" && Number.isFinite(value)) || range[0] >= range[1]) {
                      throw new Error(`Invalid range for ${signal}. Use [minimum, maximum].`);
                    }
                    return { signal, min: String(range[0]), max: String(range[1]) };
                  });
                  const nextConditions = { ...conditions };
                  for (const option of trajectoryOptions) {
                    delete nextConditions[option.key];
                    const value = parsed.conditions?.[option.key];
                    if (value !== undefined) {
                      if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) throw new Error(`${option.key} must be a positive number.`);
                      nextConditions[option.key] = value;
                    }
                  }
                  onLimitsChange(next);
                  onConditionsChange(nextConditions);
                  setProfileError("");
                } catch (error) { setProfileError(error instanceof Error ? error.message : "Could not read profile."); }
                event.target.value = "";
              }} />
            </label>
            {(limits.length > 0 || trajectoryOptions.some((item) => conditions[item.key] !== undefined)) && <button type="button" onClick={() => {
              try {
                const options = Object.fromEntries(trajectoryOptions.filter((item) => conditions[item.key] !== undefined).map((item) => [item.key, conditions[item.key]]));
                if (Object.values(options).some((value) => !Number.isFinite(value) || value <= 0)) throw new Error("Trajectory check settings must be positive numbers.");
                const body = JSON.stringify({ robotics_limits: toRoboticsLimits(limits), conditions: options }, null, 2);
                const link = document.createElement("a");
                link.href = URL.createObjectURL(new Blob([body], { type: "application/json" }));
                link.download = "arm-profile.json";
                link.click();
                window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
                setProfileError("");
              } catch (error) { setProfileError(error instanceof Error ? error.message : "Complete the profile before downloading it."); }
            }} className="inline-flex items-center gap-1.5 text-xs text-white/60 hover:text-white"><Download size={14} /> Save profile</button>}
            <button type="button" onClick={addLimit} className="inline-flex items-center gap-1.5 text-xs font-medium text-accent-cyan hover:underline">
              <Plus size={15} /> Add signal limit
            </button>
          </div>
        </div>
        {profileError && <p className="mt-3 text-xs text-red-400">{profileError}</p>}
        {limits.length === 0 ? (
          <p className="mt-4 border-t border-white/[0.08] pt-3 text-xs text-white/45">No model-specific limits set. Broad plausibility checks still run.</p>
        ) : (
          <div className="mt-4 space-y-2">
            {limits.map((limit, index) => (
              <div key={index} className="grid grid-cols-[minmax(0,1.2fr)_minmax(72px,.8fr)_minmax(72px,.8fr)_32px] items-center gap-2">
                <input aria-label={`Signal ${index + 1}`} list={`robot-signals-${index}`} value={limit.signal} placeholder="Signal name" onChange={(event) => onLimitsChange(limits.map((item, i) => i === index ? { ...item, signal: event.target.value } : item))} className="min-w-0 rounded-md border border-white/10 bg-black/20 px-2 py-2 text-xs" />
                <datalist id={`robot-signals-${index}`}>{signals.map((name) => <option key={name} value={name} />)}</datalist>
                <input aria-label="Minimum" type="number" step="any" value={limit.min} placeholder="Min" onChange={(event) => onLimitsChange(limits.map((item, i) => i === index ? { ...item, min: event.target.value } : item))} className="w-full rounded-md border border-white/10 bg-black/20 px-2 py-2 text-xs" />
                <input aria-label="Maximum" type="number" step="any" value={limit.max} placeholder="Max" onChange={(event) => onLimitsChange(limits.map((item, i) => i === index ? { ...item, max: event.target.value } : item))} className="w-full rounded-md border border-white/10 bg-black/20 px-2 py-2 text-xs" />
                <button type="button" aria-label="Remove limit" onClick={() => onLimitsChange(limits.filter((_, i) => i !== index))} className="flex h-8 items-center justify-center text-white/40 hover:text-red-400"><Trash2 size={15} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-white/[0.08] bg-ink-900/60 p-4">
        <h3 className="text-sm font-medium text-white">Trajectory checks</h3>
        <p className="mt-2 text-sm leading-6 text-white/55">Timestamps are seconds; joint positions must be unwrapped. Optional agreement tolerances compare interval motion with recorded velocity or acceleration.</p>
        <div className="mt-4 space-y-3">
          {trajectoryOptions.map((option) => <label key={option.key} className="flex items-center justify-between gap-4 text-sm text-white/65">
            <span>{option.label}<span className="mt-1 block text-xs text-white/45">{option.unit}</span></span>
            <input aria-label={option.label} type="number" step="any" min="0" placeholder="Optional" value={conditions[option.key] ?? ""} onChange={(event) => {
              const next = { ...conditions };
              if (event.target.value === "") delete next[option.key]; else next[option.key] = Number(event.target.value);
              onConditionsChange(next);
            }} className="w-28 rounded-md border border-white/10 bg-black/20 px-2 py-2 text-sm" />
          </label>)}
        </div>
        <p className="mt-4 border-t border-white/10 pt-3 text-sm text-white/55">A declared joint velocity or acceleration limit also checks motion derived from the preceding joint state.</p>
      </div>

      <div className="rounded-xl border border-white/[0.08] bg-ink-900/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-white">Trajectory preview</h3>
            <p className="mt-1 text-xs text-white/50">{rows.length} samples · {episodes.length} {episodes.length === 1 ? "episode" : "episodes"}</p>
          </div>
          <div className="flex gap-2">
            {episodes.length > 1 && <select aria-label="Episode" value={episode?.name ?? ""} onChange={(event) => setEpisodeChoice(event.target.value)} className="max-w-40 rounded-md border border-white/10 bg-black/20 px-2 py-1.5 text-xs">{episodes.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.indices.length}</option>)}</select>}
            {signals.length > 0 && <select aria-label="Trajectory signal" value={signal} onChange={(event) => setSignalChoice(event.target.value)} className="max-w-48 rounded-md border border-white/10 bg-black/20 px-2 py-1.5 text-xs">{signals.map((name) => <option key={name} value={name}>{name}</option>)}</select>}
          </div>
        </div>
        {samples.length > 1 ? (
          <>
            <svg className="mt-4 block h-auto w-full" viewBox="0 0 720 250" role="img" aria-label={`${signal} trajectory for ${episode?.name}`}>
              {[0, 1, 2, 3].map((line) => <line key={line} x1="38" x2="682" y1={18 + line * 68} y2={18 + line * 68} stroke="#d8d4ca" strokeWidth="1" />)}
              {minLimit !== undefined && <line x1="38" x2="682" y1={y(minLimit)} y2={y(minLimit)} stroke="#a95624" strokeDasharray="5 5" />}
              {maxLimit !== undefined && <line x1="38" x2="682" y1={y(maxLimit)} y2={y(maxLimit)} stroke="#a95624" strokeDasharray="5 5" />}
              <path d={path} fill="none" stroke="#34372f" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
              {samples.map((sample, i) => {
                const outOfRange = (minLimit !== undefined && sample.value < minLimit) || (maxLimit !== undefined && sample.value > maxLimit);
                const excludedSample = excludedSet.has(sample.index);
                return (outOfRange || excludedSample) ? <circle key={sample.index} cx={x(i)} cy={y(sample.value)} r="4.5" fill={outOfRange ? "#a13c32" : "#a95624"} /> : null;
              })}
              <text x="38" y="244" fill="#747168" fontSize="11">{timeAxis ? `${samples[0].time} s` : "sample 1"}</text>
              <text x="682" y="244" fill="#747168" fontSize="11" textAnchor="end">{timeAxis ? `${samples[samples.length - 1].time} s` : `sample ${samples.length}`}</text>
            </svg>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.08] pt-3">
              <p className="text-xs text-white/50">{signal} · {samples.length} points in {episode?.name}</p>
              {(minLimit !== undefined || maxLimit !== undefined) && <p className="font-mono text-xs text-accent-cyan">limits {minLimit ?? "−∞"} to {maxLimit ?? "+∞"}</p>}
            </div>
            <div className="mt-3 max-h-36 overflow-auto border-t border-white/[0.08] pt-2">
              {samples.filter((sample) => excludedSet.has(sample.index) || (minLimit !== undefined && sample.value < minLimit) || (maxLimit !== undefined && sample.value > maxLimit)).slice(0, 8).map((sample) => (
                <div key={sample.index} className="flex justify-between gap-3 py-1 font-mono text-xs text-red-400">
                  <span>sample {sample.index + 1}</span><span>{signal} = {sample.value}</span>
                </div>
              ))}
              {!samples.some((sample) => excludedSet.has(sample.index) || (minLimit !== undefined && sample.value < minLimit) || (maxLimit !== undefined && sample.value > maxLimit)) && <p className="text-xs text-white/45">{minLimit === undefined && maxLimit === undefined ? "No model range configured for this signal." : "No selected-signal samples exceed the configured range."}</p>}
            </div>
          </>
        ) : <p className="mt-4 border-t border-white/[0.08] pt-3 text-xs text-white/45">Add at least two numeric samples for a trajectory preview. Load a CSV or paste a JSON array.</p>}
      </div>
      <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-accent-cyan hover:underline">
        <Upload size={15} /> Load trajectory CSV
        <input className="sr-only" type="file" accept=".csv,text/csv" onChange={async (event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          try { onCsvLoaded(JSON.stringify(csvToRows(await file.text()), null, 2)); setCsvError(""); }
          catch (error) { setCsvError(error instanceof Error ? error.message : "Could not read CSV."); }
          event.target.value = "";
        }} />
      </label>
      {csvError && <p role="alert" className="text-xs text-red-400">{csvError}</p>}
    </section>
  );
}

export function toRoboticsLimits(rows: RobotLimitDraft[]): Record<string, [number, number]> {
  const limits: Record<string, [number, number]> = {};
  for (const row of rows) {
    if (!row.signal && !row.min && !row.max) continue;
    const min = Number(row.min), max = Number(row.max);
    if (!row.signal || row.min === "" || row.max === "" || !Number.isFinite(min) || !Number.isFinite(max) || min >= max) {
      throw new Error("Complete each arm limit with a signal and a minimum below the maximum.");
    }
    if (row.signal in limits) throw new Error(`Limit for ${row.signal} is listed more than once.`);
    limits[row.signal] = [min, max];
  }
  return limits;
}
