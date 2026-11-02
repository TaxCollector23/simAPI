import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

const checks = [
  ["Your arm’s limits", "Check joint and tool readings against the limits you set."],
  ["Sudden jumps", "Find movement that would need more speed or acceleration than your arm allows."],
  ["Gaps in the run", "Find broken timestamps and long gaps between samples."],
  ["Numbers that disagree", "Check whether recorded speed and acceleration match the joint’s movement."],
  ["Missing data", "See which checks couldn’t run and what information they need."],
  ["A clear report", "Review each recorded movement. Download your results and keep complete movements together."],
];
const workflow = [
  ["Bring your data", "Upload a CSV or JSON file."],
  ["Add your limits", "Use the settings for your arm."],
  ["Run a check", "See what passed and what needs a look."],
  ["Use the result", "Review the report or stop a job when checks fail."],
];

export function RoboticsCapabilities() {
  return (
    <>
      <section className="py-20 sm:py-28">
        <div className="container-tight">
          <div className="grid gap-10 lg:grid-cols-[.8fr_1.2fr] lg:gap-20">
            <div>
              <h2 className="max-w-md text-balance text-3xl font-medium leading-tight sm:text-4xl">Catch motion and data issues early.</h2>
              <p className="mt-6 max-w-md text-base leading-7 text-white/65">Check joint limits, trajectory continuity, timing, and agreement between recorded and derived motion.</p>
              <Link href="/play" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:underline">Take a closer look <ArrowUpRight size={16} /></Link>
              <p className="mt-8 max-w-md border-t border-white/10 pt-5 text-base leading-7 text-white/65">Use seconds and consistent units. SimAPI helps validate recorded data; it does not certify hardware or guarantee safe operation.</p>
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

      <section className="py-20 sm:py-28">
        <div className="container-tight">
          <h2 className="max-w-2xl text-balance text-3xl font-medium sm:text-4xl">One validation flow, from data to deployment.</h2>
          <ol className="mt-10 grid gap-8 border-y border-white/10 py-8 sm:grid-cols-2 lg:grid-cols-4">
            {workflow.map(([title, copy]) => <li key={title}><h3 className="text-xl font-medium">{title}</h3><p className="mt-3 text-sm leading-6 text-white/65">{copy}</p></li>)}
          </ol>
          <div className="mt-10 grid items-start gap-8 lg:grid-cols-[.8fr_1.2fr] lg:gap-20">
            <div><h3 className="text-xl font-medium">Reuse your validation profile.</h3><p className="mt-3 text-base leading-7 text-white/65">Define limits and timing checks once. Apply the same profile in the browser, CLI, or SDK.</p></div>
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
