import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { SectionHeader } from "./ui/section";
import results from "@/lib/benchmark-results-dimensional.json";

const percent = (value: number, digits = 1) => `${value.toFixed(digits)}%`;
const auto = results.auto_excluded;
const detected = results.total_detected;

export function BenchmarkStats() {
  return (
    <section className="border-b border-white/10 py-20 sm:py-28">
      <div className="container-tight">
        <SectionHeader
          eyebrow="Measured evidence"
          title={<>What the current benchmark shows</>}
          lede={<>This synthetic dimensional-analysis benchmark contains {results.n_train.toLocaleString()} training trials, {percent(results.corruption_rate_pct)} corrupted, across six failure modes and {results.seeds.length} seeds. It is a test of data checks, not a robotics field study.</>}
        />
        <div className="mt-12 grid gap-8 border-y border-white/10 py-8 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
          <div>
            <p className="font-mono text-[clamp(3.5rem,9vw,7rem)] font-medium leading-none tracking-tight text-white tabular-nums">
              {percent(detected.recall * 100)}
            </p>
            <p className="mt-4 text-lg text-white/80">Corrupted rows detected or sent for review</p>
            <p className="mt-3 max-w-lg text-sm leading-6 text-white/55">This figure includes human review flags. It does not mean those rows can all be removed automatically.</p>
          </div>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-1">
            <div className="border-l-2 border-accent-cyan pl-5">
              <p className="font-mono text-3xl font-medium text-white tabular-nums">{percent(auto.recall * 100)}</p>
              <p className="mt-1 text-sm text-white/65">Auto-excluded by verifiable checks</p>
            </div>
            <div className="border-l-2 border-white/25 pl-5">
              <p className="font-mono text-3xl font-medium text-white tabular-nums">{percent(detected.precision * 100, 2)}</p>
              <p className="mt-1 text-sm text-white/65">Precision for detected and review-flagged rows</p>
            </div>
          </div>
        </div>
        <div className="mt-12 grid gap-12 lg:grid-cols-[1fr_1fr]">
          <div>
            <h3 className="text-xl font-medium text-white">Where it works</h3>
            <p className="mt-3 text-sm leading-7 text-white/65">
              The benchmark catches {percent(detected.per_category_recall_pct.unit_conversion)} of injected unit-conversion errors. Anchored physical relationships give the engine an independent reference.
            </p>
          </div>
          <div>
            <h3 className="text-xl font-medium text-white">Where it misses</h3>
            <p className="mt-3 text-sm leading-7 text-white/65">
              Measurement noise is detected at {percent(detected.per_category_recall_pct.measurement_noise)} recall. Small perturbations inside natural variation can look like valid data.
            </p>
          </div>
        </div>
        <div className="mt-12 overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full min-w-[600px] text-left text-sm">
            <caption className="border-b border-white/10 px-5 py-4 text-left text-sm font-medium text-white">Model error after filtering (MAPE, lower is better)</caption>
            <thead className="bg-ink-900 text-white/55">
              <tr><th className="px-5 py-3 font-medium">Model</th><th className="px-5 py-3 font-medium">Corrupted</th><th className="px-5 py-3 font-medium">Naive filter</th><th className="px-5 py-3 font-medium">SimAPI auto-exclusion</th><th className="px-5 py-3 font-medium">Clean ceiling</th></tr>
            </thead>
            <tbody className="divide-y divide-white/10 text-white/80">
              <tr><th className="px-5 py-4 font-medium text-white">Neural net (MLP)</th><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_corrupted_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_naive_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_simapi_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_clean_mean, 2)}</td></tr>
              <tr><th className="px-5 py-4 font-medium text-white">Gradient boosting</th><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_corrupted_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_naive_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_simapi_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_clean_mean, 2)}</td></tr>
            </tbody>
          </table>
        </div>
        <p className="mt-5 max-w-3xl text-sm leading-6 text-white/55">
          On the neural net, naive filtering beats SimAPI&apos;s auto-exclusion tier in this test. The engine leaves some high-magnitude anomalies for review because it cannot prove them physically impossible.
        </p>
        <Link href="/benchmark" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:text-white">
          Read the full method and limitations <ArrowUpRight className="h-4 w-4" />
        </Link>
      </div>
    </section>
  );
}
