import Image from "next/image";
import Link from "next/link";

const MCP_URL = "https://simapi-mcp.onrender.com/mcp";
const CLAUDE_CONNECTORS_URL = "https://claude.ai/customize/connectors";

export function ClaudeSetup() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header>
        <Link href="/" className="mb-6 inline-flex items-center text-sm text-[var(--ink-secondary)] hover:text-[var(--ink)]">
          ← SimAPI home
        </Link>
        <div className="flex items-center gap-3">
          <Image src="/claude-spark-clay.svg" alt="Claude" width={36} height={36} priority />
          <p className="text-sm font-medium uppercase tracking-[0.12em] text-[var(--amber)]">SimAPI × Claude</p>
        </div>
        <h1 className="mt-4 font-display text-4xl leading-tight tracking-tight text-[var(--ink)] sm:text-5xl">
          Connect SimAPI to Claude
        </h1>
        <p className="mt-3 text-base leading-7 text-[var(--ink-secondary)]">
          Add the remote MCP server to give Claude SimAPI&apos;s robotics validation tools.
        </p>
      </header>

      <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="steps-heading">
        <h2 id="steps-heading" className="text-xl font-medium text-[var(--ink)]">Setup</h2>
        <ol className="mt-5 space-y-5">
          <li>
            <p className="font-medium text-[var(--ink)]">1. Add SimAPI</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              In Claude, open <strong>Customize → Connectors → + Add → Add custom connector</strong>. Name it <strong>SimAPI</strong>.
            </p>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">2. Enter the server URL</p>
            <code className="mt-2 block break-all rounded-lg bg-[#eeeae0] p-3 font-mono text-xs text-[var(--ink)]">{MCP_URL}</code>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Click <strong>Continue</strong>.</p>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">3. Add your MCP key</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              Choose <strong>No sign-in</strong>. Under <strong>Request headers</strong>, add this required header:
            </p>
            <div className="mt-2 grid gap-2 rounded-lg bg-[#eeeae0] p-3 text-xs sm:grid-cols-[130px_1fr]">
              <span className="font-medium text-[var(--ink-muted)]">Header name</span>
              <code className="break-all font-mono text-[var(--ink)]">authorization</code>
              <span className="font-medium text-[var(--ink-muted)]">Header value</span>
              <code className="break-all font-mono text-[var(--ink)]">Bearer &lt;your MCP key&gt;</code>
            </div>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Mark it <strong>Required</strong>, then click <strong>Add</strong>.</p>
          </li>
          <li>
            <p className="font-medium text-[var(--ink)]">4. Use SimAPI in a chat</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              Select <strong>+ → Connectors</strong>, turn on SimAPI, and ask Claude to analyze your robotics data.
            </p>
          </li>
        </ol>

        <p className="mt-6 border-t border-[var(--line)] pt-4 text-xs leading-5 text-[var(--ink-muted)]">
          If <strong>Request headers</strong> doesn&apos;t appear, Claude hasn&apos;t enabled this beta feature for your account yet. See <a className="underline hover:text-[var(--ink)]" href="https://claude.com/docs/connectors/custom/add-unlisted" target="_blank" rel="noreferrer">Claude&apos;s connector guide</a>.
        </p>
      </section>

      <aside className="flex flex-col gap-3 rounded-xl border border-[var(--line)] bg-[var(--paper-soft)] p-5 sm:flex-row sm:items-center sm:justify-between" aria-labelledby="key-heading">
        <div>
          <h2 id="key-heading" className="font-medium text-[var(--ink)]">Need an MCP key?</h2>
          <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Self-service key creation is coming soon. Ask the SimAPI owner for a key.</p>
        </div>
        <button type="button" className="btn-primary shrink-0 cursor-not-allowed opacity-60" disabled>
          Google sign-in — coming soon
        </button>
      </aside>

      <Link href={CLAUDE_CONNECTORS_URL} target="_blank" className="inline-flex text-sm font-medium text-[var(--amber)] hover:underline">
        Open Claude connector settings →
      </Link>
    </div>
  );
}
