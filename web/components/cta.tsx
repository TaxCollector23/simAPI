import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

export function Cta() {
  return (
    <section className="py-20 sm:py-28">
      <div className="container-tight grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <p className="text-sm font-medium text-accent-cyan">Next step</p>
          <h2 className="mt-4 max-w-2xl text-balance text-3xl font-medium leading-tight text-white sm:text-4xl">
            Put a physics check between simulation and the next decision
          </h2>
          <p className="mt-4 max-w-xl text-base leading-7 text-white/65">
            Try a run in the browser, then use the CLI or SDK when you are ready to make validation part of your pipeline.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/play" className="btn-accent">Open playground <ArrowUpRight className="h-4 w-4" /></Link>
          <Link href="/docs" className="btn-ghost">Read the docs</Link>
        </div>
      </div>
    </section>
  );
}
