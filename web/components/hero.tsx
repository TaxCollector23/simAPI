import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ClaudeSpark } from "./claude-spark";

export function Hero() {
  return (
    <section className="landing-hero">
      <div className="landing-wrap hero-layout">
        <div className="hero-copy">
          <p className="hero-context">Clear checks for robot recordings</p>
          <h1>See what happened in a robot run.</h1>
          <p className="hero-description">
            Upload a recording. SimAPI checks it against the limits you choose and shows what needs a closer look.
          </p>
          <div className="hero-actions">
            <Link href="/play" className="landing-button landing-button-primary">
              Try it out <ArrowUpRight size={17} strokeWidth={1.7} />
            </Link>
            <Link href="/connect/claude" className="landing-button landing-button-secondary">
              <ClaudeSpark /> Use in Claude <ArrowUpRight size={17} strokeWidth={1.7} />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
