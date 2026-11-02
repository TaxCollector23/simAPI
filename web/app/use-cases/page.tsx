import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { PageHero } from "@/components/ui/page-hero";
import { Cta } from "@/components/cta";

export const metadata: Metadata = {
  title: "Use cases",
  description: "Use SimAPI to check simulation data for Physical AI training and robotics workflows.",
};

const cases = [
  {
    index: "01",
    name: "Physical AI",
    question: "Should this simulation data reach training?",
    description: "Synthetic training data can carry solver failures, unit errors, and outliers into a model. Validate batches before they are accepted into a dataset.",
    input: "Simulation trials and conditions",
    result: "A status, issue list, and training_ready signal",
    check: "Inspect excluded and review-flagged rows separately before making a dataset decision.",
  },
  {
    index: "02",
    name: "Robotics",
    question: "Does this run obey the robot's basic physical constraints?",
    description: "The robotics domain includes checks for end effector speed magnitude, manipulability, workspace volume, overshoot, response times, and load versus torque relationships when those fields are present.",
    input: "Robot simulation output as a file or API payload",
    result: "Check results and a pass, warning, or failed verdict",
    check: "Use the verdict as a CI gate, then inspect the specific finding before changing a controller or policy.",
  },
];

export default function UseCases() {
  return (
    <>
      <PageHero
        eyebrow="Use cases"
        title={<>Quality gates for simulated worlds</>}
        lede="SimAPI checks what a run produced before the data moves into training or a robotics workflow."
      />
      <section className="container-tight py-16 sm:py-24">
        <div className="divide-y divide-white/10 border-y border-white/10">
          {cases.map((item) => (
            <article key={item.name} className="grid gap-8 py-10 lg:grid-cols-[220px_1fr] lg:gap-16 lg:py-14">
              <div>
                <span className="font-mono text-sm text-accent-cyan">{item.index}</span>
                <h2 className="mt-3 text-3xl font-medium text-white">{item.name}</h2>
              </div>
              <div>
                <h3 className="max-w-2xl text-balance text-2xl font-medium leading-snug text-white">{item.question}</h3>
                <p className="mt-5 max-w-2xl text-base leading-7 text-white/70">{item.description}</p>
                <dl className="mt-8 grid gap-6 border-t border-white/10 pt-6 sm:grid-cols-2">
                  <div><dt className="text-sm text-white/50">Input</dt><dd className="mt-2 text-sm leading-6 text-white/85">{item.input}</dd></div>
                  <div><dt className="text-sm text-white/50">Result</dt><dd className="mt-2 text-sm leading-6 text-white/85">{item.result}</dd></div>
                </dl>
                <p className="mt-7 max-w-2xl border-l-2 border-accent-cyan pl-5 text-sm leading-6 text-white/70">{item.check}</p>
              </div>
            </article>
          ))}
        </div>
        <Link href="/play" className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:text-white">
          Try a validation <ArrowUpRight className="h-4 w-4" />
        </Link>
      </section>
      <Cta />
    </>
  );
}
