import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

function TrajectoryFigure() {
  return (
    <figure className="trajectory-figure">
      <figcaption className="trajectory-caption">
        <span>Joint trajectory</span>
        <span>Schematic</span>
      </figcaption>
      <svg
        viewBox="0 0 760 430"
        className="trajectory-plot"
        role="img"
        aria-label="Schematic joint position trace over time. One trajectory point crosses a declared limit."
      >
        <defs>
          <pattern id="plot-grid" width="54" height="54" patternUnits="userSpaceOnUse">
            <path d="M 54 0 L 0 0 0 54" fill="none" stroke="#d7d1c5" strokeWidth="1" />
          </pattern>
        </defs>
        <rect x="62" y="30" width="670" height="334" fill="url(#plot-grid)" />
        <line x1="62" y1="98" x2="732" y2="98" stroke="#b9b1a4" strokeWidth="1.5" strokeDasharray="7 7" />
        <line x1="62" y1="364" x2="732" y2="364" stroke="#736d63" strokeWidth="1.5" />
        <line x1="62" y1="30" x2="62" y2="364" stroke="#736d63" strokeWidth="1.5" />
        <text x="62" y="404" className="plot-axis">time →</text>
        <text x="20" y="230" transform="rotate(-90 20 230)" className="plot-axis">joint position</text>
        <text x="76" y="87" className="plot-note">declared limit</text>
        <path d="M82 281 C126 264 144 188 196 171 S265 195 304 185 S369 77 425 88 S489 167 528 154 S602 180 642 134 S692 146 718 120" fill="none" stroke="#34372f" strokeWidth="4" strokeLinecap="round" />
        <path d="M369 77 C385 60 405 49 425 88" fill="none" stroke="#b86c32" strokeWidth="4" strokeLinecap="round" />
        <line x1="398" y1="40" x2="398" y2="364" stroke="#b86c32" strokeWidth="1.5" strokeDasharray="5 7" />
        <circle cx="398" cy="67" r="7" fill="#b86c32" stroke="#f7f4ee" strokeWidth="3" />
        <path d="M414 62 H518" fill="none" stroke="#b86c32" strokeWidth="1.5" />
        <text x="526" y="67" className="plot-callout">limit crossed</text>
        <text x="83" y="347" className="plot-tick">episode start</text>
        <text x="640" y="347" className="plot-tick">episode end</text>
      </svg>
      <p className="trajectory-note">Example only. The trace shows a joint sample crossing a configured position limit.</p>
    </figure>
  );
}

export function Hero() {
  return (
    <section className="landing-hero">
      <div className="landing-wrap hero-layout">
        <div className="hero-copy">
          <p className="hero-context">Validation for manipulation robotics</p>
          <h1>SimAPI: Simulations you can trust</h1>
          <p className="hero-description">
            Catch broken joint and end-effector data before it reaches a policy, dataset, or robot.
          </p>
          <div className="hero-actions">
            <Link href="/play" className="landing-button landing-button-primary">
              Try a validation <ArrowUpRight size={17} strokeWidth={1.7} />
            </Link>
            <Link href="/docs" className="landing-button landing-button-secondary">Read the docs</Link>
          </div>
          <p className="hero-access">Use in the browser, from the CLI, or through an SDK</p>
        </div>
        <TrajectoryFigure />
      </div>
    </section>
  );
}
