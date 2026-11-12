const checks = [
  ["Joint limits", "See when movement goes outside the limits you choose."],
  ["Changes in motion", "Find sudden jumps in the recorded movement."],
  ["Recording gaps", "Spot missing samples and uneven timing."],
];

const steps = [
  ["Add a recording", "Open a robot run in your browser."],
  ["Choose limits", "Set limits that fit your robot."],
  ["Review the results", "See what needs a closer look and why."],
];

export function RoboticsCapabilities() {
  return (
    <>
      <section className="py-14 sm:py-20">
        <div className="container-tight">
          <div className="max-w-xl">
            <h2 className="text-balance text-3xl font-medium sm:text-4xl">What SimAPI checks</h2>
            <p className="mt-4 text-base leading-7 text-white/65">
              Each result shows the recorded values that led to it.
            </p>
          </div>
          <dl className="mt-8 grid gap-4 sm:grid-cols-3">
            {checks.map(([title, copy]) => (
              <div key={title} className="rounded-xl border border-white/10 bg-white/30 p-5">
                <dt className="text-lg font-medium">{title}</dt>
                <dd className="mt-2 text-sm leading-6 text-white/65">{copy}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-5 text-xs leading-5 text-white/65">SimAPI checks recordings, not the physical robot.</p>
        </div>
      </section>

      <section className="py-14 sm:py-20">
        <div className="container-tight">
          <h2 className="text-balance text-3xl font-medium sm:text-4xl">How it works</h2>
          <ol className="mt-8 grid gap-6 border-y border-white/10 py-7 sm:grid-cols-3">
            {steps.map(([title, copy], index) => (
              <li key={title}>
                <p className="text-sm font-medium text-accent-cyan">Step {index + 1}</p>
                <h3 className="mt-2 text-lg font-medium">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-white/65">{copy}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}
