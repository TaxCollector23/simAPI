import { Hero } from "@/components/hero";
import { RoboticsCapabilities } from "@/components/robotics-capabilities";

export default function HomePage() {
  return (
    <div className="landing-page">
      <Hero />
      <RoboticsCapabilities />
    </div>
  );
}
