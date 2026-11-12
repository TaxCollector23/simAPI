import type { Metadata } from "next";
import { ClaudeSetup } from "@/components/claude-setup";

export const metadata: Metadata = {
  title: "Use SimAPI in Claude",
  description: "Connect the SimAPI robotics validation tools to Claude with a secure MCP key.",
  robots: { index: true, follow: true },
};

export default function ClaudeConnectPage() {
  return (
    <div className="container-tight mx-auto max-w-5xl pb-24 pt-32 sm:pt-36">
      <ClaudeSetup />
    </div>
  );
}
