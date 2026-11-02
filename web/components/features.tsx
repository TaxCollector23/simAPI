import { SectionHeader } from "./ui/section";

const steps = [
  {
    number: "01",
    title: "Submit the run",
    detail: "Send rows of simulation output with a domain and any known conditions. The browser accepts JSON; the CLI and API fit into scripts and CI.",
  },
  {
    number: "02",
    title: "Check the physics",
    detail: "The engine checks plausible ranges, dimensional and cross-variable consistency, conservation relationships, and statistical anomalies when the needed fields are present.",
  },
  {
    number: "03",
    title: "Inspect the evidence",
    detail: "Get a status, issues, exclusions, and supporting values. An optional AI review can add context when configured; deterministic findings remain visible on their own.",
  },
  {
    number: "04",
    title: "Gate the next step",
    detail: "Use the result in a training-data review or fail a robotics CI job at the threshold you choose.",
  },
];

export function Features() {
  return (
    <section id="features" className="border-b border-white/10 py-20 sm:py-28">
      <div className="container-tight">
        <SectionHeader
          eyebrow="Platform"
          title={<>A validation result you can act on</>}
          lede="The useful output is the evidence behind a verdict: which rule ran, what value triggered it, and what happened to the affected rows."
        />
        <div className="mt-12 divide-y divide-white/10 border-y border-white/10">
          {steps.map((step) => (
            <div key={step.number} className="grid gap-4 py-7 sm:grid-cols-[72px_260px_1fr] sm:items-start sm:gap-8">
              <span className="font-mono text-sm text-accent-cyan">{step.number}</span>
              <h3 className="text-xl font-medium text-white">{step.title}</h3>
              <p className="max-w-2xl text-base leading-7 text-white/65">{step.detail}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
