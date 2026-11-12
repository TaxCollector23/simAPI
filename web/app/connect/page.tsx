import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ClaudeSpark } from "@/components/claude-spark";
import { ChatGPTMark } from "@/components/chatgpt-mark";

export const metadata: Metadata = {
  title: "Use SimAPI in Claude or ChatGPT",
  description: "Choose an AI assistant to connect to SimAPI.",
};

export default function ConnectPage() {
  return (
    <div className="container-tight mx-auto max-w-5xl pb-24 pt-32 sm:pt-36">
      <header className="max-w-2xl">
        <p className="text-sm font-medium uppercase tracking-[0.12em] text-[var(--amber)]">
          SimAPI integrations
        </p>
        <h1 className="mt-4 font-display text-4xl leading-tight tracking-tight text-[var(--ink)] sm:text-5xl">
          Choose where to use SimAPI
        </h1>
        <p className="mt-3 text-base leading-7 text-[var(--ink-secondary)]">
          Connect SimAPI&apos;s robotics validation tools to your AI assistant.
        </p>
      </header>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <Link
          href="/connect/claude"
          className="group rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 transition-colors hover:bg-[var(--paper-soft)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--amber)] sm:p-8"
        >
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-full bg-[#eeeae0]">
              <ClaudeSpark />
            </span>
            <h2 className="text-xl font-medium text-[var(--ink)]">Claude</h2>
          </div>
          <p className="mt-3 text-sm leading-6 text-[var(--ink-secondary)]">
            Add SimAPI as a Claude connector.
          </p>
          <span className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-[var(--amber)] group-hover:underline">
            Set up Claude <ArrowUpRight size={16} />
          </span>
        </Link>

        <Link
          href="/connect/chatgpt"
          className="group rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 transition-colors hover:bg-[var(--paper-soft)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--amber)] sm:p-8"
        >
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-full bg-[#eeeae0]">
              <ChatGPTMark size={20} />
            </span>
            <h2 className="text-xl font-medium text-[var(--ink)]">ChatGPT</h2>
          </div>
          <p className="mt-3 text-sm leading-6 text-[var(--ink-secondary)]">
            Add SimAPI as a custom MCP server in ChatGPT.
          </p>
          <span className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-[var(--amber)] group-hover:underline">
            Set up ChatGPT <ArrowUpRight size={16} />
          </span>
        </Link>
      </div>
    </div>
  );
}
