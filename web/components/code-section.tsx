import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

const entryPoints = [
  { name: "In your browser", copy: "Upload a file and see what needs attention.", href: "/play" },
  { name: "In your terminal", copy: "Check a run with one command. Stop a job if checks fail.", href: "https://github.com/TaxCollector23/simAPI/tree/main/sdk-node#cli" },
  { name: "In your code", copy: "Use Python or Node.js to check runs as they finish.", href: "https://github.com/TaxCollector23/simAPI#python-sdk" },
];

export function CodeSection() {
  return (
    <section className="py-20 sm:py-28">
      <div className="container-tight">
        <div className="max-w-2xl">
          <h2 className="mt-3 text-balance text-3xl font-medium sm:text-4xl">Validate the full robotics workflow.</h2>
          <p className="mt-5 text-base leading-7 text-white/65">
            Check trajectories, joint limits, timing, tool readings, and training data with one repeatable validation flow.
          </p>
        </div>
        <p className="mt-5 max-w-2xl text-sm leading-6 text-white/65">
          Start in the browser, then run the same checks from your CLI or SDK.
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
          <p className="max-w-sm text-sm leading-6 text-white/65">Check a run with one command.</p>
          <code className="overflow-x-auto whitespace-nowrap font-mono text-sm">simapi validate episode.csv --type robotics --fail-on warning</code>
        </div>
      </div>
    </section>
  );
}
