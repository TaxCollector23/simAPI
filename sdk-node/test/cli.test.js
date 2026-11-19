import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const entry = fileURLToPath(new URL("../bin/simapi.js", import.meta.url));

async function workspace(t) {
  const cwd = await mkdtemp(join(tmpdir(), "simapi-cli-"));
  const config = join(cwd, "config");
  const env = { ...process.env, SIMAPI_CONFIG_DIR: config, NO_COLOR: "" };
  delete env.SIMAPI_API_KEY;
  delete env.SIMAPI_BASE_URL;
  t.after(() => rm(cwd, { recursive: true, force: true }));

  function cli(args, input) {
    return new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [entry, ...args], { cwd, env });
      let stdout = "", stderr = "";
      child.stdout.on("data", (part) => { stdout += part; });
      child.stderr.on("data", (part) => { stderr += part; });
      child.once("error", reject);
      child.once("close", (code) => resolve({ code, stdout, stderr }));
      child.stdin.end(input);
    });
  }

  async function serve(handler) {
    const server = createServer(handler);
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    env.SIMAPI_BASE_URL = `http://127.0.0.1:${server.address().port}/api/`;
    t.after(() => new Promise((resolve) => server.close(resolve)));
  }

  return { cwd, config, cli, serve };
}

test("first run, help and version work without a config directory", async (t) => {
  const { cli, config } = await workspace(t);
  const start = await cli([]);
  assert.equal(start.code, 0);
  assert.equal(start.stderr, "");
  assert.match(start.stdout, /SimAPI\s+v\d+\.\d+\.\d+/);
  assert.match(start.stdout, /No account required/);
  for (const name of ["init", "validate", "inspect", "doctor"]) {
    assert.match(start.stdout, new RegExp(`^\\s+${name}\\s+`, "m"));
  }
  assert.doesNotMatch(start.stdout, /\x1b|████|api-key|config set/);
  assert.match((await cli(["--help"])).stdout, /Recordings and reports/);
  const help = await cli(["help", "validate"]);
  assert.equal(help.code, 0);
  assert.match(help.stdout, /--exact-profile/);
  assert.match(help.stdout, /threshold reached/);
  const { version } = JSON.parse(await readFile(new URL("../package.json", import.meta.url)));
  assert.deepEqual(await cli(["--version"]), { code: 0, stdout: version + "\n", stderr: "" });
  await assert.rejects(stat(config), { code: "ENOENT" });
});

test("setup refuses to overwrite existing settings and usage errors stay on stderr", async (t) => {
  const { cli, cwd } = await workspace(t);
  const first = await cli(["init"]);
  assert.equal(first.code, 0);
  assert.match(first.stdout, /Created simapi\.json/);
  const path = join(cwd, "simapi.json");
  const settings = await readFile(path, "utf8");
  assert.equal(JSON.parse(settings).simulation_type, "robotics");

  for (const [args, message] of [
    [["init"], /File already exists: simapi\.json/],
    [["init", "--profile", "oops"], /Unknown option for init/],
    [["validate", "--report"], /--report requires a value/],
    [["validate", "a.csv", "b.csv"], /Too many arguments/],
    [["toString"], /Unknown command/],
  ]) {
    const result = await cli(args);
    assert.equal(result.code, 2);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, message);
  }
  assert.equal(await readFile(path, "utf8"), settings);
});

test("CI replay sends only the downloaded check settings and writes the report at either threshold", async (t) => {
  const { cli, cwd, config, serve } = await workspace(t);
  const rows = [{ episode_id: "reach", time: 0, joint_1_position: 2 }];
  const profile = {
    schema_version: 1,
    name: "Bench arm",
    robotics_limits: { joint_1_position: [-1, 1] },
    units: { joint_1_position: "rad" },
    conditions: { max_time_step: 0.2 },
  };
  const recording = {
    data: rows,
    conditions: { max_time_step: 99, velocity_tolerance: 100 },
    robotics_limits: { joint_9_position: [-10, 10] },
    robotics_profile: "ftc",
    units: { joint_1_position: "deg" },
  };
  await writeFile(join(cwd, "simapi-run.json"), JSON.stringify(recording));
  await writeFile(join(cwd, "simapi-profile.json"), JSON.stringify(profile));
  await writeFile(join(cwd, "simapi.json"), JSON.stringify({
    profile: "ftc", simulation_type: "aerodynamics", fail_on: "warning",
    conditions: { payload: 100 }, robotics_limits: { joint_10_position: [-15, 15] },
  }));
  await mkdir(config);
  await writeFile(join(config, "config.json"), JSON.stringify({ simulation_type: "ftc", fail_on: "warning" }));
  const requests = [];
  await serve(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    requests.push({ url: req.url, key: req.headers["x-api-key"], body: JSON.parse(body) });
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({
      status: "warning",
      warnings: 1,
      issues: [],
      robotics_warnings: [{ name: "battery", detail: "Battery voltage low" }],
    }));
  });

  for (const [threshold, exitCode] of [["failed", 0], ["warning", 1]]) {
    const result = await cli([
      "validate", "./simapi-run.json", "--type", "robotics",
      "--profile", "./simapi-profile.json", "--exact-profile", "--no-ai",
      "--report", "./simapi-report.json", "--fail-on", threshold, "--json",
    ]);
    assert.equal(result.code, exitCode, result.stderr);
    assert.equal(result.stderr, "");
    const report = JSON.parse(result.stdout);
    assert.equal(report.status, "warning");
    assert.deepEqual(JSON.parse(await readFile(join(cwd, "simapi-report.json"), "utf8")), report);
    assert.deepEqual(requests.at(-1), {
      url: "/api/v1/validate",
      key: undefined,
      body: {
        data: rows,
        simulation_type: "robotics",
        run_ai: false,
        robotics_limits: profile.robotics_limits,
        conditions: profile.conditions,
        units: profile.units,
      },
    });
  }

  const noProfile = await cli(["validate", "./simapi-run.json", "--exact-profile"]);
  assert.equal(noProfile.code, 2);
  assert.match(noProfile.stderr, /requires --profile/);
  const collision = await cli([
    "validate", "./simapi-run.json", "--profile", "./simapi-profile.json",
    "--exact-profile", "--report", "./simapi-run.json",
  ]);
  assert.equal(collision.code, 2);
  assert.match(collision.stderr, /separate from your recording/);
  assert.equal(requests.length, 2);
  assert.deepEqual(JSON.parse(await readFile(join(cwd, "simapi-run.json"))), recording);

  const summary = await cli(["validate", "./simapi-run.json", "--profile", "./simapi-profile.json", "--exact-profile", "--summary"]);
  assert.equal(summary.code, 0);
  assert.match(summary.stdout, /^WARNING/);
  assert.doesNotMatch(summary.stdout, /Battery voltage/);
  assert.match(summary.stderr, /Battery voltage low/);
});

test("the API rate limit and local file problems produce actionable errors without fake JSON", async (t) => {
  const { cli, cwd, serve } = await workspace(t);
  await writeFile(join(cwd, "run.csv"), "time,joint_1_position\n0,0\n");
  await writeFile(join(cwd, "broken.json"), "{");
  let requests = 0;
  await serve((req, res) => {
    requests++;
    res.writeHead(429, { "retry-after": "10" });
    res.end();
  });

  const malformed = await cli(["inspect", "broken.json", "--json"]);
  assert.equal(malformed.code, 2);
  assert.equal(malformed.stdout, "");
  assert.match(malformed.stderr, /must contain a JSON array/);
  assert.equal(requests, 0);

  const limited = await cli(["validate", "run.csv", "--report", "report.json", "--json"]);
  assert.equal(limited.code, 2);
  assert.equal(limited.stdout, "");
  assert.match(limited.stderr, /HTTP 429.*Try again in 10 seconds/);
  assert.equal(requests, 1);
  await assert.rejects(stat(join(cwd, "report.json")), { code: "ENOENT" });
});

test("private deployment credentials can be piped in and are masked in output", async (t) => {
  const { cli, config } = await workspace(t);
  const temporaryKey = "example";
  const saved = await cli(["api-key", "set", "--stdin"], temporaryKey + "\n");
  assert.equal(saved.code, 0, saved.stderr);
  const shown = await cli(["api-key", "show"]);
  assert.doesNotMatch(saved.stdout + shown.stdout, /example/);
  assert.match(shown.stdout, /••••/);
  const file = join(config, "config.json");
  assert.equal(JSON.parse(await readFile(file, "utf8")).apiKey, temporaryKey);
  if (process.platform !== "win32") assert.equal((await stat(file)).mode & 0o777, 0o600);
});
