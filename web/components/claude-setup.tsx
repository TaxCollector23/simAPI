import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight, KeyRound, ShieldCheck } from "lucide-react";

const MCP_URL = "https://simapi-mcp.onrender.com/mcp";
const CLAUDE_CONNECTORS_URL = "https://claude.ai/customize/connectors";

export function ClaudeSetup() {
  return (
    <div className="space-y-12">
      <header className="max-w-3xl">
        <Link href="/" className="mb-8 inline-flex items-center gap-2 text-sm text-[var(--ink-secondary)] hover:text-[var(--ink)]">
          ← SimAPI home
        </Link>
        <div className="flex items-center gap-4">
          <Image src="/claude-spark-clay.svg" alt="" aria-hidden="true" width={48} height={48} priority />
          <p className="text-sm font-medium uppercase tracking-[0.12em] text-[var(--amber)]">SimAPI × Claude</p>
        </div>
        <h1 className="mt-5 font-display text-5xl leading-[1.02] tracking-tight text-[var(--ink)] sm:text-6xl">
          Use SimAPI in Claude.
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-[var(--ink-secondary)]">
          Give Claude the robotics validation tools to inspect trajectories, joint limits, recording quality, and failed checks.
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(310px,0.8fr)]">
        <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="steps-heading">
          <h2 id="steps-heading" className="text-2xl font-medium text-[var(--ink)]">Connect in a few steps</h2>
          <ol className="mt-6 space-y-6">
            <li className="flex gap-4">
              <span className="claude-step-number grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--ink)] text-sm text-white">1</span>
              <div>
                <h3 className="font-medium text-[var(--ink)]">Get an MCP key</h3>
                <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Google login and self-serve key creation are coming soon. For now, you need an MCP key issued by the SimAPI service owner.</p>
              </div>
            </li>
            <li className="flex gap-4">
              <span className="claude-step-number grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--ink)] text-sm text-white">2</span>
              <div>
                <h3 className="font-medium text-[var(--ink)]">Add SimAPI in Claude</h3>
                <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Open Claude’s connector settings, choose <strong>Add custom connector</strong>, and name it <strong>SimAPI</strong>.</p>
                <a href={CLAUDE_CONNECTORS_URL} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-[var(--amber)] hover:underline">
                  Open Claude connector settings <ArrowUpRight size={15} />
                </a>
              </div>
            </li>
            <li className="flex gap-4">
              <span className="claude-step-number grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--ink)] text-sm text-white">3</span>
              <div>
                <h3 className="font-medium text-[var(--ink)]">Set the server and key</h3>
                <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Use this server URL, choose <strong>No sign in</strong>, then add a fixed request header.</p>
                <code className="mt-3 block break-all rounded-lg bg-[#eeeae0] p-3 font-mono text-xs text-[var(--ink)]">{MCP_URL}</code>
                <code className="mt-2 block break-all rounded-lg bg-[#eeeae0] p-3 font-mono text-xs text-[var(--ink)]">Authorization: Bearer &lt;your MCP key&gt;</code>
              </div>
            </li>
            <li className="flex gap-4">
              <span className="claude-step-number grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--ink)] text-sm text-white">4</span>
              <div>
                <h3 className="font-medium text-[var(--ink)]">Enable it in a conversation</h3>
                <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">In a Claude chat, open <strong>+</strong>, choose <strong>Connectors</strong>, enable SimAPI, then ask Claude to analyze a robotics episode.</p>
              </div>
            </li>
          </ol>
          <div className="mt-8 flex gap-3 rounded-lg border border-[var(--line)] bg-white/60 p-4 text-sm leading-6 text-[var(--ink-secondary)]">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[var(--amber)]" />
            <p>Keep the full key private. Claude reuses it for MCP requests. If it is lost, revoke it with the service owner and request another.</p>
          </div>
          <p className="mt-5 text-xs leading-5 text-[var(--ink-muted)]">SimAPI is an independent service and is not affiliated with or endorsed by Anthropic.</p>
        </section>

        <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="key-heading">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-[#eeeae0] text-[var(--amber)]"><KeyRound className="h-5 w-5" /></span>
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--ink-muted)]">Account keys</p>
              <h2 id="key-heading" className="text-xl font-medium text-[var(--ink)]">Google sign-in</h2>
            </div>
          </div>
          <p className="mt-5 text-sm leading-6 text-[var(--ink-secondary)]">
            Account sign-in and personal MCP key creation are not live yet. The button below is a placeholder while this feature is being set up.
          </p>
          <button type="button" className="btn-primary mt-5 w-full cursor-not-allowed opacity-60" disabled aria-describedby="login-placeholder-note">
            Google login — coming soon
          </button>
          <p id="login-placeholder-note" className="mt-3 text-xs leading-5 text-[var(--ink-muted)]">
            If you already have an authorized SimAPI MCP key, you can use it with the steps on this page.
          </p>
        </section>
      </div>

      <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-soft)] p-6 sm:p-8">
        <h2 className="text-xl font-medium text-[var(--ink)]">Try a first prompt</h2>
        <p className="mt-2 text-sm leading-6 text-[var(--ink-secondary)]">After connecting, select SimAPI in the chat’s connector menu and ask Claude: “Use SimAPI to analyze this robot episode. Run the relevant validation checks and explain any failures or warnings with the measurements behind them.”</p>
        <p className="mt-3 text-xs leading-5 text-[var(--ink-muted)]">Claude uses the connector tools from natural language; there is no <code>/simapi</code> slash command.</p>
      </section>
    </div>
  );
}
