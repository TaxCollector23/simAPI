"use client";

import { useMemo, useState } from "react";
import {
  episodeOf,
  numeric,
  rowKeys,
  type Row,
} from "@/lib/robotics-workflow.js";

const colors = ["#34372f", "#a95624", "#38664d", "#70523d"];
export function TrajectoryExplorer({
  rows,
  baseline = [],
  limits,
  excluded = [],
  units = {},
}: {
  rows: Row[];
  baseline?: Row[];
  limits: Record<string, [number, number]>;
  excluded?: number[];
  units?: Record<string, string>;
}) {
  const keys = useMemo(() => rowKeys(rows), [rows]);
  const baseKeys = useMemo(
    () => rowKeys(baseline.length ? baseline : rows),
    [baseline, rows],
  );
  const episodes = [...new Set(rows.map((r) => episodeOf(r, keys.group)))];
  const baseEpisodes = [
    ...new Set(baseline.map((r) => episodeOf(r, baseKeys.group))),
  ];
  const [episode, setEpisode] = useState(""),
    [baseEpisode, setBaseEpisode] = useState(""),
    [selection, setSelection] = useState<string[]>([]),
    [page, setPage] = useState(0);
  const signals = [...new Set(rows.flatMap(Object.keys))].filter(
    (key) =>
      key !== keys.time &&
      key !== keys.group &&
      rows.some((r) => numeric(r[key]) !== null),
  );
  const suggested = ["position", "velocity", "acceleration", "torque", "force"]
    .map((quantity) => signals.find((s) => s.endsWith(`_${quantity}`)))
    .filter((s): s is string => Boolean(s))
    .slice(0, 4);
  const knownSelection = selection.filter((s) => signals.includes(s));
  const selected = knownSelection.length
    ? knownSelection
    : suggested.length
      ? suggested
      : signals.slice(0, 1);
  const currentId = episodes.includes(episode) ? episode : episodes[0],
    baseId = baseline.length
      ? baseEpisodes.includes(baseEpisode)
        ? baseEpisode
        : baseEpisodes[0]
      : baseEpisode;
  const active = rows
    .map((r, i) => ({ row: r, index: i }))
    .filter(({ row }) => episodeOf(row, keys.group) === currentId);
  const activeRows = active.map((v) => v.row);
  const comparison = (baseline.length ? baseline : rows).filter(
    (r) => Boolean(baseId) && episodeOf(r, baseKeys.group) === baseId,
  );
  const excludedSet = new Set(excluded);
  const validTiming = (data: Row[], key?: string) =>
    Boolean(
      key &&
      data.length > 1 &&
      data.every(
        (r, i) =>
          numeric(r[key]) !== null &&
          (!i || Number(r[key]) > Number(data[i - 1][key])),
      ),
    );
  const timed =
    validTiming(activeRows, keys.time) &&
    (!comparison.length || validTiming(comparison, baseKeys.time));
  const offset = (data: Row[], i: number, time?: string) =>
    timed && time ? Number(data[i][time]) - Number(data[0][time]) : i;
  const maxX = Math.max(
    1e-9,
    active.length ? offset(activeRows, active.length - 1, keys.time) : 1,
    comparison.length
      ? offset(comparison, comparison.length - 1, baseKeys.time)
      : 0,
  );
  const x = (v: number) => 52 + (v / maxX) * 636;
  const pageCount = Math.max(1, Math.ceil(active.length / 100)),
    safePage = Math.min(page, pageCount - 1);
  return (
    <section aria-label="Trajectory explorer" className="robotics-panel">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-medium">Trajectories</h2>
        <div className="flex flex-wrap gap-3">
          {episodes.length > 0 && (
            <label className="flex items-center gap-2 text-sm">
              Episode
              <select
                value={currentId}
                onChange={(e) => {
                  setEpisode(e.target.value);
                  setPage(0);
                }}
              >
                {episodes.map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
          )}
          {baseEpisodes.length > 0 && (
            <label className="flex items-center gap-2 text-sm">
              Compare
              <select
                value={baseId}
                onChange={(e) => setBaseEpisode(e.target.value)}
              >
                {baseEpisodes.map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
          )}
          {!baseline.length && episodes.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              Compare episode
              <select
                value={baseEpisode}
                onChange={(e) => setBaseEpisode(e.target.value)}
              >
                <option value="">None</option>
                {episodes.map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>
      <>
        <fieldset className="mt-5 flex flex-wrap gap-x-5 gap-y-3">
          <legend className="sr-only">Displayed signals, up to four</legend>
          {signals.map((signal) => (
            <label
              key={signal}
              className="inline-flex items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={selected.includes(signal)}
                disabled={
                  (!selected.includes(signal) && selected.length >= 4) ||
                  (selected.includes(signal) && selected.length === 1)
                }
                onChange={(e) => {
                  if (e.target.checked && selected.length >= 4) return;
                  setSelection(
                    e.target.checked
                      ? [...selected, signal]
                      : selected.filter((s) => s !== signal),
                  );
                }}
              />
              {signal}
            </label>
          ))}
        </fieldset>
        {comparison.length > 0 && (
          <p className="mt-4 text-sm">
            Solid: current run · dashed: comparison · aligned by{" "}
            {timed ? "elapsed time" : "sample index"}
          </p>
        )}
        {selected.map((signal, number) => {
          const range = limits[signal],
            all = [
              ...active.map((v) => numeric(v.row[signal])),
              ...comparison.map((r) => numeric(r[signal])),
              ...(range ?? []),
            ].filter((n): n is number => n !== null);
          if (!all.length) return null;
          const min = Math.min(...all),
            max = Math.max(...all),
            pad = (max - min || 1) * 0.12,
            low = min - pad,
            high = max + pad,
            y = (v: number) => 16 + ((high - v) / (high - low)) * 144;
          const path = (data: Row[], time?: string) => {
            let open = false;
            return data
              .map((r, i) => {
                const v = numeric(r[signal]);
                if (v === null) {
                  open = false;
                  return "";
                }
                const point = `${open ? "L" : "M"}${x(offset(data, i, time)).toFixed(2)},${y(v).toFixed(2)}`;
                open = true;
                return point;
              })
              .join(" ");
          };
          return (
            <figure key={signal} className="mt-6">
              <figcaption className="flex flex-wrap justify-between gap-2 text-sm font-medium">
                <span>
                  {signal}
                  {units[signal] ? ` (${units[signal]})` : ""}
                </span>
                <span>
                  {range
                    ? `Limits ${range[0]} to ${range[1]}`
                    : "No configured limit"}
                </span>
              </figcaption>
              <svg
                viewBox="0 0 720 198"
                className="mt-3 block w-full"
                role="img"
                aria-label={`${signal} for ${currentId}${comparison.length ? ` compared with ${baseId}` : ""}`}
              >
                {[0, 1, 2].map((n) => (
                  <line
                    key={n}
                    x1="52"
                    x2="688"
                    y1={16 + n * 72}
                    y2={16 + n * 72}
                    stroke="#d8d4ca"
                  />
                ))}
                {range?.map((v) => (
                  <line
                    key={v}
                    x1="52"
                    x2="688"
                    y1={y(v)}
                    y2={y(v)}
                    stroke="#a95624"
                    strokeDasharray="3 5"
                  />
                ))}
                <text
                  x="46"
                  y={y(max) + 5}
                  textAnchor="end"
                  fontSize="14"
                  fill="#5f5d55"
                >
                  {Number(max.toPrecision(3))}
                </text>
                <text
                  x="46"
                  y={y(min) + 5}
                  textAnchor="end"
                  fontSize="14"
                  fill="#5f5d55"
                >
                  {Number(min.toPrecision(3))}
                </text>
                <path
                  d={path(activeRows, keys.time)}
                  stroke={colors[number]}
                  fill="none"
                  strokeWidth="2.5"
                  strokeLinejoin="round"
                />
                {comparison.length > 0 && (
                  <path
                    d={path(comparison, baseKeys.time)}
                    stroke="#747168"
                    fill="none"
                    strokeWidth="2"
                    strokeDasharray="6 5"
                  />
                )}
                {active.map(({ row, index }, i) => {
                  const value = numeric(row[signal]);
                  return value !== null &&
                    (excludedSet.has(index) ||
                      (range && (value < range[0] || value > range[1]))) ? (
                    <circle
                      key={index}
                      cx={x(offset(activeRows, i, keys.time))}
                      cy={y(value)}
                      r="4"
                      fill="#a13c32"
                    >
                      <title>{`Sample ${index + 1}, ${signal}=${value}`}</title>
                    </circle>
                  ) : null;
                })}
                <text x="52" y="191" fontSize="14" fill="#5f5d55">
                  0
                </text>
                <text
                  x="688"
                  y="191"
                  textAnchor="end"
                  fontSize="14"
                  fill="#5f5d55"
                >
                  {Number(maxX.toPrecision(4))}{" "}
                  {timed ? "s elapsed" : "sample index"}
                </text>
              </svg>
            </figure>
          );
        })}
        {!active.length && (
          <p className="mt-5 text-base">Load data to inspect joint motion.</p>
        )}
        {!!active.length && (
          <details className="mt-6">
            <summary className="cursor-pointer text-sm font-medium">
              Inspect sample values
            </summary>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th className="p-2">Sample</th>
                    <th className="p-2">Time</th>
                    {selected.map((s) => (
                      <th className="p-2" key={s}>
                        {s}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {active
                    .slice(safePage * 100, (safePage + 1) * 100)
                    .map(({ row, index }) => (
                      <tr key={index} className="border-t border-white/10">
                        <td className="p-2">{index + 1}</td>
                        <td className="p-2">
                          {keys.time
                            ? String(row[keys.time] ?? "Unavailable")
                            : "Unavailable"}
                        </td>
                        {selected.map((s) => (
                          <td key={s} className="p-2">
                            {String(row[s] ?? "Unavailable")}
                          </td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex gap-4 text-sm">
              <button
                disabled={!safePage}
                onClick={() => setPage(safePage - 1)}
              >
                Previous
              </button>
              <span>
                Page {safePage + 1} of {pageCount}
              </span>
              <button
                disabled={safePage + 1 >= pageCount}
                onClick={() => setPage(safePage + 1)}
              >
                Next
              </button>
            </div>
          </details>
        )}
      </>
    </section>
  );
}
