"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

const installCommand = "npm install -g simapi-cli";

export function CliInstall() {
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const copied = copyStatus === "copied";

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(installCommand);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }

  return (
    <div className="mt-8 max-w-[24rem]">
      <h2 className="text-sm font-medium">Install the CLI</h2>
      <div className="mt-2 flex items-center gap-2 rounded-lg border border-[var(--line)] bg-[var(--paper-raised)] py-1 pl-3 pr-1">
        <code className="min-w-0 flex-1 select-all break-words font-mono text-sm text-[var(--amber)]">
          {installCommand}
        </code>
        <button
          type="button"
          aria-label="Copy install command"
          onClick={copyCommand}
          className="landing-button landing-button-secondary landing-install-copy w-[5.5rem] shrink-0"
        >
          {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="mt-2 text-sm leading-6 text-[var(--ink-secondary)]">
        Requires Node.js 18+. After installing, run <code className="font-mono text-[var(--ink)]">simapi</code>.
      </p>
      <p role="status" className={copyStatus === "failed" ? "mt-1 text-sm text-[var(--ink-secondary)]" : "sr-only"}>
        {copied && "Install command copied."}
        {copyStatus === "failed" && "Couldn’t copy automatically. Select the command to copy it."}
      </p>
    </div>
  );
}
