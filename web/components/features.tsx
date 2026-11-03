import { SectionHeader } from "./ui/section";

const steps = [
  {
    number: "01",
    title: "Submit the run",
    detail: "Load CSV, JSON, ROS 1 bags, or MCAP recordings. Preview the joint signals and select a topic before validation.",
  },
  {
    number: "02",
    title: "Check the motion",
    detail: "Import limits from URDF or use a saved profile. Check joint ranges, sample timing, derived motion, and agreement between position, velocity, and acceleration.",
  },
  {
    number: "03",
    title: "Inspect the evidence",
    detail: "Review the episode, sample, timestamp, signal, observed value, and expected range for a finding. Compare reports or preview repairs before exporting a new dataset.",
  },
  {
    number: "04",
    title: "Gate the next step",
    detail: "Use the result in a training-data review or fail a robotics CI job at the threshold you choose.",
  },
];

export function Features() {
  return (
    <section id="features" className="py-20 sm:py-28">
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
