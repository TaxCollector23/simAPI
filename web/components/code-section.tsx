import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

const entryPoints = [
  { name: "In your browser", copy: "Upload CSV or JSON, or open a supported ROS 1 bag or MCAP recording. Select its signals and review findings.", href: "/play", action: "Open the validator" },
  { name: "In your terminal", copy: "Validate a file with a saved robot profile and return a failing exit code when it crosses your chosen threshold.", href: "https://github.com/TaxCollector23/simAPI/tree/main/sdk-node#cli", action: "Read the CLI guide" },
  { name: "In your code", copy: "Call the Python or Node.js SDK to validate runs from your data pipeline.", href: "https://github.com/TaxCollector23/simAPI#python-sdk", action: "View SDK setup" },
];

export function CodeSection() {
  return (
    <section className="py-20 sm:py-28">
      <div className="container-tight">
        <div className="max-w-2xl">
          <h2 className="mt-3 text-balance text-3xl font-medium sm:text-4xl">Run trajectory checks in the browser, CLI, or SDK.</h2>
          <p className="mt-5 text-base leading-7 text-white/65">
            SimAPI checks recorded robot signals against limits and timing rules you configure, then returns a report with the values and samples behind each finding.
          </p>
        </div>
        <p className="mt-5 max-w-2xl text-sm leading-6 text-white/65">
          Choose the interface that fits your data workflow; use the CLI threshold to gate a job when checks fail.
        </p>
        <div className="mt-12 grid border-y border-white/10 md:grid-cols-3">
          {entryPoints.map((item, index) => (
            <article key={item.name} className={`py-6 md:py-7 ${index ? "md:border-l md:border-white/10 md:pl-7" : "md:pr-7"} ${index === 1 ? "md:px-7" : ""}`}>
              <h3 className="text-xl font-medium">{item.name}</h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-white/65">{item.copy}</p>
              <Link href={item.href} className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:underline">
                {item.action} <ArrowUpRight size={16} strokeWidth={1.7} />
              </Link>
            </article>
          ))}
        </div>
        <div className="landing-terminal mt-8 flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="max-w-sm text-sm leading-6 text-white/65">Example: validate a run with an arm profile and fail on warnings.</p>
          <code className="overflow-x-auto whitespace-nowrap font-mono text-sm">simapi validate episode.csv --profile arm-profile.json --fail-on warning</code>
        </div>
      </div>
    </section>
  );
}
