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
          eyebrow="Put to the test"
          title={<>How it did in our tests</>}
          lede={<>We tested SimAPI on {results.n_train.toLocaleString()} generated samples with six kinds of errors. These results come from test data, not real robot runs.</>}
        />
        <div className="mt-12 grid gap-8 border-y border-white/10 py-8 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
          <div>
            <p className="font-mono text-[clamp(3.5rem,9vw,7rem)] font-medium leading-none tracking-tight text-white tabular-nums">
              {percent(detected.recall * 100)}
            </p>
            <p className="mt-4 text-lg text-white/80">Errors caught or flagged for review</p>
            <p className="mt-3 max-w-lg text-sm leading-6 text-white/55">Some flagged samples still need a person to review them.</p>
          </div>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-1">
            <div className="border-l-2 border-accent-cyan pl-5">
              <p className="font-mono text-3xl font-medium text-white tabular-nums">{percent(auto.recall * 100)}</p>
              <p className="mt-1 text-sm text-white/65">Known errors removed automatically</p>
            </div>
            <div className="border-l-2 border-white/25 pl-5">
              <p className="font-mono text-3xl font-medium text-white tabular-nums">{percent(detected.precision * 100, 2)}</p>
              <p className="mt-1 text-sm text-white/65">Flagged samples that contained errors</p>
            </div>
          </div>
        </div>
        <div className="mt-12 grid gap-12 lg:grid-cols-[1fr_1fr]">
          <div>
            <h3 className="text-xl font-medium text-white">What it catches well</h3>
            <p className="mt-3 text-sm leading-7 text-white/65">
              It found {percent(detected.per_category_recall_pct.unit_conversion)} of the unit mix-ups added to this test.
            </p>
          </div>
          <div>
            <h3 className="text-xl font-medium text-white">What it can miss</h3>
            <p className="mt-3 text-sm leading-7 text-white/65">
              It found {percent(detected.per_category_recall_pct.measurement_noise)} of the added measurement noise. Small errors can look like normal variation.
            </p>
          </div>
        </div>
        <div className="mt-12 overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full min-w-[600px] text-left text-sm">
            <caption className="border-b border-white/10 px-5 py-4 text-left text-sm font-medium text-white">Prediction error after cleanup (lower is better)</caption>
            <thead className="bg-ink-900 text-white/55">
              <tr><th className="px-5 py-3 font-medium">Model</th><th className="px-5 py-3 font-medium">With errors</th><th className="px-5 py-3 font-medium">Basic cleanup</th><th className="px-5 py-3 font-medium">SimAPI cleanup</th><th className="px-5 py-3 font-medium">Clean data</th></tr>
            </thead>
            <tbody className="divide-y divide-white/10 text-white/80">
              <tr><th className="px-5 py-4 font-medium text-white">Neural network</th><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_corrupted_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_naive_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_simapi_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.mlp.mape_clean_mean, 2)}</td></tr>
              <tr><th className="px-5 py-4 font-medium text-white">Boosted trees</th><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_corrupted_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_naive_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_simapi_mean, 2)}</td><td className="px-5 py-4 font-mono tabular-nums">{percent(results.models.gbt.mape_clean_mean, 2)}</td></tr>
            </tbody>
          </table>
        </div>
        <p className="mt-5 max-w-3xl text-sm leading-6 text-white/55">
          Basic cleanup gave the neural network better results in this test. Some unusual values still need a person to review them.
        </p>
        <Link href="/benchmark" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-accent-cyan hover:text-white">
          See the full test <ArrowUpRight className="h-4 w-4" />
        </Link>
      </div>
    </section>
  );
}
