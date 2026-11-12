import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { LiveHealthChart } from "./live-health-chart";

export function Hero() {
  return (
    <section className="landing-hero">
      <div className="landing-wrap hero-layout">
        <div className="hero-copy">
          <p className="hero-context">Robot dataset and trajectory validation</p>
          <h1>Check robot motion data before it moves downstream.</h1>
          <p className="hero-description">
            SimAPI checks recorded joint data against limits you set, finds timing and motion inconsistencies, and shows the evidence behind each finding.
          </p>
          <div className="hero-actions">
            <Link href="/play" className="landing-button landing-button-primary">
              Validate a run <ArrowUpRight size={17} strokeWidth={1.7} />
            </Link>
            <Link href="/docs" className="landing-button landing-button-secondary">How validation works</Link>
          </div>
        </div>
        <LiveHealthChart />
      </div>
    </section>
  );
}
