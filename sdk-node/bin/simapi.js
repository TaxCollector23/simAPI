#!/usr/bin/env node
/**
 * SimAPI CLI.
 *
 * Node 18+ CLI with local ROS and URDF readers. The hosted API is
 * open by default -- no account or sign-in required. An API key is only
 * relevant if you're running your own deployment with SIMAPI_API_KEYS set.
 *   init · validate · watch · usage ·
 *   api-key {show,set,generate,delete} · config [set] · doctor · version · help
 */
import { readFile, writeFile, mkdir, stat, readdir, unlink } from "node:fs/promises";
import { watch as fsWatch, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, basename, extname } from "node:path";
import { validateProfile, parseCsvDocument, inspectRows, toCsv, repairPreview, compareReports, githubAnnotations } from "../lib/robotics-workflow.js";
import { resolveFtcProfile } from "../lib/ftc-frc.js";
import { createInterface } from "node:readline/promises";
import { stdin, stdout, platform, env } from "node:process";
import { exec } from "node:child_process";

const VERSION = "1.1.3";
const WEB_BASE = env.SIMAPI_WEB_URL || "https://simapilander.vercel.app";
const API_BASE = env.SIMAPI_BASE_URL || "https://simapilander.vercel.app/api";
const CONFIG_DIR = env.SIMAPI_CONFIG_DIR || join(homedir(), ".simapi");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");
const USAGE_PATH = join(CONFIG_DIR, "usage.json");
const LAST_RUN_PATH = join(CONFIG_DIR, "last_run.json");

// ── Colors ────────────────────────────────────────────────────────────────────
const COLOR = stdout.isTTY && !env.NO_COLOR && env.TERM !== "dumb";
const rgb = (r, g, b, s) => (COLOR ? `\x1b[38;2;${r};${g};${b}m${s}\x1b[0m` : s);
const c = {
  dim: (s) => (COLOR ? `\x1b[2m${s}\x1b[0m` : s),
  bold: (s) => (COLOR ? `\x1b[1m${s}\x1b[0m` : s),
  cyan: (s) => rgb(169, 86, 36, s),
  blue: (s) => rgb(169, 86, 36, s),
  green: (s) => rgb(56, 102, 77, s),
  red: (s) => rgb(161, 60, 50, s),
  amber: (s) => rgb(134, 83, 0, s),
  white: (s) => (COLOR ? `\x1b[97m${s}\x1b[0m` : s),
};

// ── Startup banner ──────────────────────────────────────────────────────────────
const ART = [
  "███████╗██╗███╗   ███╗ █████╗ ██████╗ ██╗",
  "██╔════╝██║████╗ ████║██╔══██╗██╔══██╗██║",
  "███████╗██║██╔████╔██║███████║██████╔╝██║",
  "╚════██║██║██║╚██╔╝██║██╔══██║██╔═══╝ ██║",
  "███████║██║██║ ╚═╝ ██║██║  ██║██║     ██║",
  "╚══════╝╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝",
];
function banner() {
  const width = stdout.columns || 80;
  const artWidth = Math.max(...ART.map((l) => [...l].length));
  const pad = width >= artWidth ? " ".repeat(Math.floor((width - artWidth) / 2)) : "";
  const line = (s) => (width >= artWidth ? pad + s : s); // never wrap; left-align when narrow

  stdout.write("\n");
  ART.forEach((row) => stdout.write(line(rgb(169, 86, 36, row)) + "\n"));
  const title = `SimAPI CLI v${VERSION}`;
  const tag = "Robotics validation for trajectories and training data.";
  const centerText = (s) => (width >= s.length ? " ".repeat(Math.floor((width - s.length) / 2)) + s : s);
  stdout.write("\n" + centerText(c.bold(c.white(title))) + "\n");
  stdout.write(centerText(c.dim(tag)) + "\n\n");
}

// ── Config / usage stores ────────────────────────────────────────────────────────
async function readJson(path, fallback = {}) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return fallback;
  }
}
async function writeJson(path, obj) {
  if (!existsSync(CONFIG_DIR)) await mkdir(CONFIG_DIR, { recursive: true });
  await writeFile(path, JSON.stringify(obj, null, 2));
}
const readConfig = () => readJson(CONFIG_PATH);
const writeConfig = (o) => writeJson(CONFIG_PATH, o);
async function resolveKey() {
  return env.SIMAPI_API_KEY || (await readConfig()).apiKey || null;
}
function mask(key) {
  if (!key) return "—";
  return key.length <= 12 ? key : `${key.slice(0, 10)}${"•".repeat(6)}${key.slice(-4)}`;
}

async function trackUsage(ms) {
  const u = await readJson(USAGE_PATH, { events: [] });
  u.events = (u.events || []).filter((e) => Date.now() - e.t < 1000 * 60 * 60 * 24 * 31);
  u.events.push({ t: Date.now(), ms });
  await writeJson(USAGE_PATH, u);
}

// ── HTTP ──────────────────────────────────────────────────────────────────────
async function api(path, { method = "GET", body, key } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(60_000),
  });
  const text = await res.text();
  let json;
  try { json = text ? JSON.parse(text) : {}; }
  catch { throw new Error(`Endpoint returned non-JSON content (HTTP ${res.status}). Check deployment access and SIMAPI_BASE_URL.`); }
  return { ok: res.ok, status: res.status, json };
}

function openBrowser(url) {
  const cmd = platform === "darwin" ? `open "${url}"` : platform === "win32" ? `start "" "${url}"` : `xdg-open "${url}"`;
  exec(cmd, () => {});
}

async function prompt(question) {
  const rl = createInterface({ input: stdin, output: stdout });
  const answer = await rl.question(question);
  rl.close();
  return answer.trim();
}

const PROFILES_DIR = join(CONFIG_DIR, "profiles");
function profilePath(name) {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name || "")) throw new Error("Profile names use 1–64 letters, digits, underscores, or hyphens.");
  return join(PROFILES_DIR, `${name}.json`);
}
async function loadProfile(name) {
  if (!name) throw new Error("Provide a profile name or JSON file.");
  const builtin = resolveFtcProfile(name);
  if (builtin) return validateProfile(builtin);
  const path = existsSync(name) ? name : profilePath(name);
  return validateProfile(JSON.parse(await readFile(path, "utf8")));
}
async function writeNew(path, content) { await writeFile(path, content, { flag: "wx" }); }

// ── Commands ────────────────────────────────────────────────────────────────────
const commands = {
  async init() {
    const file = "simapi.json";
    if (existsSync(file)) return fail(`${file} already exists.`);
    const config = {
      simulation_type: "robotics",
      conditions: {},
      robotics_limits: {},
      files: ["episode.csv"],
      fail_on: "warning",
    };
    await writeFile(file, JSON.stringify(config, null, 2));
    ok(`Created ${file} — edit it, then run ${c.cyan("simapi validate episode.csv")}.`);
  },

  async validate(args) {
    const file = args._[0];
    if (!file) return fail(`Usage: ${c.cyan("simapi validate <file>")}`);
    const key = await resolveKey();
    await runValidation(file, key, args);
  },

  async watch(args) {
    const file = args._[0];
    if (!file) return fail(`Usage: ${c.cyan("simapi watch <file>")}`);
    const key = await resolveKey();
    if (!existsSync(file)) return fail(`File not found: ${file}`);
    stdout.write(`\n  ${c.cyan("watching")} ${file} — re-validates on change. ${c.dim("Ctrl-C to stop.")}\n`);
    await runValidation(file, key, args);
    let busy = false;
    let timer = null;
    fsWatch(file, () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (busy) return;
        busy = true;
        stdout.write(`\n  ${c.dim(new Date().toLocaleTimeString())} change detected — re-validating…\n`);
        await runValidation(file, key, args);
        busy = false;
      }, 150);
    });
  },

  async usage() {
    const u = await readJson(USAGE_PATH, { events: [] });
    const events = u.events || [];
    const now = new Date();
    const startDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startMonth = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
    const today = events.filter((e) => e.t >= startDay).length;
    const month = events.filter((e) => e.t >= startMonth).length;
    const avg = events.length ? Math.round(events.reduce((a, e) => a + (e.ms || 0), 0) / events.length) : 0;
    stdout.write(`\n  ${c.bold("Local request history")}\n`);
    row("Requests today", String(today));
    row("Requests this month", String(month));
    row("Avg validation time", avg ? `${avg}ms` : "—");
    stdout.write("\n");
  },

  async "api-key"(args) {
    const sub = args._[0];
    const key = await resolveKey();
    if (sub === "show") {
      if (!key) return info("No API key configured. The hosted API doesn't require one.");
      return info(`Active key: ${c.cyan(mask(key))}`);
    }
    if (sub === "generate") {
      const { ok: good, json } = await api("/v1/keys/generate", { method: "POST", body: { label: args._[1] || "CLI" } });
      if (!good) return fail(`Key generation failed: ${json?.error || "server error"}`);
      const cfg = await readConfig();
      await writeConfig({ ...cfg, apiKey: json.api_key });
      return ok(`New key issued and saved: ${c.cyan(mask(json.api_key))}`);
    }
    if (sub === "set") {
      const value = args._[1];
      if (!value) return fail(`Usage: ${c.cyan("simapi api-key set <key>")}`);
      const cfg = await readConfig();
      await writeConfig({ ...cfg, apiKey: value });
      return ok(`API key saved: ${c.cyan(mask(value))}`);
    }
    if (sub === "delete") {
      const cfg = await readConfig();
      delete cfg.apiKey;
      await writeConfig(cfg);
      return ok("API key deleted from this machine.");
    }
    return fail(`Usage: ${c.cyan("simapi api-key <show|generate|set|delete>")}`);
  },

  async config(args) {
    if (args._[0] === "set") {
      const [, k, ...rest] = args._;
      const v = rest.join(" ");
      if (!k) return fail(`Usage: ${c.cyan("simapi config set <key> <value>")}`);
      const cfg = await readConfig();
      cfg[k] = v === "true" ? true : v === "false" ? false : /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v;
      await writeConfig(cfg);
      return ok(`Set ${c.bold(k)} = ${cfg[k]}`);
    }
    const cfg = await readConfig();
    const shown = { ...cfg };
    if (shown.apiKey) shown.apiKey = mask(shown.apiKey);
    stdout.write(`\n  ${c.bold("Configuration")} ${c.dim(`(${CONFIG_PATH})`)}\n`);
    const keys = Object.keys(shown);
    if (keys.length === 0) stdout.write(c.dim("  (empty — nothing configured yet)\n"));
    for (const k of keys) row(k, String(shown[k]));
    stdout.write("\n");
  },

  async domains() {
    const list = [
      "aerodynamics", "fluid_dynamics", "structural", "thermodynamics", "robotics",
      "combustion", "acoustics", "electromagnetics", "geomechanics", "biomechanics",
      "nuclear", "plasma", "chemical", "hydrodynamics", "meteorology", "astrophysics",
      "materials", "tribology", "aeroelasticity", "cryogenics", "multiphysics",
    ];
    stdout.write(`\n  ${c.bold("Supported simulation types")} ${c.dim(`(${list.length})`)}\n`);
    for (const d of list) stdout.write(`   ${c.cyan("•")} ${d}\n`);
    stdout.write(`\n  Use with: ${c.cyan("simapi validate run.json --type <domain>")}\n\n`);
  },

  async doctor(args) {
    const fix = !!args["fix"] || args._.includes("--fix");
    stdout.write(`\n  ${c.bold("SimAPI doctor")}\n`);
    stdout.write("  " + "─".repeat(46) + "\n");
    let problems = 0;

    if (existsSync(CONFIG_DIR)) {
      ok(`Config directory writable (${CONFIG_DIR})`);
    } else if (fix) {
      await mkdir(CONFIG_DIR, { recursive: true });
      ok(`Created config directory (${CONFIG_DIR})`);
    } else {
      stdout.write(`  ${c.red("✗")} Config directory missing (${CONFIG_DIR})\n    ${c.dim("fix: simapi doctor --fix")}\n`);
      problems++;
    }

    const nodeMajor = Number(process.versions.node.split(".")[0]);
    if (nodeMajor >= 18) ok(`Node ${process.version} (>= 18 required)`);
    else {
      stdout.write(`  ${c.red("✗")} Node ${process.version} is below the minimum supported version (18)\n`);
      problems++;
    }

    const key = await resolveKey();
    if (key) ok(`API key configured (${mask(key)})`);
    else stdout.write(`  ${c.dim("·")} No API key configured — not required for the hosted API. ${c.dim("(simapi api-key generate)")}\n`);

    try {
      const t = Date.now();
      const res = await api("/v1/health");
      if (res.ok) ok(`API reachable at ${API_BASE} (${Date.now() - t}ms, engine=${res.json.engine || "unknown"})`);
      else {
        stdout.write(`  ${c.red("✗")} API returned HTTP ${res.status} at ${API_BASE}\n`);
        problems++;
      }
    } catch (e) {
      stdout.write(`  ${c.red("✗")} API unreachable at ${API_BASE}: ${e.message}\n`);
      problems++;
    }

    if (existsSync("simapi.json")) {
      try {
        JSON.parse(await readFile("simapi.json", "utf8"));
        ok("simapi.json found and valid");
      } catch (e) {
        stdout.write(`  ${c.red("✗")} simapi.json exists but is not valid JSON: ${e.message}\n`);
        problems++;
      }
    } else {
      stdout.write(`  ${c.dim("·")} No simapi.json in this directory ${c.dim("(optional — run simapi init)")}\n`);
    }

    stdout.write("  " + "─".repeat(46) + "\n");
    if (problems === 0) stdout.write(`  ${c.green("All checks passed.")}\n\n`);
    else stdout.write(`  ${c.amber(`${problems} issue(s) found`)}${fix ? "" : ` — run ${c.cyan("simapi doctor --fix")} to auto-fix what's fixable`}\n\n`);
  },

  async repair(args) {
    const file = args._[0];
    if (!file) return fail("Usage: simapi repair <file> [--apply] [--output <new-file>]");
    const payload = await loadPayload(file, await resolveKey(), args);
    const data = Array.isArray(payload) ? payload : payload.data || payload.trials || [];
    const plan = repairPreview(data);
    if (args.json) stdout.write(JSON.stringify(plan, null, 2) + "\n");
    else {
      stdout.write(`\n  Repair preview: ${plan.original_samples} → ${plan.repaired_samples} samples\n`);
      for (const proposal of plan.proposals) {
        stdout.write(`  ${proposal.kind}: ${proposal.description} (${proposal.affected_row_count} samples)\n`);
        for (const ch of proposal.changes.slice(0, 8)) stdout.write(`    sample ${ch.row + 1}, ${ch.column}: ${ch.before} → ${ch.after}\n`);
      }
      for (const item of plan.unrepairable) stdout.write(`  Review: ${item.reason}\n`);
      if (!plan.proposals.length) info("No automatic changes proposed.");
    }
    if (args.apply && plan.proposals.length) {
      const csv = extname(file).toLowerCase() === ".csv";
      const output = args.output || file.slice(0, file.length - extname(file).length) + (csv ? ".repaired.csv" : ".repaired.json");
      await writeNew(output, csv ? toCsv(plan.repaired_data) : JSON.stringify(plan.repaired_data, null, 2) + "\n");
      if (!args.json) ok(`Wrote ${output}. Review and revalidate before use.`);
    }
  },

  async inspect(args) {
    const file = args._[0]; if (!file) return fail("Usage: simapi inspect <file> [--topic <name>] [--json]");
    if (args.profile) args.profileData = await loadProfile(args.profile);
    const payload = await loadPayload(file, await resolveKey(), args);
    const report = inspectRows(Array.isArray(payload) ? payload : payload.data || payload.trials || []);
    if (args.json) return stdout.write(JSON.stringify(report, null, 2) + "\n");
    stdout.write(`\n  ${file}: ${report.samples} samples, ${report.episodes.length} episodes\n`);
    for (const episode of report.episodes) stdout.write(`  ${episode.episode_id}: ${episode.samples} samples, ${episode.duration_seconds === null ? "duration unavailable" : episode.duration_seconds + "s"}\n`);
    for (const signal of report.signals) stdout.write(`  ${signal.name}: ${signal.min ?? "unavailable"} to ${signal.max ?? "unavailable"}; ${signal.missing_or_nonnumeric} missing/non-numeric\n`);
  },

  async import(args) {
    const file = args._[0]; if (!file) return fail("Usage: simapi import <recording.bag|recording.mcap|data.csv> --output <run.json> [--topic <name>]");
    let rows, recording;
    if (/\.(mcap|bag)$/i.test(file)) {
      const { readRecording } = await import("../lib/robotics-import.js");
      recording = await readRecording(new Uint8Array(await readFile(file)), file, { topic: args.topic, episode: args.episode, profile: args.profile ? await loadProfile(args.profile) : undefined });
      if (args["list-topics"] || recording.requires_topic) {
        if (args.json) stdout.write(JSON.stringify(recording.topics, null, 2) + "\n");
        else for (const t of recording.topics) stdout.write(`${t.topic}  ${t.schema}  ${t.samples} samples\n`);
        if (recording.requires_topic && !args["list-topics"]) return fail("Multiple topics found. Select one with --topic.");
        return;
      }
      rows = recording.rows;
    } else {
      const payload = await loadPayload(file, await resolveKey(), args); rows = Array.isArray(payload) ? payload : payload.data || payload.trials;
    }
    if (!Array.isArray(rows) || !rows.length) return fail("No samples found.");
    if (!args.output) return fail("--output is required; the source recording is never modified.");
    await writeNew(args.output, args.output.endsWith(".csv") ? toCsv(rows) : JSON.stringify(rows, null, 2) + "\n");
    if (!args.json) ok(`Imported ${rows.length} samples${recording?.topic ? ` from ${recording.topic}` : ""} into ${args.output}`);
  },

  async profile(args) {
    const [sub, value] = args._;
    await mkdir(PROFILES_DIR, { recursive: true });
    if (sub === "list") {
      const names = ["ftc", "frc", ...(await readdir(PROFILES_DIR)).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5))];
      stdout.write(args.json ? JSON.stringify(names) + "\n" : names.map((name) => ["ftc", "frc"].includes(name) ? `${name} (built-in FTC/FRC profile)` : name).join("\n") + "\n"); return;
    }
    if (sub === "show") { stdout.write(JSON.stringify(await loadProfile(value), null, 2) + "\n"); return; }
    if (sub === "delete") { if (resolveFtcProfile(value)) return fail("Built-in FTC/FRC profiles cannot be deleted."); await unlink(profilePath(value)); ok(`Deleted profile ${value}`); return; }
    if (sub === "import") {
      if (!value) return fail("Usage: simapi profile import <arm.urdf|profile.json> --name <name> [--output <profile.json>]");
      const text = await readFile(value, "utf8");
      const profile = /\.urdf$/i.test(value) ? (await import("../lib/robotics-import.js")).profileFromUrdf(text, args.name) : validateProfile(JSON.parse(text));
      const name = args.name || basename(value, extname(value));
      if (resolveFtcProfile(name)) return fail("The names ftc and frc are reserved for built-in FTC/FRC profiles.");
      const content = JSON.stringify({ ...profile, name }, null, 2) + "\n";
      // Validate all output paths before writing the named profile.
      const path = profilePath(name);
      if (existsSync(path) || (args.output && existsSync(args.output))) return fail("Output/profile already exists. Choose a new name or remove the old profile first.");
      if (args.output) await writeNew(args.output, content);
      await writeNew(path, content);
      ok(`Saved profile ${name}. Use --profile ${name}`);
      for (const warning of profile.warnings || []) info(warning);
      return;
    }
    return fail("Usage: simapi profile <import|list|show|delete>");
  },

  async compare(args) {
    if (args._.length !== 2) return fail("Usage: simapi compare <baseline.json> <current.json> [--json] [--fail-on regression]");
    const diff = compareReports(JSON.parse(await readFile(args._[0], "utf8")), JSON.parse(await readFile(args._[1], "utf8")));
    if (args.json) stdout.write(JSON.stringify(diff, null, 2) + "\n");
    else {
      stdout.write(`\n  ${diff.status_before} → ${diff.status_after} | excluded samples ${diff.exclusion_delta >= 0 ? "+" : ""}${diff.exclusion_delta}\n`);
      stdout.write(`  Configuration: ${diff.same_configuration === null ? "unknown in older report" : diff.same_configuration ? "same" : "changed; compare settings before judging regressions"}\n`);
      for (const [label, entries] of [["New/worse", diff.introduced], ["Resolved/improved", diff.resolved], ["Persisting", diff.persisting]]) for (const item of entries) stdout.write(`  ${label}: ${item.name} (${item.before} → ${item.after})\n`);
      for (const item of diff.episode_changes) stdout.write(`  Episode ${item.episode_id}: ${item.before?.flagged_samples ?? "absent"} → ${item.after?.flagged_samples ?? "absent"} flagged samples\n`);
    }
    if (args["fail-on"] === "regression" && diff.regressed) process.exitCode = 1;
  },

  async explain() {
    const cached = await readJson(LAST_RUN_PATH, null);
    if (!cached) return fail(`No cached validation run. Run ${c.cyan("simapi validate <file>")} first.`);
    const r = cached.result;
    const ageS = Math.round((Date.now() - cached.t) / 1000);
    stdout.write(`\n  ${c.bold("Explaining")} ${c.dim(cached.file)} ${c.dim(`(validated ${ageS}s ago)`)}\n`);
    stdout.write("  " + "─".repeat(46) + "\n");
    const issues = r.issues || [];
    if (!issues.length) {
      stdout.write(`  ${c.green("No issues were found in this run.")}\n\n`);
      return;
    }
    issues.forEach((issue, idx) => {
      const mk = issue.status === "failed" ? c.red("✗") : c.amber("⚠");
      const name = issue.human_name || issue.name || "unnamed check";
      stdout.write(`\n  ${mk} ${c.bold(`${idx + 1}. ${name}`)}\n`);
      if (issue.category) row("Category", issue.category);
      if (issue.detail) row("Detail", issue.detail);
      if (issue.value !== undefined && issue.value !== null) row("Value", String(issue.value));
    });
    const exclusions = r.exclusions || [];
    if (exclusions.length) {
      stdout.write(`\n  ${c.bold(`Excluded trials (${exclusions.length})`)}\n`);
      for (const e of exclusions.slice(0, 10)) row(`Trial ${e.trial_number ?? e.trial_index}`, e.reason || "");
      if (exclusions.length > 10) stdout.write(`  ${c.dim(`… and ${exclusions.length - 10} more`)}\n`);
    }
    stdout.write("\n");
  },

  async open() {
    const url = `${WEB_BASE}/dashboard`;
    ok(`Opening ${c.cyan(url)}`);
    openBrowser(url);
  },

  version() {
    banner();
    stdout.write(`  ${c.bold(`v${VERSION}`)}  ${c.dim(`node ${process.version}`)}\n\n`);
  },

  help() {
    printHelp();
  },
};

async function loadPayload(file, key, args) {
  if (/\.(mcap|bag)$/i.test(file)) {
    const { readRecording } = await import("../lib/robotics-import.js");
    const recording = await readRecording(new Uint8Array(await readFile(file)), file, { topic: args.topic, episode: args.episode, profile: args.profileData });
    if (recording.requires_topic) throw new Error(`Choose --topic: ${recording.topics.map((t) => t.topic).join(", ")}`);
    return { data: recording.rows, simulation_type: "robotics" };
  }
  const raw = await readFile(file, "utf8");
  if (file.toLowerCase().endsWith(".csv")) { const parsed = parseCsvDocument(raw); return { data: parsed.rows, source_lines: parsed.sourceLines, simulation_type: args.type || "robotics" }; }
  try {
    return JSON.parse(raw);
  } catch {
    // Not JSON (e.g. simulations.txt / a log dump) → convert with AI.
    stdout.write(`  ${c.dim(`Parsing ${file} with AI…`)}\n`);
    const pr = await api("/v1/parse", { method: "POST", body: { text: raw, simulation_type: args.type }, key });
    if (!pr.ok) {
      if (pr.json && pr.json.enabled === false)
        throw new Error("AI text parsing isn't enabled yet (server needs OPENROUTER_API_KEY). Use a .json file for now.");
      throw new Error(`Could not parse ${file}: ${(pr.json && pr.json.error) || pr.status}`);
    }
    return pr.json; // { simulation_type, conditions, data }
  }
}


async function runValidation(file, key, args) {
  if (!existsSync(file)) return fail(`File not found: ${file}`);
  const cfg = await readConfig();
  const projectCfg = await readJson("simapi.json");
  args.profile ??= projectCfg.profile || cfg.profile;
  args["fail-on"] ??= projectCfg.fail_on || cfg.fail_on;
  let profileLimits = {};
  let profileConditions = {};
  let profileFtcLimits = {};
  let profileUnits = {};
  let profileKind = "robotics";
  if (args.profile === "") return fail("--profile requires a JSON profile path.");
  if (args.profile) {
    let profile;
    try { profile = await loadProfile(args.profile); }
    catch (e) { return fail(e.message); }
    profileLimits = profile.robotics_limits;
    profileConditions = profile.conditions;
    profileFtcLimits = profile.ftc_limits || {};
    profileUnits = profile.units || {};
    profileKind = profile.robotics_profile || "robotics";
    args.profileData = profile;
  }
  let payload;
  try {
    payload = await loadPayload(file, key, args);
  } catch (e) {
    return fail(e.message);
  }
  const body = Array.isArray(payload)
    ? {
        data: payload,
        simulation_type: args.type || projectCfg.simulation_type || cfg.simulation_type || "robotics",
        conditions: projectCfg.conditions || {},
        ...(projectCfg.robotics_limits ? { robotics_limits: projectCfg.robotics_limits } : {}),
      }
    : {
        simulation_type: args.type || payload.simulation_type || projectCfg.simulation_type || cfg.simulation_type || "robotics",
        conditions: payload.conditions || projectCfg.conditions || {},
        ...(payload.robotics_limits || projectCfg.robotics_limits
          ? { robotics_limits: payload.robotics_limits || projectCfg.robotics_limits }
          : {}),
        data: payload.data || payload.trials || [],
        ...(payload.robotics_profile ? { robotics_profile: payload.robotics_profile } : {}),
        ...(payload.ftc_limits ? { ftc_limits: payload.ftc_limits } : {}),
        ...(payload.units ? { units: payload.units } : {}),
      };
  if (args.profile) {
    if (body.simulation_type !== "robotics") return fail("--profile can only be used with --type robotics.");
    body.robotics_limits = { ...(body.robotics_limits || {}), ...profileLimits };
    body.conditions = { ...body.conditions, ...profileConditions };
    if (Object.keys(profileUnits).length) body.units = { ...(body.units || {}), ...profileUnits };
    if (profileKind === "ftc") {
      body.robotics_profile = "ftc";
      body.ftc_limits = { ...(body.ftc_limits || {}), ...profileFtcLimits };
    }
  }
  if (args.report === "") return fail("--report requires an output path.");
  body.run_ai = !args["no-ai"];
  if (args["fail-on"] && !["warning", "failed"].includes(args["fail-on"])) return fail("--fail-on must be warning or failed.");
  if (args.format && args.format !== "github") return fail("--format must be github.");

  const t0 = Date.now();
  let res;
  try {
    res = await api("/v1/validate", { method: "POST", body, key });
  } catch (e) {
    return fail(`Request failed: ${e.message} ${c.dim(`(is ${API_BASE} reachable?)`)}`);
  }
  await trackUsage(Date.now() - t0);

  if (!res.ok) {
    const err = res.json?.error || {};
    return fail(`[${err.code || res.status}] ${err.message || "validation error"}`);
  }
  const r = { ...res.json, validation_context: { simulation_type: body.simulation_type, robotics_limits: body.robotics_limits || {}, conditions: body.conditions || {}, ...(body.robotics_profile ? { robotics_profile: body.robotics_profile } : {}), ...(body.ftc_limits ? { ftc_limits: body.ftc_limits } : {}), ...(body.units ? { units: body.units } : {}) } };
  if (args.format === "github") for (const line of githubAnnotations(r, file, payload.source_lines)) process.stderr.write(line + "\n");
  await writeJson(LAST_RUN_PATH, { file, t: Date.now(), result: r });
  if (args.report) await writeFile(args.report, JSON.stringify(r, null, 2) + "\n");
  if (args.json) stdout.write(JSON.stringify(r, null, 2) + "\n");
  else if (args.summary || args.format === "github" || env.CI) {
    stdout.write(`${r.status.toUpperCase()}  ${file}  ${r.trials_submitted ?? "?"} samples, ${r.trials_excluded ?? "?"} excluded, ${r.failed ?? "?"} failed checks, ${r.warnings ?? "?"} warnings\n`);
    for (const issue of (r.issues || []).slice(0, 3)) stdout.write(`  ${issue.human_name || issue.name}: ${issue.detail || ""}\n`);
  } else renderReport(r, file, body.simulation_type);

  if (args["fail-on"] === "warning" && r.status !== "passed") process.exitCode = 1;
  if (args["fail-on"] === "failed" && r.status === "failed") process.exitCode = 1;
}

function renderReport(r, file, simType) {
  const status = (r.status || "").toUpperCase();
  const tone = r.status === "passed" ? c.green : r.status === "warning" ? c.amber : c.red;
  const mark = r.status === "passed" ? "✓" : r.status === "warning" ? "⚠" : "✗";
  const failures = (r.issues || []).filter((i) => i.status === "failed").length;
  const warns = (r.issues || []).filter((i) => i.status === "warning").length;

  // Status banner
  const title = ` ${mark}  ${status}`;
  const right = file;
  const width = Math.max(48, title.length + right.length + 6);
  stdout.write("\n  " + c.dim("╭" + "─".repeat(width) + "╮") + "\n");
  const pad = width - title.length - right.length - 2;
  stdout.write("  " + c.dim("│") + tone(c.bold(title)) + " ".repeat(Math.max(1, pad)) + c.dim(right) + " " + c.dim("│") + "\n");
  stdout.write("  " + c.dim("╰" + "─".repeat(width) + "╯") + "\n\n");

  // Summary
  const excl = r.trials_excluded ?? 0;
  row("Simulation", simType);
  if (r.robotics_summary) {
    row("Motion engine", r.robotics_summary.engine_version);
    row("Episodes", String(r.robotics_summary.episodes.length));
  }
  row("Trials", `${c.bold(String(r.trials_valid ?? "—"))} valid / ${r.trials_submitted ?? "—"}` + (excl ? c.dim(`   (${excl} excluded)`) : ""));
  row("Rules", `${r.unique_checks ?? r.all_checks ?? "—"} unique` + c.dim(`   ·  ${(r.all_checks ?? 0).toLocaleString()} evaluations`));
  row("Findings", `${failures ? c.red(failures + " failed") : "0 failed"}   ${warns ? c.amber(warns + " warnings") : "0 warnings"}`);
  row("Training ready", r.training_ready ? c.green("yes") : c.red("no"));
  row("Time", `${r.processing_ms ?? "—"}ms`);

  const issues = r.issues || [];
  if (issues.length) {
    stdout.write(`\n  ${c.bold(`Issues (${issues.length})`)}\n`);
    for (const i of issues.slice(0, 12)) {
      const mk = i.status === "failed" ? c.red("✗") : c.amber("⚠");
      stdout.write(`   ${mk} ${i.human_name || i.name}\n`);
      if (i.detail && i.detail !== i.human_name) stdout.write(`     ${c.dim(i.detail)}\n`);
    }
    if (issues.length > 12) stdout.write(`   ${c.dim(`… and ${issues.length - 12} more`)}\n`);
  }

  const ex = r.exclusions || [];
  if (ex.length) {
    stdout.write(`\n  ${c.bold(`Excluded trials (${excl})`)}\n`);
    for (const e of ex.slice(0, 6)) stdout.write(`   ${c.dim("#" + (e.trial_index + 1))}  ${e.reason}\n`);
    if (ex.length > 6) stdout.write(`   ${c.dim(`… and ${ex.length - 6} more`)}\n`);
  }

  const recs = r.ai?.recommendations || r.recommendations || [];
  if (recs.length) {
    stdout.write(`\n  ${c.bold("Recommendations")}\n`);
    for (const rec of recs.slice(0, 6)) stdout.write(`   ${c.cyan("→")} ${rec}\n`);
  }
  if (r.ai && r.ai.dataset_summary) {
    stdout.write(`\n  ${c.bold("AI review")}  ${c.dim(r.ai.model ? r.ai.model.split("/").pop() : "")}\n   ${c.dim(r.ai.dataset_summary)}\n`);
  }
  stdout.write("\n");
}

// ── Help ──────────────────────────────────────────────────────────────────────
const HELP = {
  inspect: { usage: "simapi inspect <file>", desc: "Inspect samples, episodes, timing, signal ranges and missing values locally.", opts: [["--json", "machine-readable inspection"], ["--topic <name>", "choose a recording topic"]] },
  import: { usage: "simapi import <file> --output <run.json>", desc: "Extract JointState samples from ROS 1 bags, ROS 1/2 MCAP, CSV, or JSON. Select --topic when several channels exist.", opts: [["--topic <topic>", "select a JointState channel"], ["--list-topics", "inspect recording channels"], ["--profile <name|file>", "load joint metadata, including prismatic effort units"], ["--episode <id>", "assign an episode identifier"]] },
  profile: { usage: "simapi profile <import|list|show|delete>", desc: "Import URDF limits or JSON profiles, or use the built-in ftc/frc school robotics profile.", ex: ["simapi profile import arm.urdf --name arm --output arm-profile.json", "simapi profile list", "simapi profile show arm", "simapi validate drive-log.csv --profile ftc"] },
  compare: { usage: "simapi compare baseline.json current.json", desc: "Compare checks, episode findings, exclusions, and configuration.", opts: [["--json", "JSON comparison"], ["--fail-on regression", "fail CI on new or worsened findings"]] },
  init: { usage: "simapi init", desc: "Create a simapi.json config in the current project." },
  validate: { usage: "simapi validate <file>", desc: "Validate a .json, .csv, or .txt simulation file and print the report. Plain-text/log files are converted to JSON with AI.", opts: [["--summary", "compact report (automatic in CI)"], ["--format github", "emit GitHub Actions annotations"], ["--topic <name>", "select a recording channel"], ["--type <domain>", "simulation domain (defaults to robotics)"], ["--profile <file>", "robotics limits and trajectory check options"], ["--report <file>", "save the full JSON report"], ["--json", "raw JSON output"], ["--no-ai", "skip the AI second pass"], ["--fail-on <level>", "exit non-zero on warning|failed"]], ex: ["simapi validate episode.csv --profile arm-profile.json --fail-on warning", "simapi validate drive-log.csv --profile ftc", "simapi validate simulation.json", "simapi validate simulations.txt --type aerodynamics"] },
  domains: { usage: "simapi domains", desc: "List the supported simulation types." },
  doctor: { usage: "simapi doctor [--fix]", desc: "Diagnose config, connectivity, and project setup." },
  explain: { usage: "simapi explain", desc: "Explain the issues from the most recent validation run in detail." },
  repair: { usage: "simapi repair <file> [--apply]", desc: "Preview or apply automatic structural repairs to a data file.", ex: ["simapi repair simulation.json", "simapi repair simulation.json --apply"] },
  open: { usage: "simapi open", desc: "Open the SimAPI dashboard in your browser." },
  watch: { usage: "simapi watch <file>", desc: "Re-run validation automatically whenever the file changes.", ex: ["simapi watch simulation.json"] },
  usage: { usage: "simapi usage", desc: "Show requests today/this month, remaining quota, and average time." },
  "api-key": { usage: "simapi api-key <show|generate|set|delete>", desc: "The hosted API needs no key. Only relevant for your own deployment.", ex: ["simapi api-key generate", "simapi api-key set <key>", "simapi api-key show"] },
  config: { usage: "simapi config [set <key> <value>]", desc: "Show or update CLI configuration.", ex: ["simapi config", "simapi config set fail_on warning"] },
  version: { usage: "simapi version", desc: "Print the installed CLI version." },
  help: { usage: "simapi help", desc: "Show all commands." },
};

function printHelp() {
  banner();
  stdout.write(`  ${c.bold("Usage")}\n    simapi ${c.dim("<command> [options]")}\n\n`);
  stdout.write(`  ${c.bold("Commands")}\n`);
  const items = [
    ["init", "Create a robotics simapi.json config"],
    ["inspect <file>", "Inspect episode timing, ranges and missing signals"],
    ["import <recording> --output <file>", "Extract JointState data from ROS bags or MCAP"],
    ["profile <import|list|show|delete>", "Reusable JSON, URDF, and built-in ftc/frc profiles"],
    ["compare <baseline> <current>", "Compare checks and episode findings"],
    ["validate <file>", "Validate JSON or CSV simulation data"],
    ["watch <file>", "Re-validate on file change"],
    ["domains", "List supported simulation types"],
    ["usage", "Show API usage statistics"],
    ["api-key <cmd>", "show · generate · set · delete (optional -- no account needed)"],
    ["config [set]", "Show or update configuration"],
    ["doctor [--fix]", "Diagnose config and connectivity"],
    ["explain", "Explain the last validation run in detail"],
    ["repair <file> [--apply]", "Preview or apply automatic repairs"],
    ["open", "Open the dashboard in your browser"],
    ["version", "Show the CLI version"],
    ["help", "Show this help"],
  ];
  for (const [name, desc] of items) stdout.write(`    ${c.cyan(name)}\n      ${c.dim(desc)}\n`);
  stdout.write(`\n  ${c.dim("Run")} ${c.cyan("simapi <command> --help")} ${c.dim("for details on a command.")}\n\n`);
}

function printCommandHelp(name) {
  const h = HELP[name];
  if (!h) return printHelp();
  stdout.write(`\n  ${c.bold(name)} — ${h.desc}\n\n`);
  stdout.write(`  ${c.bold("Usage")}\n    ${c.cyan(h.usage)}\n`);
  if (h.opts) {
    stdout.write(`\n  ${c.bold("Options")}\n`);
    for (const [o, d] of h.opts) stdout.write(`    ${c.cyan(o.padEnd(20))} ${c.dim(d)}\n`);
  }
  if (h.ex) {
    stdout.write(`\n  ${c.bold("Examples")}\n`);
    for (const e of h.ex) stdout.write(`    ${c.dim("$")} ${e}\n`);
  }
  stdout.write("\n");
}

// ── Output helpers ──────────────────────────────────────────────────────────────
function row(label, value) {
  stdout.write(`  ${label.padEnd(22)} ${value}\n`);
}
function ok(msg) {
  stdout.write(`  ${c.green("✓")} ${msg}\n`);
}
function info(msg) {
  stdout.write(`  ${msg}\n`);
}
function fail(msg) {
  stdout.write(`  ${c.red("✗")} ${msg}\n`);
  process.exitCode = 1;
}

// ── Arg parsing ─────────────────────────────────────────────────────────────────
function parse(argv) {
  const out = { _: [], type: undefined, profile: undefined, json: false, "fail-on": undefined, help: false, fix: false, apply: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--help" || a === "-h") out.help = true;
    else if (a === "--json") out.json = true;
    else if (a === "--no-ai") out["no-ai"] = true;
    else if (["--report", "--output", "--topic", "--episode", "--name", "--format", "--type", "--profile", "--fail-on"].includes(a)) { const value = argv[++i]; if (!value || value.startsWith("--")) throw new Error(`${a} requires a value.`); out[a.slice(2)] = value; }
    else if (a === "--summary") out.summary = true;
    else if (a === "--list-topics") out["list-topics"] = true;
    else if (a === "--fix") out.fix = true;
    else if (a === "--apply") out.apply = true;
    else if (a.startsWith("--")) throw new Error(`Unknown option: ${a}`);
    else out._.push(a);
  }
  return out;
}

async function main() {
  const [, , cmd, ...rest] = process.argv;
  const args = parse(rest);

  if (!cmd || cmd === "--help" || cmd === "-h") return printHelp();
  if (cmd === "--version" || cmd === "-v") return commands.version();
  const name = cmd === "apikey" ? "api-key" : cmd;
  if (!(name in commands)) {
    fail(`Unknown command: ${cmd}`);
    return printHelp();
  }
  if (args.help) return printCommandHelp(name);
  await commands[name](args);
}

main().catch((e) => fail(e.message));
