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
          Connect Claude to SimAPI&apos;s robotics checks with a remote MCP connector.
        </p>
      </header>

      <aside className="rounded-xl border border-[var(--amber)]/30 bg-[var(--paper-raised)] p-5" aria-labelledby="before-you-start">
        <h2 id="before-you-start" className="font-medium text-[var(--ink)]">Before you start</h2>
        <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
          Ask the SimAPI owner for an MCP key. You&apos;ll paste it into Claude&apos;s connector settings in step 5. Keep the key private.
        </p>
      </aside>

      <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="steps-heading">
        <h2 id="steps-heading" className="text-xl font-medium text-[var(--ink)]">Connect in Claude</h2>
        <ol className="mt-5 space-y-6">
          <li>
            <p className="font-medium text-[var(--ink)]">1. Open custom connectors</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              In Claude, go to <strong>Customize → Connectors</strong>. Click <strong>Add</strong>, hover over <strong>Custom</strong>, then choose <strong>Web</strong>.
            </p>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">2. Name the connector and add its URL</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Enter <strong>SimAPI</strong> as the name. Paste this server URL, then click <strong>Continue</strong>.</p>
            <code className="mt-2 block break-all rounded-lg bg-[#eeeae0] p-3 font-mono text-xs text-[var(--ink)]">{MCP_URL}</code>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">3. Choose header authentication</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              Review the detected settings and click <strong>Continue</strong>. Under <strong>Authentication</strong>, choose <strong>No sign in</strong>, then click <strong>Continue</strong> again.
            </p>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">4. Add your key as a request header</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              Under <strong>Request headers</strong>, add the header below. Replace <code className="rounded bg-[#eeeae0] px-1 py-0.5 font-mono text-xs text-[var(--ink)]">YOUR_MCP_KEY</code> with the key from the SimAPI owner.
            </p>
            <div className="mt-2 grid gap-2 rounded-lg bg-[#eeeae0] p-3 text-xs sm:grid-cols-[130px_1fr]">
              <span className="font-medium text-[var(--ink-muted)]">Header name</span>
              <code className="break-all font-mono text-[var(--ink)]">authorization</code>
              <span className="font-medium text-[var(--ink-muted)]">Header value</span>
              <code className="break-all font-mono text-[var(--ink)]">Bearer YOUR_MCP_KEY</code>
            </div>
            <p className="mt-2 text-sm leading-6 text-[var(--ink-secondary)]">
              Mark the header <strong>Required</strong>. Enter the word <code className="font-mono text-xs">Bearer</code>, one space, then your key. Do not type angle brackets or quotation marks. Click <strong>Add</strong> to save the connector.
            </p>
          </li>
          <li>
            <p className="font-medium text-[var(--ink)]">5. Turn it on in a chat</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">
              Start a Claude chat, open the <strong>+</strong> menu by the message box, choose <strong>Connectors</strong>, and turn on <strong>SimAPI</strong>. Then ask Claude to review your robotics data.
            </p>
          </li>
        </ol>

        <p className="mt-6 border-t border-[var(--line)] pt-4 text-xs leading-5 text-[var(--ink-muted)]">
          If <strong>Request headers</strong> is missing, your Claude account may not have this feature yet. See <a className="underline hover:text-[var(--ink)]" href="https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities" target="_blank" rel="noreferrer">Claude&apos;s current connector instructions</a>.
        </p>
      </section>

      <aside className="flex flex-col gap-3 rounded-xl border border-[var(--line)] bg-[var(--paper-soft)] p-5 sm:flex-row sm:items-center sm:justify-between" aria-labelledby="key-heading">
        <div>
          <h2 id="key-heading" className="font-medium text-[var(--ink)]">Don&apos;t have a key yet?</h2>
          <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">SimAPI does not offer self-service keys yet. Request an MCP key from the SimAPI owner before you start.</p>
        </div>
      </aside>

      <Link href={CLAUDE_CONNECTORS_URL} target="_blank" className="inline-flex text-sm font-medium text-[var(--amber)] hover:underline">
        Open Claude connector settings →
      </Link>
    </div>
  );
}
