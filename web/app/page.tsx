import { Hero } from "@/components/hero";
import { CodeSection } from "@/components/code-section";
import { Cta } from "@/components/cta";
import { RoboticsCapabilities } from "@/components/robotics-capabilities";

export default function HomePage() {
  return (
    <div className="landing-page">
      <Hero />
      <CodeSection />
      <RoboticsCapabilities />
      <Cta />
    </div>
  );
}
