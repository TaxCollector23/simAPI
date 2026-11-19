#!/usr/bin/env node
import { access, mkdir, readFile, readdir, realpath, rename, unlink, writeFile } from "node:fs/promises";
import { constants, existsSync, readFileSync, watch as fsWatch } from "node:fs";
import { randomUUID } from "node:crypto";
import { homedir } from "node:os";
import { basename, extname, join, resolve } from "node:path";
import { execFile } from "node:child_process";
import { env, platform, stderr, stdin, stdout } from "node:process";
import { validateProfile, parseCsvDocument, inspectRows, toCsv, repairPreview, compareReports, githubAnnotations } from "../lib/robotics-workflow.js";
import { resolveFtcProfile } from "../lib/ftc-frc.js";

const { version: VERSION } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const WEB_BASE = env.SIMAPI_WEB_URL || "https://simapilander.vercel.app";
const API_BASE = (env.SIMAPI_BASE_URL || "https://simapilander.vercel.app/api").replace(/\/+$/, "");
const CONFIG_DIR = env.SIMAPI_CONFIG_DIR || join(homedir(), ".simapi");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");
const USAGE_PATH = join(CONFIG_DIR, "usage.json");
const LAST_RUN_PATH = join(CONFIG_DIR, "last_run.json");

function paint(stream) {
  const color = stream.isTTY && !("NO_COLOR" in env) && env.TERM !== "dumb";
  const style = (code) => (value) => color ? `\x1b[${code}m${value}\x1b[0m` : value;
  return {
    dim: style("2"),
    bold: style("1"),
    accent: style("38;2;169;86;36"), // Landing page amber (#a95624).
    green: style("38;2;56;102;77"),
    red: style("38;2;161;60;50"),
    amber: style("38;2;134;83;0"),
  };
}

const c = paint(stdout);
const diagnostic = paint(stderr);

async function readJson(path, fallback = {}) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return fallback;
  }
}

async function readSettings(path) {
  try {
    const value = JSON.parse(await readFile(path, "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a JSON object.");
    return value;
  } catch (error) {
    if (error.code === "ENOENT") return {};
    throw new Error(`Could not read settings from ${path}. Check that it is a readable JSON object.`);
  }
}

async function writeJsonAtomic(path, value) {
  const temp = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temp, JSON.stringify(value, null, 2) + "\n", { flag: "wx", mode: 0o600 });
    await rename(temp, path);
  } catch (error) {
    await unlink(temp).catch(() => {});
    throw error;
  }
}

async function writeJson(path, value) {
  await mkdir(CONFIG_DIR, { recursive: true, mode: 0o700 });
  await writeJsonAtomic(path, value);
}

const readConfig = () => readSettings(CONFIG_PATH);
const writeConfig = (value) => writeJson(CONFIG_PATH, value);
async function resolveKey() {
  return env.SIMAPI_API_KEY || (await readConfig()).apiKey || null;
}
function mask(key) {
  if (!key) return "—";
  const value = String(key);
  return value.length <= 8 ? "••••" : `••••${value.slice(-4)}`;
}

async function trackUsage(ms) {
  const u = await readJson(USAGE_PATH, { events: [] });
  u.events = (u.events || []).filter((e) => Date.now() - e.t < 1000 * 60 * 60 * 24 * 31);
  u.events.push({ t: Date.now(), ms });
  await writeJson(USAGE_PATH, u);
}

// ── HTTP ──────────────────────────────────────────────────────────────────────
async function api(path, { method = "GET", body, key, timeout = 65_000 } = {}) {
  let response, text;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      // Do not forward custom authentication headers to another endpoint.
      redirect: key ? "error" : "follow",
      signal: AbortSignal.timeout(timeout),
    });
    if (response.status === 429) {
      const retryAfter = response.headers.get("retry-after");
      const retryHint = retryAfter && /^\d+$/.test(retryAfter) ? ` Try again in ${retryAfter} seconds.` : " Try again later.";
      throw new Error(`The validation API is rate limited (HTTP 429).${retryHint}`);
    }
    text = await response.text();
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") {
      throw new Error(`The request timed out after ${timeout / 1000} seconds. Try again or run simapi doctor.`);
    }
    if (error instanceof TypeError) {
      throw new Error("Could not reach the validation API. Check your connection or SIMAPI_BASE_URL, then run simapi doctor.");
    }
    throw error;
  }
  let json;
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`The validation API returned a non-JSON response (HTTP ${response.status}). Check SIMAPI_BASE_URL or try again.`);
  }
  return { ok: response.ok, status: response.status, json };
}

function errorMessage(response) {
  const error = response.json?.error ?? response.json?.detail;
  const message = typeof error === "string" ? error : error?.message ?? error?.error;
  return `${message || "The validation API rejected the request."} (HTTP ${response.status})`;
}

function openBrowser(url) {
  const app = platform === "darwin" ? "open" : platform === "win32" ? "rundll32.exe" : "xdg-open";
  const args = platform === "win32" ? ["url.dll,FileProtocolHandler", url] : [url];
  return new Promise((resolve, reject) => {
    execFile(app, args, (error) => {
      if (error) reject(new Error(`Could not open your browser. Visit ${url}.`));
      else resolve();
    });
  });
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
    const config = {
      simulation_type: "robotics",
      conditions: {},
      robotics_limits: {},
      fail_on: "warning",
    };
    await writeNew(file, JSON.stringify(config, null, 2) + "\n");
    ok(`Created ${file}. Set your limits, then run ${c.accent("simapi validate episode.csv")} with your recording.`);
  },

  async validate(args) {
    const file = args._[0];
    if (args._.length !== 1) return fail("Usage: simapi validate <file>");
    const key = await resolveKey();
    await runValidation(file, key, args);
  },

  async watch(args) {
    const file = args._[0];
    if (args._.length !== 1) return fail("Usage: simapi watch <file>");
    const key = await resolveKey();
    if (!existsSync(file)) return fail(`File not found: ${file}`);
    stderr.write(`Watching ${file}. Press Ctrl-C to stop.\n`);
    await runValidation(file, key, args);
    let busy = false;
    let timer = null;
    fsWatch(file, () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (busy) return;
        busy = true;
        stderr.write(`Change detected in ${file}. Validating again.\n`);
        try {
          await runValidation(file, key, args);
        } catch (error) {
          fail(error.message);
        } finally {
          busy = false;
        }
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
    if (args.stdin && sub !== "set") return fail("--stdin is only available with simapi api-key set.");
    if (sub === "show") {
      if (args._.length !== 1) return fail("Usage: simapi api-key show");
      const key = await resolveKey();
      if (!key) return info("No API key configured. The hosted API doesn't require one.");
      return info(`Active key: ${c.accent(mask(key))}`);
    }
    if (sub === "generate") {
      const { ok: good, json } = await api("/v1/keys/generate", { method: "POST", body: { label: args._[1] || "CLI" } });
      if (!good || typeof json?.api_key !== "string" || !json.api_key) return fail("The API did not issue a key.");
      const cfg = await readConfig();
      await writeConfig({ ...cfg, apiKey: json.api_key });
      return ok(`New key issued and saved: ${c.accent(mask(json.api_key))}`);
    }
    if (sub === "set") {
      let value = args._[1];
      if (args.stdin) {
        if (value || stdin.isTTY) return fail("Pipe one API key to simapi api-key set --stdin.");
        value = "";
        for await (const chunk of stdin) {
          value += chunk;
          if (value.length > 4096) return fail("API key exceeds 4096 characters.");
        }
        value = value.trim();
      }
      if (!value || /\s/.test(value)) return fail("Provide a valid key with simapi api-key set --stdin.");
      const cfg = await readConfig();
      await writeConfig({ ...cfg, apiKey: value });
      return ok(`API key saved: ${c.accent(mask(value))}`);
    }
    if (sub === "delete") {
      if (args._.length !== 1) return fail("Usage: simapi api-key delete");
      const cfg = await readConfig();
      delete cfg.apiKey;
      await writeConfig(cfg);
      return ok("API key deleted from this machine.");
    }
    return fail(`Usage: ${c.accent("simapi api-key <show|generate|set|delete>")}`);
  },

  async config(args) {
    if (args._[0] === "set") {
      const [, k, ...rest] = args._;
      const v = rest.join(" ");
      if (!k || !rest.length) return fail("Usage: simapi config set <key> <value>");
      if (k.toLowerCase() === "apikey") return fail("Use simapi api-key set --stdin to save a key.");
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
    for (const d of list) stdout.write(`   ${c.accent("•")} ${d}\n`);
    stdout.write(`\n  Use with: ${c.accent("simapi validate run.json --type <domain>")}\n\n`);
  },

  async doctor(args) {
    const fix = !!args.fix;
    stdout.write(`\n  ${c.bold("SimAPI doctor")}\n`);
    stdout.write("  " + "─".repeat(46) + "\n");
    let problems = 0;

    try {
      if (fix) await mkdir(CONFIG_DIR, { recursive: true, mode: 0o700 });
      if (existsSync(CONFIG_DIR)) {
        await access(CONFIG_DIR, constants.W_OK | constants.X_OK);
        await readConfig();
        ok(`Config directory writable (${CONFIG_DIR})`);
      } else info("Local config will be created when needed.");
    } catch (error) {
      stderr.write(`  ${diagnostic.red("✗")} Could not use config: ${error.message}\n`);
      problems++;
    }

    const nodeMajor = Number(process.versions.node.split(".")[0]);
    if (nodeMajor >= 18) ok(`Node ${process.version} (>= 18 required)`);
    else {
      stderr.write(`  ${diagnostic.red("✗")} Node ${process.version} is below the minimum supported version (18)\n`);
      problems++;
    }

    try {
      const t = Date.now();
      const res = await api("/v1/health", { timeout: 5_000 });
      if (res.ok) ok(`API reachable at ${API_BASE} (${Date.now() - t}ms, engine=${res.json.engine || "unknown"})`);
      else {
        stderr.write(`  ${diagnostic.red("✗")} API returned HTTP ${res.status}\n`);
        problems++;
      }
    } catch (e) {
      stderr.write(`  ${diagnostic.red("✗")} ${e.message}\n`);
      problems++;
    }

    if (existsSync("simapi.json")) {
      try {
        await readSettings("simapi.json");
        ok("simapi.json found and valid");
      } catch (e) {
        stderr.write(`  ${diagnostic.red("✗")} ${e.message}\n`);
        problems++;
      }
    } else {
      stdout.write(`  ${c.dim("·")} No simapi.json in this directory ${c.dim("(optional — run simapi init)")}\n`);
    }

    stdout.write("  " + "─".repeat(46) + "\n");
    if (problems === 0) stdout.write(`  ${c.green("All checks passed.")}\n\n`);
    else fail(`${problems} setup ${problems === 1 ? "issue" : "issues"} found.`);
  },

  async repair(args) {
    const file = args._[0];
    if (!file) return fail("Usage: simapi repair <file> [--apply] [--output <new-file>]");
    if (args.profile) args.profileData = await loadProfile(args.profile);
    const payload = await loadPayload(file, args);
    const plan = repairPreview(getRows(payload));
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
    const payload = await loadPayload(file, args);
    const report = inspectRows(getRows(payload));
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
      rows = getRows(await loadPayload(file, args));
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
      for (const warning of profile.warnings || []) stderr.write(`  ${warning}\n`);
      return;
    }
    return fail("Usage: simapi profile <import|list|show|delete>");
  },

  async compare(args) {
    if (args._.length !== 2) return fail("Usage: simapi compare <baseline.json> <current.json> [--json] [--fail-on regression]");
    if (args["fail-on"] && args["fail-on"] !== "regression") return fail("--fail-on must be regression for simapi compare.");
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
    if (!cached) return fail(`No cached validation run. Run ${c.accent("simapi validate <file>")} first.`);
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
    const url = new URL("/play", WEB_BASE);
    if (!["http:", "https:"].includes(url.protocol)) return fail("SIMAPI_WEB_URL must be an HTTP(S) URL.");
    await openBrowser(url.href);
    ok(`Opened ${c.accent(url.href)}`);
  },

  version() {
    stdout.write(`${VERSION}\n`);
  },

  help(args) {
    if (args._[0]) printCommandHelp(args._[0]);
    else printHelp();
  },
};

async function loadPayload(file, args, { allowAi = false, key } = {}) {
  if (/\.(mcap|bag)$/i.test(file)) {
    const { readRecording } = await import("../lib/robotics-import.js");
    const recording = await readRecording(new Uint8Array(await readFile(file)), file, { topic: args.topic, episode: args.episode, profile: args.profileData });
    if (recording.requires_topic) throw new Error(`Choose --topic: ${recording.topics.map((t) => t.topic).join(", ")}`);
    return { data: recording.rows, simulation_type: "robotics" };
  }
  const extension = extname(file).toLowerCase();
  if (!["", ".json", ".csv", ".txt", ".log"].includes(extension)) {
    throw new Error("Supported inputs are CSV, JSON, ROS 1 bags, and MCAP. Use simapi validate for optional text parsing.");
  }
  const raw = (await readFile(file, "utf8")).replace(/^\uFEFF/, "");
  if (extension === ".csv") {
    const parsed = parseCsvDocument(raw);
    return { data: parsed.rows, source_lines: parsed.sourceLines };
  }
  try {
    const payload = JSON.parse(raw);
    if (payload && typeof payload === "object") return payload;
  } catch {
    // Only explicit text inputs to validate may use the AI parser.
  }
  if (!allowAi || ![".txt", ".log"].includes(extension)) {
    throw new Error(`${file} must contain a JSON array of samples or an object with a data array.`);
  }
  stderr.write(`Parsing text with the hosted AI parser.\n`);
  const response = await api("/v1/parse", { method: "POST", body: { text: raw, simulation_type: args.type }, key });
  if (!response.ok) throw new Error(`Could not parse ${file}: ${errorMessage(response)}`);
  return response.json;
}

async function assertSeparateOutput(input, output) {
  const inputPath = await realpath(input);
  const outputPath = await realpath(output).catch((error) => {
    if (error.code !== "ENOENT") throw error;
    return resolve(output);
  });
  if (inputPath === outputPath) throw new Error("Choose a report path separate from your recording and profile.");
}

function getRows(payload) {
  const rows = Array.isArray(payload) ? payload : payload?.data ?? payload?.trials;
  if (!Array.isArray(rows) || !rows.length || rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
    throw new Error("The recording must contain at least one sample with named signals.");
  }
  return rows;
}

async function runValidation(file, key, args) {
  if (!existsSync(file)) return fail(`File not found: ${file}`);
  const exact = args["exact-profile"];
  if (exact && !args.profile) return fail("--exact-profile requires --profile <name|file>.");
  const cfg = exact ? {} : await readConfig();
  const projectCfg = exact ? {} : await readSettings("simapi.json");
  const profileName = args.profile ?? projectCfg.profile ?? cfg.profile;
  const threshold = args["fail-on"] ?? projectCfg.fail_on ?? cfg.fail_on;
  if (threshold !== undefined && !["warning", "failed"].includes(threshold)) return fail("--fail-on must be failed or warning.");
  if (args.format && args.format !== "github") return fail("--format must be github.");
  if (args.report) {
    await assertSeparateOutput(file, args.report);
    if (profileName && !resolveFtcProfile(profileName)) {
      const path = existsSync(profileName) ? profileName : profilePath(profileName);
      await assertSeparateOutput(path, args.report);
    }
  }

  const profile = profileName ? await loadProfile(profileName) : undefined;
  const payload = await loadPayload(file, { ...args, profileData: profile }, { allowAi: args.ai && !exact, key });
  const settings = exact || Array.isArray(payload) ? {} : payload;
  const simType = args.type || settings.simulation_type || projectCfg.simulation_type || cfg.simulation_type || "robotics";
  const body = {
    data: getRows(payload),
    simulation_type: simType,
    conditions: settings.conditions || projectCfg.conditions || {},
    robotics_limits: settings.robotics_limits ?? (simType === "robotics" ? projectCfg.robotics_limits : undefined),
    robotics_profile: settings.robotics_profile,
    ftc_limits: settings.ftc_limits,
    units: settings.units,
    run_ai: args.ai ?? false,
  };
  if (profile) {
    if (body.simulation_type !== "robotics") return fail("--profile can only be used with --type robotics.");
    body.robotics_limits = { ...body.robotics_limits, ...profile.robotics_limits };
    body.conditions = { ...body.conditions, ...profile.conditions };
    if (profile.units) body.units = { ...body.units, ...profile.units };
    if (profile.robotics_profile === "ftc") {
      body.robotics_profile = "ftc";
      body.ftc_limits = { ...body.ftc_limits, ...profile.ftc_limits };
    }
  }
  const started = Date.now();
  const response = await api("/v1/validate", { method: "POST", body, key });
  if (!response.ok) return fail(errorMessage(response));
  if (!["passed", "warning", "failed"].includes(response.json?.status)) {
    return fail("The validation API returned an invalid report. Check SIMAPI_BASE_URL or try again.");
  }
  const r = {
    ...response.json,
    validation_context: {
      simulation_type: body.simulation_type,
      robotics_limits: body.robotics_limits || {},
      conditions: body.conditions,
      ...(body.robotics_profile ? { robotics_profile: body.robotics_profile } : {}),
      ...(body.ftc_limits ? { ftc_limits: body.ftc_limits } : {}),
      ...(body.units ? { units: body.units } : {}),
    },
  };
  if (args.report) await writeJsonAtomic(args.report, r);
  try {
    await trackUsage(Date.now() - started);
    await writeJson(LAST_RUN_PATH, { file, t: Date.now(), result: r });
  } catch {
    stderr.write("Could not update local run history. Check your SIMAPI_CONFIG_DIR permissions.\n");
  }
  if (args.format === "github") {
    for (const line of githubAnnotations(r, file, payload.source_lines)) stderr.write(line + "\n");
  }
  if (args.json) stdout.write(JSON.stringify(r, null, 2) + "\n");
  else if (args.summary || args.format === "github" || env.CI) {
    stdout.write(`${r.status.toUpperCase()}  ${file}  ${r.trials_submitted ?? "?"} samples, ${r.trials_excluded ?? "?"} excluded, ${r.failed ?? "?"} failed checks, ${r.warnings ?? "?"} warnings\n`);
    printRoboticsWarnings(r);
    for (const issue of (r.issues || []).slice(0, 3)) stdout.write(`  ${issue.human_name || issue.name}: ${issue.detail || ""}\n`);
  } else renderReport(r, file, body.simulation_type);

  const failedThreshold = (threshold === "warning" && r.status !== "passed") ||
    (threshold === "failed" && r.status === "failed");
  process.exitCode = failedThreshold ? 1 : 0;
}

function printRoboticsWarnings(r) {
  const warnings = r.robotics_warnings || r.screening_warnings || r.robotics_summary?.screening_warnings || [];
  for (const warning of warnings) {
    const detail = typeof warning === "string" ? warning : warning?.detail;
    if (detail) stderr.write(`  ${diagnostic.amber("⚠")} ${detail}\n`);
  }
}

function renderReport(r, file, simType) {
  const status = (r.status || "").toUpperCase();
  const tone = r.status === "passed" ? c.green : r.status === "warning" ? c.amber : c.red;
  const mark = r.status === "passed" ? "✓" : r.status === "warning" ? "⚠" : "✗";
  const failures = r.failed ?? (r.issues || []).filter((i) => i.status === "failed").length;
  const warns = r.warnings ?? (r.issues || []).filter((i) => i.status === "warning").length;

  // Status banner
  const title = ` ${mark}  ${status}`;
  stdout.write(`\n  ${tone(title.trimStart())}  ${file}\n\n`);

  // Summary
  const excl = r.trials_excluded ?? 0;
  row("Simulation", simType);
  if (r.robotics_summary) {
    row("Motion engine", r.robotics_summary.engine_version);
    row("Episodes", String(r.robotics_summary.episodes?.length ?? "—"));
    if (r.robotics_summary.limits_source) row("Joint limits", r.robotics_summary.limits_source);
  }
  printRoboticsWarnings(r);
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
    for (const rec of recs.slice(0, 6)) stdout.write(`   ${c.accent("→")} ${rec}\n`);
  }
  if (r.ai && r.ai.dataset_summary) {
    stdout.write(`\n  ${c.bold("AI review")}  ${c.dim(r.ai.model ? r.ai.model.split("/").pop() : "")}\n   ${c.dim(r.ai.dataset_summary)}\n`);
  }
  stdout.write("\n");
}

// ── Help ──────────────────────────────────────────────────────────────────────
const VALIDATE_OPTIONS = [
  ["--profile <name|file>", "Use a saved or built-in profile, or a JSON profile file"],
  ["--exact-profile", "Use only the named profile's check settings"],
  ["--type <domain>", "Select a simulation domain (default: robotics)"],
  ["--topic <name>", "Select a JointState channel in a ROS bag or MCAP"],
  ["--episode <id>", "Set the episode ID for a ROS bag or MCAP"],
  ["--report <file>", "Write or replace a JSON report at the given path"],
  ["--fail-on <level>", "Exit 1 on 'failed' checks, or on 'warning' and failed checks"],
  ["--format github", "Write GitHub Actions annotations to stderr"],
  ["--json", "Print only the JSON report to stdout"],
  ["--summary", "Print a compact report (the default in CI)"],
  ["--ai / --no-ai", "Enable optional AI review and text parsing (default: off)"],
];

const HELP = {
  init: { usage: "simapi init", desc: "Create simapi.json with starter robotics settings in this directory." },
  validate: {
    usage: "simapi validate <file> [options]",
    desc: "Check CSV, JSON, or a robot recording using the hosted validation engine.",
    opts: VALIDATE_OPTIONS,
    ex: ["simapi validate run.csv", "simapi validate run.json --profile ./arm-profile.json --exact-profile --report ./simapi-report.json --fail-on failed"],
  },
  inspect: {
    usage: "simapi inspect <file> [options]",
    desc: "Inspect episode counts, sample timing, and signal ranges locally.",
    opts: [["--json", "Print JSON to stdout"], ["--profile <name|file>", "Load joint metadata"], ["--topic <name>", "Select a recording channel"], ["--episode <id>", "Assign the recording an episode ID"]],
  },
  doctor: {
    usage: "simapi doctor [--fix]",
    desc: "Check local configuration and whether the hosted API is reachable.",
    opts: [["--fix", "Create the local config directory if it is missing"]],
  },
  import: {
    usage: "simapi import <file> --output <run.json>",
    desc: "Extract JointState samples from a ROS bag or MCAP, or convert CSV and JSON recordings.",
    opts: [["--topic <name>", "Select a JointState channel"], ["--list-topics", "List channels instead of importing"], ["--json", "Print channel listings as JSON"], ["--profile <name|file>", "Load joint metadata"], ["--episode <id>", "Assign an episode ID"]],
  },
  profile: {
    usage: "simapi profile <import|list|show|delete>",
    desc: "Manage reusable URDF and JSON profiles. FTC and FRC profiles are built in.",
    ex: ["simapi profile import arm.urdf --name arm --output arm-profile.json", "simapi profile list --json", "simapi profile show arm", "simapi validate drive-log.csv --profile ftc"],
  },
  compare: {
    usage: "simapi compare <baseline.json> <current.json>",
    desc: "Compare findings, excluded samples, and settings between two reports.",
    opts: [["--json", "Print a JSON comparison"], ["--fail-on regression", "Exit 1 on new or more severe findings"]],
  },
  repair: {
    usage: "simapi repair <file> [options]",
    desc: "Preview recording repairs locally. Use --apply to write a separate file.",
    opts: [["--apply", "Write a repaired copy if the preview proposes changes"], ["--output <file>", "Set the repaired copy's path"], ["--json", "Print the repair plan as JSON"], ["--profile <name|file>", "Load joint metadata for a ROS recording"], ["--topic <name>", "Select a recording channel"], ["--episode <id>", "Assign the recording an episode ID"]],
  },
  watch: { usage: "simapi watch <file> [options]", desc: "Validate again when the recording changes.", opts: VALIDATE_OPTIONS },
  explain: { usage: "simapi explain", desc: "Show findings from the last validation." },
  domains: { usage: "simapi domains", desc: "List the simulation domains supported by validate." },
  usage: { usage: "simapi usage", desc: "Show local request counts and average validation time." },
  open: { usage: "simapi open", desc: "Open the SimAPI playground in your browser." },
  "api-key": {
    usage: "simapi api-key <show|generate|set|delete>",
    desc: "Manage an optional API key for a private deployment. Public validation needs no account.",
    ex: ["simapi api-key show", "simapi api-key set --stdin"],
  },
  config: { usage: "simapi config [set <key> <value>]", desc: "Show or update local CLI settings.", ex: ["simapi config set fail_on warning"] },
  version: { usage: "simapi --version", desc: "Print the installed version." },
  help: { usage: "simapi help [command]", desc: "Show command help." },
};

const START_COMMANDS = ["init", "validate", "inspect", "doctor"];

function printHelp(compact = false) {
  stdout.write(`\n  ${c.accent(c.bold("SimAPI"))}  ${c.dim(`v${VERSION}`)}\n`);
  stdout.write("  Validate robot recordings and profiles. No account required.\n\n");
  stdout.write(`  ${c.bold("Usage")}  simapi <command> [options]\n\n`);
  printCommandList("Start here", START_COMMANDS);
  if (!compact) {
    printCommandList("Recordings and reports", ["import", "profile", "compare", "repair", "watch", "explain"]);
    printCommandList("Tools and settings", ["domains", "usage", "open", "api-key", "config", "version", "help"]);
  }
  stdout.write(compact
    ? `  Run ${c.accent("simapi --help")} for all commands.\n\n`
    : `  Run ${c.accent("simapi <command> --help")} for options and examples.\n\n`);
}

function printCommandList(heading, names) {
  stdout.write(`  ${c.bold(heading)}\n`);
  for (const name of names) {
    stdout.write(`    ${c.accent(name.padEnd(9))}  ${HELP[name].desc}\n`);
  }
  stdout.write("\n");
}

function printCommandHelp(name) {
  if (!Object.hasOwn(HELP, name)) return fail(`Unknown command: ${name}. Run simapi --help.`);
  const h = HELP[name];
  stdout.write(`\n  ${c.accent(h.usage)}\n  ${h.desc}\n`);
  if (h.opts) {
    stdout.write(`\n  ${c.bold("Options")}\n`);
    for (const [o, d] of h.opts) stdout.write(`    ${c.accent(o.padEnd(23))} ${d}\n`);
  }
  if (h.ex) {
    stdout.write(`\n  ${c.bold("Examples")}\n`);
    for (const example of h.ex) stdout.write(`    ${example}\n`);
  }
  if (name === "validate") {
    stdout.write("\n  Exit codes: 0 checks complete, 1 threshold reached, 2 command or service error.\n");
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
function fail(message) {
  stderr.write(`${diagnostic.red("Error:")} ${message}\n`);
  process.exitCode = 2;
}

const NUMBER_OF_POSITIONALS = {
  init: 0, validate: 1, watch: 1, usage: 0, "api-key": 2, domains: 0,
  doctor: 0, repair: 1, inspect: 1, import: 1, profile: 2, compare: 2,
  explain: 0, open: 0, version: 0, help: 1,
};
const VALUE_FLAGS = new Set(["report", "output", "topic", "episode", "name", "format", "type", "profile", "fail-on"]);
const RECORDING_FLAGS = ["profile", "topic", "episode", "json"];
const VALIDATE_FLAGS = [...RECORDING_FLAGS, "report", "format", "type", "fail-on", "summary", "ai", "no-ai", "exact-profile"];
const COMMAND_FLAGS = {
  validate: VALIDATE_FLAGS,
  watch: VALIDATE_FLAGS,
  inspect: RECORDING_FLAGS,
  import: [...RECORDING_FLAGS, "list-topics", "output"],
  repair: [...RECORDING_FLAGS, "apply", "output"],
  doctor: ["fix"],
  profile: ["json", "name", "output"],
  compare: ["json", "fail-on"],
  "api-key": ["stdin"],
};

function parse(command, argv) {
  const args = { _: [] };
  const flags = COMMAND_FLAGS[command] ?? [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--") {
      args._.push(...argv.slice(i + 1));
      break;
    }
    if (arg === "-h" || arg === "--help") args.help = true;
    else if (arg.startsWith("--")) {
      const equals = arg.indexOf("=");
      const flag = arg.slice(2, equals < 0 ? undefined : equals);
      if (!flags.includes(flag)) throw new Error(`Unknown option for ${command}: --${flag}. Run simapi ${command} --help.`);
      if (VALUE_FLAGS.has(flag)) {
        const value = equals < 0 ? argv[++i] : arg.slice(equals + 1);
        if (!value || (equals < 0 && value.startsWith("--"))) throw new Error(`--${flag} requires a value.`);
        args[flag] = value;
      } else {
        if (equals >= 0) throw new Error(`--${flag} does not take a value.`);
        if (flag === "ai" || flag === "no-ai") args.ai = flag === "ai";
        else args[flag] = true;
      }
    } else if (arg.startsWith("-")) {
      throw new Error(`Unknown option for ${command}: ${arg}. Run simapi ${command} --help.`);
    } else args._.push(arg);
  }
  if (args._.length > NUMBER_OF_POSITIONALS[command]) throw new Error(`Too many arguments. Run simapi ${command} --help.`);
  return args;
}

async function main() {
  const [, , cmd, ...rest] = process.argv;
  if (!cmd) return printHelp(true);
  if (cmd === "--help" || cmd === "-h") {
    if (rest.length === 1) return printCommandHelp(rest[0]);
    if (!rest.length) return printHelp();
    return fail("Usage: simapi help [command]");
  }
  const name = cmd === "apikey" ? "api-key" : ["--version", "-v"].includes(cmd) ? "version" : cmd;
  if (!Object.hasOwn(commands, name)) return fail(`Unknown command: ${cmd}. Run simapi --help.`);
  const args = parse(name, rest);
  if (args.help) return printCommandHelp(name);
  await commands[name](args);
}

main().catch((error) => {
  if (error.code === "EEXIST") return fail(`File already exists: ${error.path}. Choose another path.`);
  if (error.code === "ENOENT") return fail(`File or directory not found: ${error.path}`);
  fail(error.message);
});
