"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { GoogleAuthProvider, signInWithPopup } from "firebase/auth";
import { firebaseAuth } from "@/lib/firebase-client";

const MCP_URL = "https://simapi-mcp.onrender.com/mcp";
const CLAUDE_CONNECTORS_URL = "https://claude.ai/customize/connectors";

export function ClaudeSetup() {
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function createKey() {
    setBusy(true);
    setError("");
    setKey("");
    try {
      const result = await signInWithPopup(firebaseAuth, new GoogleAuthProvider());
      const idToken = await result.user.getIdToken();
      const response = await fetch("/api/v1/keys/generate", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${idToken}`,
        },
        body: JSON.stringify({ label: "Claude MCP" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not create your MCP key.");
      setKey(payload.api_key);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not create your MCP key.";
      setError(message.includes("auth/unauthorized-domain")
        ? "This website domain is not authorized in Firebase Authentication yet. Add simapilander.vercel.app under Authentication → Settings → Authorized domains."
        : message);
    } finally {
      setBusy(false);
    }
  }

  async function copyKey() {
    await navigator.clipboard.writeText(key);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

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
          Create a private key, then add the public SimAPI robotics validator as a Claude connector.
        </p>
      </header>

      <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="key-heading">
        <h2 id="key-heading" className="text-xl font-medium text-[var(--ink)]">1. Create your MCP key</h2>
        <p className="mt-2 text-sm leading-6 text-[var(--ink-secondary)]">
          Sign in with Google. Your key is shown once; SimAPI stores only its hash. Keep the key private.
        </p>
        <button type="button" onClick={createKey} disabled={busy} className="btn-primary mt-4 disabled:cursor-wait disabled:opacity-60">
          {busy ? "Connecting to Google…" : "Continue with Google"}
        </button>
        {error && <p role="alert" className="mt-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900">{error}</p>}
        {key && (
          <div className="mt-4 rounded-lg border border-[var(--line)] bg-[#eeeae0] p-4">
            <p className="text-sm font-medium text-[var(--ink)]">Copy this key now. It cannot be shown again.</p>
            <code className="mt-2 block break-all font-mono text-xs text-[var(--ink)]">{key}</code>
            <button type="button" className="mt-3 rounded-md border border-[var(--line)] px-3 py-2 text-sm font-medium text-[var(--ink)] hover:bg-white" onClick={copyKey}>
              {copied ? "Copied" : "Copy key"}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-[var(--line)] bg-[var(--paper-raised)] p-6 sm:p-8" aria-labelledby="steps-heading">
        <h2 id="steps-heading" className="text-xl font-medium text-[var(--ink)]">2. Add SimAPI in Claude</h2>
        <ol className="mt-5 space-y-5">
          <li>
            <p className="font-medium text-[var(--ink)]">Add a custom connector</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">On Claude web, open <strong>Customize → Connectors → + Add → Custom → Web</strong> (some accounts call this <strong>Add custom connector</strong>). Name it <strong>SimAPI</strong>.</p>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">Enter the server URL</p>
            <code className="mt-2 block break-all rounded-lg bg-[#eeeae0] p-3 font-mono text-xs text-[var(--ink)]">{MCP_URL}</code>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Choose <strong>No sign-in</strong> for Claude&apos;s authentication method. The SimAPI key is sent as a request header.</p>
          </li>
          <li className="min-w-0">
            <p className="font-medium text-[var(--ink)]">Add the key header before pressing Add</p>
            <div className="mt-2 grid gap-2 rounded-lg bg-[#eeeae0] p-3 text-xs sm:grid-cols-[130px_1fr]">
              <span className="font-medium text-[var(--ink-muted)]">Header name</span>
              <code className="break-all font-mono text-[var(--ink)]">authorization</code>
              <span className="font-medium text-[var(--ink-muted)]">Header value</span>
              <code className="break-all font-mono text-[var(--ink)]">Bearer sk_live_your_key</code>
            </div>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Replace <code>sk_live_your_key</code> with the key above. Add the space after <code>Bearer</code>. Then click <strong>Add</strong>.</p>
          </li>
          <li>
            <p className="font-medium text-[var(--ink)]">Use it in a chat</p>
            <p className="mt-1 text-sm leading-6 text-[var(--ink-secondary)]">Open a new chat, select <strong>+ → Connectors</strong>, enable SimAPI, and ask Claude to validate robotics data.</p>
          </li>
        </ol>
        <p className="mt-6 border-t border-[var(--line)] pt-4 text-xs leading-5 text-[var(--ink-muted)]">
          Free accounts can add one custom connector. On Team or Enterprise, an Owner or Primary Owner must add it for the organization. If the option is missing, try Claude web and check whether your plan or organization permits custom connectors.
        </p>
      </section>

      <Link href={CLAUDE_CONNECTORS_URL} target="_blank" className="inline-flex text-sm font-medium text-[var(--amber)] hover:underline">
        Open Claude connector settings →
      </Link>
    </div>
  );
}
