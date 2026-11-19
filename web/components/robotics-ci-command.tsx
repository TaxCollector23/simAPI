"use client";

import { useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import {
  ciProfileFile,
  ciReportFile,
  ciRunFile,
  ciValidationCommand,
  type CiFailThreshold,
} from "@/lib/robotics-report-navigation";
import type { Profile, Row } from "@/lib/robotics-workflow.js";

function downloadJson(filename: string, value: unknown) {
  const href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], {
    type: "application/json",
  }));
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export function RoboticsCiCommand({ rows, profile }: { rows: Row[]; profile: Profile }) {
  const [threshold, setThreshold] = useState<CiFailThreshold>("failed");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "unavailable">("idle");
  const command = ciValidationCommand(threshold);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("unavailable");
    }
  }

  return (
    <section aria-labelledby="robotics-ci-heading" className="mt-6 border-t border-white/10 pt-5">
      <h3 id="robotics-ci-heading" className="text-base font-medium">Run these checks in CI</h3>
      <p className="mt-2 text-sm leading-6">
        Save the run and profile at your repository root. The command uses
        these checks and writes <code>{ciReportFile}</code>.
      </p>
      <label className="mt-4 flex flex-wrap items-center gap-3 text-sm">
        Fail CI on
        <select
          value={threshold}
          onChange={(event) => {
            setThreshold(event.target.value as CiFailThreshold);
            setCopyStatus("idle");
          }}
        >
          <option value="failed">Errors only</option>
          <option value="warning">Warnings and errors</option>
        </select>
      </label>
      <pre className="mt-4 overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-white/10 bg-ink-950 p-3 font-mono text-sm leading-6">
        <code>{command}</code>
      </pre>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" onClick={copy} className="landing-button landing-button-secondary">
          {copyStatus === "copied" ? <Check size={16} /> : <Copy size={16} />}
          Copy CI command
        </button>
        <button type="button" onClick={() => downloadJson(ciProfileFile, profile)} className="landing-button landing-button-secondary">
          <Download size={16} /> Download profile
        </button>
        <button type="button" onClick={() => downloadJson(ciRunFile, rows)} className="px-2 py-3 text-sm font-medium text-accent-cyan hover:underline">
          Download run JSON
        </button>
      </div>
      <p role="status" className="mt-2 text-sm">
        {copyStatus === "copied" && "CI command copied."}
        {copyStatus === "unavailable" && "Clipboard access was unavailable. Select and copy the command above."}
      </p>
    </section>
  );
}
