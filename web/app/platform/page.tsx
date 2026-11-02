import type { Metadata } from "next";
import { Features } from "@/components/features";
import { BenchmarkStats } from "@/components/benchmark-stats";
import { Cta } from "@/components/cta";

export const metadata: Metadata = {
  title: "Platform",
  description:
    "How SimAPI takes simulation output through checks, evidence review, and a pipeline gate.",
};

export default function PlatformPage() {
  return (
    <div className="pt-16">
      <Features />
      <BenchmarkStats />
      <Cta />
    </div>
  );
}
