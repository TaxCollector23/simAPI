import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ClaudeSpark } from "./claude-spark";

export function Cta() {
  return (
    <section className="py-20 sm:py-24">
      <div className="container-tight flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-2xl">
          <p className="landing-page-kicker">Robotics validation</p>
          <h2 className="mt-3 text-balance text-3xl font-medium sm:text-4xl">Validate a robotics run.</h2>
          <p className="mt-4 max-w-xl text-base leading-7 text-white/65">
            Check motion, limits, and data quality in your browser.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/play" className="landing-button landing-button-primary">Validate a run <ArrowUpRight size={17} strokeWidth={1.7} /></Link>
          <Link href="/docs" className="landing-button landing-button-secondary">Read the workflow docs</Link>
          <Link href="/connect/claude" className="landing-button landing-button-primary landing-button-claude"><ClaudeSpark /> Use in Claude <ArrowUpRight size={17} strokeWidth={1.7} /></Link>
        </div>
      </div>
    </section>
  );
}
