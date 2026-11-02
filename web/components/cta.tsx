import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

export function Cta() {
  return (
    <section className="border-b border-white/10 py-20 sm:py-24">
      <div className="container-tight flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-2xl">
          <p className="landing-page-kicker">Start with a file</p>
          <h2 className="mt-3 text-balance text-3xl font-medium sm:text-4xl">See what’s in your run.</h2>
          <p className="mt-4 max-w-xl text-base leading-7 text-white/65">
            Bring a file. Add your arm’s limits. See what needs a look.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/play" className="landing-button landing-button-primary">Check a run <ArrowUpRight size={17} strokeWidth={1.7} /></Link>
          <Link href="/docs" className="landing-button landing-button-secondary">See how it works</Link>
        </div>
      </div>
    </section>
  );
}
