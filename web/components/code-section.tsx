import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

const entryPoints = [
  { name: "Browser", copy: "Upload a run and read the checks and affected samples.", href: "/play" },
  { name: "CLI", copy: "Validate a file from your terminal or fail a CI job at a chosen severity.", href: "/docs/sdks/cli" },
  { name: "SDK / API", copy: "Send records and robot-specific ranges from Python, Node.js, or your service.", href: "/docs/quickstart" },
];

export function CodeSection() {
  return (
    <section className="border-b border-white/10 py-20 sm:py-28">
      <div className="container-tight">
        <div className="max-w-2xl">
          <p className="landing-page-kicker">Manipulation arms</p>
          <h2 className="mt-3 text-balance text-3xl font-medium sm:text-4xl">Check joint and tool data against the limits for your arm</h2>
          <p className="mt-5 text-base leading-7 text-white/65">
            SimAPI screens joint position, velocity, acceleration, torque, and end-effector signals. It checks sample time order within episodes and applies per-signal ranges from your robot model; violations fail validation and identify affected samples.
          </p>
        </div>
        <p className="mt-5 max-w-2xl text-sm leading-6 text-white/65">
          Use it on the hosted service. No validation server to install or maintain.
        </p>
        <div className="mt-12 grid border-y border-white/10 md:grid-cols-3">
          {entryPoints.map((item, index) => (
            <article key={item.name} className={`py-6 md:py-7 ${index ? "md:border-l md:border-white/10 md:pl-7" : "md:pr-7"} ${index === 1 ? "md:px-7" : ""}`}>
              <h3 className="text-xl font-medium">{item.name}</h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-white/65">{item.copy}</p>
              <Link href={item.href} className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:underline">
                Learn how <ArrowUpRight size={16} strokeWidth={1.7} />
              </Link>
            </article>
          ))}
        </div>
        <div className="landing-terminal mt-8 flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="max-w-sm text-sm leading-6 text-white/65">Add a deterministic robotics validation gate to a pipeline.</p>
          <code className="overflow-x-auto whitespace-nowrap font-mono text-sm">simapi validate episode.csv --type robotics --fail-on warning</code>
        </div>
      </div>
    </section>
  );
}
