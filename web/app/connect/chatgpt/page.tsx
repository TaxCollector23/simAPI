import type { Metadata } from "next";
import Link from "next/link";
import { ChatGPTMark } from "@/components/chatgpt-mark";

const MCP_URL = "https://simapi-mcp.onrender.com/mcp";
const CHATGPT_MCP_GUIDE = "https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt";

export const metadata: Metadata = {
  title: "Use SimAPI in ChatGPT",
  description: "Connect the SimAPI robotics tools to ChatGPT as a custom MCP server.",
};

export default function ChatGPTConnectPage() {
  return (
    <div className="container-tight mx-auto max-w-5xl pb-24 pt-32 sm:pt-36">
      <div className="mx-auto max-w-3xl space-y-8">
        <header>
          <Link href="/connect" className="mb-6 inline-flex items-center text-sm text-[var(--ink-secondary)] hover:text-[var(--ink)]">
            ← Choose an assistant
          </Link>
          <div className="flex items-center gap-3">
            <ChatGPTMark size={36} />
            <p className="text-sm font-medium uppercase tracking-[0.12em] text-[var(--amber)]">SimAPI × ChatGPT</p>
          </div>
          <h1 className="mt-4 font-display text-4xl leading-tight tracking-tight text-[var(--ink)] sm:text-5xl">
            Connect SimAPI to ChatGPT
          </h1>
          <p className="mt-3 text-base leading-7 text-[var(--ink-secondary)]">
            Add SimAPI&apos;s robotics validation tools as a custom MCP server.
          </p>
        </header>

        <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="setup-heading">
          <h2 id="setup-heading" className="text-xl font-medium text-[var(--ink)]">Connection details</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--ink-secondary)]">
            In ChatGPT on the web, open <strong>Plugins → + → Add custom MCP server</strong>. Name it <strong>SimAPI</strong> and enter this server URL:
          </p>
          <code className="mt-3 block break-all rounded-lg bg-[#eeeae0] p-3 font-mono text-xs text-[var(--ink)]">{MCP_URL}</code>

          <div className="mt-6 rounded-lg border border-[var(--line)] bg-[var(--paper-soft)] p-4" role="status">
            <h3 className="font-medium text-[var(--ink)]">ChatGPT sign-in is being configured</h3>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              ChatGPT requires OAuth for authenticated MCP servers. SimAPI currently checks bearer MCP keys, so the Google sign-in/key flow needs a ChatGPT-compatible OAuth connection before setup can finish. Don&apos;t paste a key into ChatGPT.
            </p>
          </div>
        </section>

        <p className="text-sm leading-6 text-[var(--ink-secondary)]">
          Custom MCP connections are available on ChatGPT Business and Enterprise/Edu web workspaces, subject to workspace permissions. See the <a className="font-medium text-[var(--amber)] underline hover:no-underline" href={CHATGPT_MCP_GUIDE} target="_blank" rel="noreferrer">official ChatGPT connection guide</a>.
        </p>
      </div>
    </div>
  );
}
