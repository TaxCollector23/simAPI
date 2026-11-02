import { Hero } from "@/components/hero";
import { CodeSection } from "@/components/code-section";
import { BenchmarkStats } from "@/components/benchmark-stats";
import { Cta } from "@/components/cta";
import { RoboticsCapabilities } from "@/components/robotics-capabilities";

export default function HomePage() {
  return (
    <div className="landing-page">
      <Hero />
      <CodeSection />
      <RoboticsCapabilities />
      <BenchmarkStats />
      <Cta />
    </div>
  );
}
