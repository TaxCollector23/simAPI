import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ClaudeSpark } from "./claude-spark";
import { HeroSignalChart } from "./hero-signal-chart";

export function Hero() {
  return (
    <section className="landing-hero">
      <div className="landing-wrap hero-layout">
        <div className="hero-copy">
          <h1>See what happened in a robot run.</h1>
          <p className="hero-description">
            Upload a recording. SimAPI checks it against the limits you choose and shows what needs a closer look.
          </p>
          <div className="hero-actions">
            <Link href="/play" className="landing-button landing-button-primary">
              Try it out <ArrowUpRight size={17} strokeWidth={1.7} />
            </Link>
            <Link
              href="/connect/claude"
              aria-label="Use SimAPI in Claude"
              className="landing-button landing-button-secondary"
            >
              <span>Use in</span>
              <ClaudeSpark />
              <ArrowUpRight size={17} strokeWidth={1.7} />
            </Link>
          </div>
        </div>
        <HeroSignalChart />
      </div>
    </section>
  );
}
