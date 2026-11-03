"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import type { ValidationResult } from "@/lib/api";

function download(name: string, text: string, type: string) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(new Blob([text], { type }));
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function RoboticsRunReport({
  result,
  rows,
}: {
  result: ValidationResult;
  rows: Record<string, unknown>[];
}) {
  const [evidencePage, setEvidencePage] = useState(0);
  const summary = result.robotics_summary;
  if (!summary) return null;
  const excluded = new Set(result.exclusions.map((item) => item.trial_index));
  const group = (row: Record<string, unknown>) => {
    const key = summary.episode_column;
    const entry = key
      ? Object.entries(row).find(
          ([name]) => name.trim().toLowerCase().replace(/[ .-]/g, "_") === key,
        )
      : undefined;
    return key ? String(entry?.[1] ?? "(missing episode)") : "Episode 1";
  };
  const blocked = new Set(
    rows.filter((_, index) => excluded.has(index)).map(group),
  );
  const accepted = rows.filter((row) => !blocked.has(group(row)));
  function exportEpisodes() {
    const columns = [...new Set(accepted.flatMap((row) => Object.keys(row)))];
    const cell = (value: unknown) =>
      `"${String(value ?? "").replace(/"/g, '""')}"`;
    const lines = [
      columns.map(cell).join(","),
      ...accepted.map((row) =>
        columns.map((column) => cell(row[column])).join(","),
      ),
    ];
    download("simapi-unflagged-episodes.csv", lines.join("\n"), "text/csv");
  }
  return (
    <section
      className="rounded-xl border border-white/10 bg-ink-900 p-5"
      aria-label="Robotics run report"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-xl font-medium text-white">Run report</h2>
        <button
          onClick={() =>
            download(
              "simapi-robotics-report.json",
              JSON.stringify(result, null, 2),
              "application/json",
            )
          }
          className="inline-flex items-center gap-2 text-sm text-accent-cyan hover:underline"
        >
          <Download size={15} /> Report JSON
        </button>
      </div>
      <div className="mt-5 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">
            Episode sampling and flagged samples
          </caption>
          <thead className="border-b border-white/10 text-white/50">
            <tr>
              <th className="py-2 pr-3 font-medium">Episode</th>
              <th className="p-2 font-medium">Samples</th>
              <th className="p-2 font-medium">Duration</th>
              <th className="p-2 font-medium">Flagged</th>
            </tr>
          </thead>
          <tbody>
            {summary.episodes.map((episode) => (
              <tr key={episode.episode_id} className="border-b border-white/10">
                <td className="py-3 pr-3 font-mono">{episode.episode_id}</td>
                <td className="p-2 tabular-nums">{episode.samples}</td>
                <td className="p-2 tabular-nums">
                  {episode.duration_seconds === null
                    ? "Unavailable"
                    : `${Number(episode.duration_seconds.toPrecision(5))} s`}
                </td>
                <td className="p-2 tabular-nums">{episode.flagged_samples}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-5 space-y-3">
        {(result.robotics_checks ?? []).map((check) => (
          <div key={check.name} className="flex items-start gap-3 text-sm">
            <span
              className={`w-16 shrink-0 ${check.status === "failed" ? "text-red-400" : check.status === "warning" ? "text-amber-400" : "text-pass"}`}
            >
              {check.status}
            </span>
            <p className="min-w-0 text-white/65">{check.detail}</p>
          </div>
        ))}
      </div>
      {!!result.robotics_evidence?.length && (
        <div className="mt-6">
          <h3 className="text-base font-medium">Finding evidence</h3>
          {result.robotics_evidence_truncated && (
            <p className="mt-3 text-sm">
              Showing the first {result.robotics_evidence.length} of{" "}
              {result.robotics_evidence_total} findings. Check counts and
              episode totals cover the complete run.
            </p>
          )}
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="p-2 font-medium">Episode / sample</th>
                  <th className="p-2 font-medium">Signal / time</th>
                  <th className="p-2 font-medium">Observed</th>
                  <th className="p-2 font-medium">Expected</th>
                  <th className="p-2 font-medium">Finding</th>
                </tr>
              </thead>
              <tbody>
                {result.robotics_evidence
                  .slice(evidencePage * 25, (evidencePage + 1) * 25)
                  .map((e, i) => (
                    <tr key={i} className="border-t border-white/10">
                      <td className="p-2">
                        {e.episode_id} / {e.sample_index + 1}
                      </td>
                      <td className="p-2">
                        {e.signal}
                        <br />
                        {e.time === null ? "Time unavailable" : `${e.time} s`}
                      </td>
                      <td className="p-2 font-mono">
                        {e.observed === null
                          ? "Unavailable"
                          : Number(e.observed.toPrecision(6))}
                      </td>
                      <td className="p-2 font-mono">
                        {e.expected
                          ? `${Number(e.expected[0].toPrecision(6))} to ${Number(e.expected[1].toPrecision(6))}`
                          : "See finding"}
                      </td>
                      <td className="min-w-64 p-2">{e.detail}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center gap-4 text-sm">
            <button
              disabled={!evidencePage}
              onClick={() => setEvidencePage(evidencePage - 1)}
            >
              Previous
            </button>
            <span>
              Page {evidencePage + 1} of{" "}
              {Math.ceil(result.robotics_evidence.length / 25)}
            </span>
            <button
              disabled={
                (evidencePage + 1) * 25 >= result.robotics_evidence.length
              }
              onClick={() => setEvidencePage(evidencePage + 1)}
            >
              Next
            </button>
          </div>
        </div>
      )}
      <div className="mt-5 border-t border-white/10 pt-4">
        <button
          disabled={!accepted.length}
          onClick={exportEpisodes}
          className="inline-flex items-center gap-2 text-sm text-accent-cyan hover:underline disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Download size={15} /> Export unflagged episodes ({accepted.length}{" "}
          samples)
        </button>
        <p className="mt-2 text-sm leading-6 text-white/55">
          Exports keep complete episodes together. An episode with an excluded
          sample is left out; passing checks does not certify a trajectory for
          hardware.
        </p>
        <details className="mt-3 text-sm text-white/55">
          <summary className="cursor-pointer">Engine assumptions</summary>
          <ul className="mt-2 space-y-1">
            {summary.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      </div>
    </section>
  );
}
