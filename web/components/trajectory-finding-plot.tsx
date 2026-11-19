import { numeric, type Evidence, type Row } from "@/lib/robotics-workflow.js";
import { findingUnits, findingWindow } from "@/lib/robotics-report-navigation";

function displayNumber(value: number) {
  return Number(value.toPrecision(6)).toString();
}

export function FindingValues({
  finding,
  unit,
}: {
  finding: Evidence;
  unit?: string;
}) {
  const observed = numeric(finding.observed);
  const expected = finding.expected?.every(Number.isFinite) ? finding.expected : null;
  const suffix = unit ? ` ${unit}` : "";
  return (
    <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
      <div>
        <dt className="font-medium">Observed</dt>
        <dd className="tabular-nums">{observed === null ? "Unavailable" : displayNumber(observed) + suffix}</dd>
      </div>
      <div>
        <dt className="font-medium">Expected</dt>
        <dd className="tabular-nums">
          {expected ? `${displayNumber(expected[0])} to ${displayNumber(expected[1])}${suffix}` : finding.expected_min !== undefined
            ? `At least ${displayNumber(finding.expected_min)}${suffix}`
            : "No numeric limit reported"}
        </dd>
      </div>
    </dl>
  );
}

export function TrajectoryFindingPlot({
  finding,
  rows,
  times,
  sample,
  signal,
  units,
  conversions,
}: {
  finding: Evidence;
  rows: Row[];
  times: (number | null)[];
  sample: number;
  signal?: string;
  units: Record<string, string>;
  conversions: Record<string, string>;
}) {
  const window = findingWindow(times, sample, finding);
  if (!window) return null;
  const { unit, factor } = findingUnits(finding, units, conversions);
  const observed = numeric(finding.observed);
  const expected = finding.expected?.every(Number.isFinite) ? finding.expected
    : finding.expected_min !== undefined ? [finding.expected_min] : [];
  // A gap's observed value is the elapsed interval, not the timestamp in its row.
  const plotSeries = signal && finding.check !== "robotics_sample_gaps" && !finding.point_only;
  const samples = plotSeries
    ? rows.map((row, index) => {
        const time = times[index];
        const value = numeric(row[signal]);
        return time !== null && value !== null && time >= window.left && time <= window.right
          ? { time, value: value * factor }
          : null;
      })
    : [];
  const values = [
    ...samples.flatMap((point) => point ? [point.value] : []),
    ...(observed === null ? [] : [observed]),
    ...(expected ?? []),
  ];
  let min = 0, max = 0;
  if (values.length) {
    min = values.reduce((low, value) => Math.min(low, value));
    max = values.reduce((high, value) => Math.max(high, value));
  }
  const padding = (max - min || 1) * 0.18;
  const x = (time: number) => 52 + (time - window.left) / (window.right - window.left) * 636;
  const y = (value: number) => 22 + (max + padding - value) / (max - min + padding * 2) * 124;
  const path = samples.map((point, index) => point
    ? `${samples[index - 1] ? "L" : "M"}${x(point.time)},${y(point.value)}`
    : "").join(" ");
  const observedX = x(window.time);
  const timestamp = window.start === window.end
    ? `${displayNumber(window.time)} s`
    : `${displayNumber(window.start)} to ${displayNumber(window.end)} s`;
  const name = finding.measurement ?? signal ?? finding.signal;

  return (
    <figure className="mt-5 rounded-lg border border-[#d8cbb9] bg-[#f7f2e9] p-4">
      <figcaption className="font-medium">
        {name}{unit ? ` (${unit})` : ""} · {timestamp}
      </figcaption>
      <FindingValues finding={finding} unit={unit} />
      <svg
        viewBox="0 0 720 186"
        className="mt-3 block w-full"
        role="img"
        aria-label={`${name} for ${finding.episode_id}, focused on ${timestamp}`}
      >
        {[22, 84, 146].map((line) => (
          <line key={line} x1={52} x2={688} y1={line} y2={line} stroke="#d8d4ca" />
        ))}
        {window.start !== window.end && (
          <rect x={x(window.start)} y={22} width={x(window.end) - x(window.start)} height={124} fill="#a95624" opacity={0.12} />
        )}
        {[...new Set(expected ?? [])].map((value) => (
          <line key={value} x1={52} x2={688} y1={y(value)} y2={y(value)} stroke="#a95624" strokeDasharray="4 5" />
        ))}
        {values.length > 0 && (
          <>
            <text x={46} y={y(max) + 4} textAnchor="end" fontSize={12} fill="#5f5d55">{displayNumber(max)}</text>
            {min !== max && <text x={46} y={y(min) + 4} textAnchor="end" fontSize={12} fill="#5f5d55">{displayNumber(min)}</text>}
          </>
        )}
        {plotSeries && (
          <>
            <path d={path} fill="none" stroke="#34372f" strokeWidth={2.5} strokeLinejoin="round" />
            {samples.map((point, index) => point && <circle key={index} cx={x(point.time)} cy={y(point.value)} r={2.5} fill="#34372f" />)}
          </>
        )}
        <line x1={observedX} x2={observedX} y1={18} y2={151} stroke="#a95624" strokeWidth={1.5} />
        {observed !== null && (
          <circle cx={observedX} cy={y(observed)} r={7} fill="#a95624" stroke="#fbf9f4" strokeWidth={2}>
            <title>Observed {displayNumber(observed)}{unit ? ` ${unit}` : ""}</title>
          </circle>
        )}
        <text x={52} y={175} fontSize={12} fill="#5f5d55">{displayNumber(window.left)} s</text>
        <text x={688} y={175} textAnchor="end" fontSize={12} fill="#5f5d55">{displayNumber(window.right)} s</text>
      </svg>
    </figure>
  );
}
