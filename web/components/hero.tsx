import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

/** Illustrative result using the engine's end-effector-velocity rule. */
function ValidationExample() {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-[0_24px_80px_rgba(0,0,0,0.18)]">
      <div className="flex items-center justify-between gap-4 border-b border-white/10 px-5 py-4 sm:px-6">
        <span className="font-mono text-sm text-white/80">robotics / sample run</span>
        <span className="text-sm text-white/50">Illustrative report</span>
      </div>
      <div className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm text-white/55">Check 01 / end effector velocity</p>
            <h2 className="mt-2 text-xl font-medium text-white sm:text-2xl">One value breaks the rule</h2>
          </div>
          <span className="font-mono text-sm text-fail">Failed</span>
        </div>
        <div className="mt-8 border-b border-white/10 pb-2">
          <svg viewBox="0 0 480 208" className="h-auto w-full" role="img" aria-label="Six end effector velocity samples. Sample four is below zero and fails validation.">
            <line x1="30" y1="150" x2="454" y2="150" stroke="rgba(255,255,255,.23)" strokeDasharray="4 5" />
            <text x="2" y="154" fill="rgba(255,255,255,.5)" fontSize="12">0</text>
            <path d="M36 72 L116 83 L196 92 L276 177 L356 93 L436 76" fill="none" stroke="#b8c6c5" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            {[36, 116, 196, 356, 436].map((x, i) => (
              <circle key={x} cx={x} cy={[72, 83, 92, 93, 76][i]} r="4" fill="#b8c6c5" />
            ))}
            <line x1="276" y1="28" x2="276" y2="177" stroke="#d5a266" strokeWidth="1" strokeDasharray="3 5" />
            <circle cx="276" cy="177" r="6" fill="#d5a266" />
            <text x="286" y="171" fill="#e7c298" fontSize="13" fontFamily="ui-monospace, monospace">−0.08 m/s</text>
            <text x="31" y="201" fill="rgba(255,255,255,.5)" fontSize="12" fontFamily="ui-monospace, monospace">01</text>
            <text x="111" y="201" fill="rgba(255,255,255,.5)" fontSize="12" fontFamily="ui-monospace, monospace">02</text>
            <text x="191" y="201" fill="rgba(255,255,255,.5)" fontSize="12" fontFamily="ui-monospace, monospace">03</text>
            <text x="271" y="201" fill="#e7c298" fontSize="12" fontFamily="ui-monospace, monospace">04</text>
            <text x="351" y="201" fill="rgba(255,255,255,.5)" fontSize="12" fontFamily="ui-monospace, monospace">05</text>
            <text x="431" y="201" fill="rgba(255,255,255,.5)" fontSize="12" fontFamily="ui-monospace, monospace">06</text>
          </svg>
        </div>
        <div className="grid gap-4 pt-5 sm:grid-cols-[1fr_auto] sm:items-end">
          <div>
            <p className="font-mono text-sm text-white/50">rb_ee_vel · magnitude must be ≥ 0</p>
            <p className="mt-2 text-sm leading-6 text-white/75">Sample 04 reports a negative speed magnitude. Inspect the solver output before using this run.</p>
          </div>
          <span className="whitespace-nowrap text-sm text-white/50">1 finding / 6 samples</span>
        </div>
      </div>
    </div>
  );
}

export function Hero() {
  return (
    <section className="border-b border-white/10 pb-20 pt-32 sm:pb-28 sm:pt-40">
      <div className="container-tight grid items-center gap-12 lg:grid-cols-[0.85fr_1.15fr] lg:gap-16">
        <div className="max-w-xl">
          <p className="text-sm font-medium text-accent-cyan">Simulation CI/CD for Physical AI and robotics</p>
          <h1 className="mt-6 text-balance text-[42px] font-medium leading-[1.07] tracking-[-0.025em] text-white sm:text-6xl">
            SimAPI: Simulations you can trust
          </h1>
          <p className="mt-7 max-w-lg text-lg leading-8 text-white/70">
            Check simulation data against physical constraints before it enters a training set or robotics workflow. Review each finding in the browser, or gate a pipeline with the CLI or SDK.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link href="/play" className="btn-accent">Try a validation <ArrowUpRight className="h-4 w-4" /></Link>
            <Link href="/docs" className="btn-ghost">Read the docs</Link>
          </div>
        </div>
        <ValidationExample />
      </div>
    </section>
  );
}
