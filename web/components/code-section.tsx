import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { SectionHeader } from "./ui/section";

const workflows = [
  {
    n: "01",
    title: "Browser",
    text: "Inspect a run and its findings without setting up a local service.",
    href: "/play",
    action: "Open playground",
  },
  {
    n: "02",
    title: "CLI",
    text: "Validate a file from your terminal. Set a fail threshold in CI.",
    href: "/docs",
    action: "CLI guide",
  },
  {
    n: "03",
    title: "SDK",
    text: "Call the same validation workflow from your application.",
    href: "/docs",
    action: "SDK guide",
  },
];

export function CodeSection() {
  return (
    <section className="border-b border-white/10 py-20 sm:py-28">
      <div className="container-tight">
        <SectionHeader
          eyebrow="Use SimAPI"
          title={<>Bring validation into the workflow you already have</>}
          lede="Start in the browser. Move a check into a script or CI when the inputs and thresholds are settled."
        />
        <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10 md:grid-cols-3">
          {workflows.map((item) => (
            <div key={item.n} className="flex h-full flex-col bg-ink-900 p-6 sm:p-8">
              <span className="font-mono text-sm text-accent-cyan">{item.n}</span>
              <h3 className="mt-6 text-2xl font-medium text-white">{item.title}</h3>
              <p className="mt-3 flex-1 text-base leading-7 text-white/65">{item.text}</p>
              <Link href={item.href} className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-white underline decoration-white/30 underline-offset-4 hover:decoration-white">
                {item.action} <ArrowUpRight className="h-4 w-4" />
              </Link>
            </div>
          ))}
        </div>
        <div className="mt-8 rounded-xl border border-white/10 bg-ink-900 p-6 sm:flex sm:items-start sm:justify-between sm:gap-8">
          <div>
            <h3 className="text-lg font-medium text-white">A check that can fail the build</h3>
            <p className="mt-2 max-w-md text-sm leading-6 text-white/60">The CLI exits nonzero when a result reaches your chosen threshold.</p>
          </div>
          <code className="mt-5 block overflow-x-auto whitespace-nowrap rounded-md bg-ink-950 px-4 py-3 font-mono text-sm text-white/85 sm:mt-0">
            simapi validate run.json --type robotics --fail-on warning
          </code>
        </div>
      </div>
    </section>
  );
}
