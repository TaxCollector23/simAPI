import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

const checks = [
  ["Joint and tool limits", "Check position, velocity, acceleration, torque, and tool signals against ranges supplied from your robot model or controller."],
  ["Motion between samples", "Catch a position jump that implies too much velocity, or a velocity jump that implies too much acceleration, using your declared limits."],
  ["Timing and dropped samples", "Check that time increases within each episode. Set a maximum sample interval to flag gaps in a trajectory."],
  ["State agreement", "Set an absolute tolerance to compare position changes with recorded velocity, or velocity changes with recorded acceleration."],
  ["Missing evidence", "A configured signal that cannot be checked is reported. Unavailable trajectory checks stay visible instead of becoming a silent pass."],
  ["Episode reports", "Review duration, sample counts, and flagged samples by episode. Export complete unflagged episodes and a machine-readable report."],
];
const workflow = [
  ["Export", "Bring a CSV or JSON run from your simulation workflow."],
  ["Declare", "Load the arm’s signal limits and your sampling tolerances."],
  ["Validate", "Run deterministic checks and inspect the affected samples."],
  ["Gate", "Use the verdict in CI or review episodes before dataset assembly."],
];

export function RoboticsCapabilities() {
  return (
    <>
      <section className="border-b border-white/10 py-20 sm:py-28">
        <div className="container-tight">
          <div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr] lg:gap-20">
            <div>
              <h2 className="max-w-md text-balance text-3xl font-medium leading-tight sm:text-4xl">A plausible value can still be part of a broken trajectory</h2>
              <p className="mt-6 max-w-md text-base leading-7 text-white/65">An arm can stay inside its position limits while moving farther than its velocity limit allows between two timestamps. SimAPI checks both the sample and the motion around it.</p>
              <Link href="/play" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:underline">Inspect an arm trajectory <ArrowUpRight size={16} /></Link>
              <p className="mt-8 max-w-md border-t border-white/10 pt-5 text-sm leading-6 text-white/55">Timestamps are seconds. Joint positions must be unwrapped and use units consistent with the profile. Finite differences describe interval-average motion; they do not prove a peak or collision constraint.</p>
            </div>
            <dl className="border-t border-white/10">
              {checks.map(([title, copy], index) => <div key={title} className="grid grid-cols-[28px_1fr] gap-4 border-b border-white/10 py-5">
                <span aria-hidden="true" className="pt-0.5 font-mono text-sm text-accent-cyan">{String(index + 1).padStart(2, "0")}</span>
                <div><dt className="text-lg font-medium">{title}</dt><dd className="mt-2 text-sm leading-6 text-white/65">{copy}</dd></div>
              </div>)}
            </dl>
          </div>
        </div>
      </section>

      <section className="border-b border-white/10 py-20 sm:py-28">
        <div className="container-tight">
          <h2 className="max-w-2xl text-balance text-3xl font-medium sm:text-4xl">One review step between simulation and the next run</h2>
          <ol className="mt-10 grid gap-8 border-y border-white/10 py-8 sm:grid-cols-2 lg:grid-cols-4">
            {workflow.map(([title, copy]) => <li key={title}><h3 className="text-xl font-medium">{title}</h3><p className="mt-3 text-sm leading-6 text-white/65">{copy}</p></li>)}
          </ol>
          <div className="mt-10 grid items-start gap-8 lg:grid-cols-[.8fr_1.2fr] lg:gap-20">
            <div><h3 className="text-xl font-medium">The same arm profile in the browser and CLI</h3><p className="mt-3 text-sm leading-7 text-white/65">Configure limits in the playground, save the profile, and reuse it in your simulator job or CI pipeline. A profile carries signal ranges and optional timing or derivative tolerances.</p><p className="mt-4 text-sm leading-6 text-white/55">These numbers are an example. Replace them with the limits and units for your arm.</p></div>
            <div className="overflow-hidden rounded-lg border border-white/10 bg-ink-900">
              <p className="border-b border-white/10 px-5 py-3 font-mono text-sm text-white/55">arm-profile.json</p>
              <pre className="overflow-x-auto p-5 font-mono text-sm leading-7 text-[#24241f]">{`{
  "robotics_limits": {
    "joint_1_position": [-1.57, 1.57],
    "joint_1_velocity": [-2, 2],
    "joint_1_acceleration": [-5, 5]
  },
  "conditions": {
    "max_time_step": 0.02,
    "velocity_tolerance": 0.1
  }
}`}</pre>
              <p className="overflow-x-auto border-t border-white/10 px-5 py-4 font-mono text-sm">simapi validate run.csv --profile arm-profile.json --fail-on failed</p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
