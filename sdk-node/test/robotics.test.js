import test from "node:test";
import assert from "node:assert/strict";
import { readFile, mkdtemp, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { McapWriter } from "@mcap/core";
import { parse } from "@foxglove/rosmsg";
import { MessageWriter as Ros1Writer } from "@foxglove/rosmsg-serialization";
import { MessageWriter as Ros2Writer } from "@foxglove/rosmsg2-serialization";
import {
  profileFromUrdf,
  readRecording,
  jointStateRow,
} from "../lib/robotics-import.js";
import { validateFtcLog, resolveFtcProfile } from "../lib/ftc-frc.js";
import {
  parseCsv,
  parseCsvDocument,
  inspectRows,
  toCsv,
  validateProfile,
  repairPreview,
  compareReports,
  buildEvidence,
  githubAnnotations,
} from "../lib/robotics-workflow.js";

const urdf =
  '<robot name="arm"><joint name="shoulder" type="revolute"><limit lower="-1" upper="1" velocity="2" effort="10"/></joint><joint name="slider" type="prismatic"><limit lower="0" upper="0.5" velocity="0.2" effort="20"/></joint><joint name="wrist" type="continuous"><limit velocity="3" effort="5"/></joint></robot>';
const profile = profileFromUrdf(urdf);
const report = (status, extra = {}) => ({
  status,
  trials_excluded: 0,
  issues: [],
  robotics_checks: [],
  validation_context: {
    simulation_type: "robotics",
    robotics_limits: {},
    conditions: {},
  },
  ...extra,
});
async function mcap(encoding = "json", count = 3, topicCount = 1) {
  const chunks = [];
  let pos = 0n;
  const writer = new McapWriter({
    writable: {
      position: () => pos,
      write: async (b) => {
        chunks.push(new Uint8Array(b));
        pos += BigInt(b.length);
      },
    },
  });
  await writer.start({ profile: "", library: "SimAPI test" });
  const ros2 = encoding === "cdr";
  const text = ros2
    ? "std_msgs/Header header\nstring[] name\nfloat64[] position\nfloat64[] velocity\nfloat64[] effort\n================================================================================\nMSG: std_msgs/Header\nbuiltin_interfaces/Time stamp\nstring frame_id\n================================================================================\nMSG: builtin_interfaces/Time\nint32 sec\nuint32 nanosec\n"
    : "std_msgs/Header header\nstring[] name\nfloat64[] position\nfloat64[] velocity\nfloat64[] effort\n================================================================================\nMSG: std_msgs/Header\nuint32 seq\ntime stamp\nstring frame_id\n";
  const schema = await writer.registerSchema({
    name: ros2 ? "sensor_msgs/msg/JointState" : "sensor_msgs/JointState",
    encoding: encoding === "json" ? "jsonschema" : ros2 ? "ros2msg" : "ros1msg",
    data: new TextEncoder().encode(encoding === "json" ? "{}" : text),
  });
  const serializer =
    encoding === "json"
      ? null
      : ros2
        ? new Ros2Writer(parse(text, { ros2: true }))
        : new Ros1Writer(parse(text));
  for (let t = 0; t < topicCount; t++) {
    const channelId = await writer.registerChannel({
      topic: `/joint_states${t || ""}`,
      schemaId: schema,
      messageEncoding: encoding,
      metadata: new Map(),
    });
    for (let i = 0; i < count; i++) {
      const stamp = ros2
          ? { sec: 0, nanosec: i * 100000000 }
          : { sec: 0, nsec: i * 100000000 },
        msg = {
          header: { seq: i, stamp, frame_id: "" },
          name: ["shoulder", "slider"],
          position: [i * 0.1, i * 0.01],
          velocity: [1, 0.1],
          effort: [2, 3],
        };
      await writer.addMessage({
        channelId,
        sequence: i,
        logTime: BigInt(i) * 100000000n,
        publishTime: BigInt(i) * 100000000n,
        data: serializer
          ? serializer.writeMessage(msg)
          : new TextEncoder().encode(JSON.stringify(msg)),
      });
    }
  }
  await writer.end();
  return Buffer.concat(chunks);
}
test("URDF imports declared units, prismatic force, no invented continuous position/acceleration", () => {
  assert.deepEqual(profile.robotics_limits.joint_shoulder_position, [-1, 1]);
  assert.deepEqual(profile.robotics_limits.joint_slider_force, [-20, 20]);
  assert.equal(profile.units.joint_slider_velocity, "m/s");
  assert.equal(profile.robotics_limits.joint_wrist_position, undefined);
  assert.equal(profile.robotics_limits.joint_shoulder_acceleration, undefined);
  assert.throws(
    () => profileFromUrdf("<!DOCTYPE robot><robot/>"),
    /resolved URDF/,
  );
  assert.throws(
    () =>
      profileFromUrdf(
        '<robot><joint name="x" type="revolute"/><joint name="x" type="revolute"/></robot>',
      ),
    /collide/,
  );
  assert.throws(() => profileFromUrdf("<robot>"), /Invalid URDF/);
});
test("JointState rejects mismatched arrays and colliding names; absent optional fields stay absent", () => {
  assert.throws(
    () => jointStateRow({ name: ["a", "b"], position: [1] }, 0),
    /length/,
  );
  assert.throws(
    () => jointStateRow({ name: ["a-b", "a_b"], position: [1, 2] }, 0),
    /Duplicate/,
  );
  const row = jointStateRow(
    { name: ["slider"], position: [0.1], velocity: [], effort: [4] },
    2,
    "x",
    profile,
  );
  assert.equal(row.joint_slider_velocity, undefined);
  assert.equal(row.joint_slider_force, 4);
});
for (const encoding of ["json", "ros1", "cdr"])
  test(`reads actual ${encoding} MCAP and rejects truncation`, async () => {
    const bytes = await mcap(encoding),
      r = await readRecording(bytes, "run.mcap", { profile });
    assert.equal(r.rows.length, 3);
    assert.equal(r.rows[1].time, 0.1);
    assert.equal(r.rows[1].joint_slider_force, 3);
    await assert.rejects(
      readRecording(bytes.subarray(0, bytes.length - 15), "bad.mcap"),
      /truncated|incomplete|magic|record/i,
    );
  });
test("multiple MCAP topics need explicit selection; samples never silently truncate", async () => {
  const bytes = await mcap("json", 2, 2),
    p = await readRecording(bytes, "run.mcap");
  assert.equal(p.requires_topic, true);
  assert.equal(p.rows.length, 0);
  const r = await readRecording(bytes, "run.mcap", {
    topic: "/joint_states1",
    episode: "pick",
  });
  assert.equal(r.rows.length, 2);
  assert.equal(r.rows[0].episode_id, "pick");
  await assert.rejects(
    readRecording(bytes, "run.mcap", { topic: "/wrong" }),
    /Topic not found/,
  );
  await assert.rejects(
    readRecording(await mcap("json", 10001), "big.mcap"),
    /exceeds 10,000/,
  );
});
for (const compression of ["none", "bz2", "lz4"])
  test(`reads independent ROS 1 bag fixture (${compression})`, async () => {
    const bytes = new Uint8Array(
        await readFile(
          new URL(`fixtures/joint-states-${compression}.bag`, import.meta.url),
        ),
      ),
      r = await readRecording(bytes, "run.bag", { profile });
    assert.equal(r.rows.length, 3);
    assert.equal(r.rows[2].time, 0.2);
    assert.equal(r.rows[0].joint_slider_force, 3);
  });
test("CSV round-trips quoted strings, episode identifiers and missing values; rejects collisions", () => {
  const input = [
    { episode_id: "001", time: 0, joint_a_position: null, note: 'a,"b"' },
  ];
  assert.deepEqual(parseCsv(toCsv(input)), input);
  assert.throws(() => parseCsv("a,b\n1"), /wrong number/);
  assert.throws(() => parseCsv("a-b,a_b\n1,2"), /unique/);
  assert.throws(
    () => validateProfile({ robotics_limits: { a: [1, 1] } }),
    /Invalid range/,
  );
  assert.throws(
    () => validateProfile({ conditions: { max_time_step: 0 } }),
    /positive/,
  );
});
test("repairs preserve the original, episode boundaries and conflicting samples", () => {
  const source = [
      { episode_id: "a", time: 2, joint_a_position: 2 },
      { episode_id: "a", time: 0, joint_a_position: 0 },
      { episode_id: "a", time: 1, joint_a_position: null },
      { episode_id: "a", time: 2, joint_a_position: 2 },
      { episode_id: "b", time: 0, joint_a_position: null },
      { episode_id: "b", time: 1, joint_a_position: 10 },
    ],
    original = structuredClone(source),
    p = repairPreview(source);
  assert.deepEqual(source, original);
  assert.equal(p.repaired_data.length, 5);
  assert.equal(p.repaired_data[1].joint_a_position, 1);
  assert.equal(p.repaired_data[3].joint_a_position, null);
  const conflict = repairPreview([
    { time: 0, joint_a_position: 1 },
    { time: 0, joint_a_position: 2 },
  ]);
  assert.equal(conflict.proposals.length, 0);
  assert.match(conflict.unrepairable[0].reason, /conflicting/);
});
test("comparison notices worsened severity under the same name and unknown settings", () => {
  const a = report("warning", { issues: [{ name: "q", status: "warning" }] }),
    b = report("failed", { issues: [{ name: "q", status: "failed" }] }),
    d = compareReports(a, b);
  assert.equal(d.regressed, true);
  assert.equal(d.introduced.length, 1);
  assert.equal(d.same_configuration, true);
  assert.equal(
    compareReports(a, { ...b, validation_context: undefined })
      .same_configuration,
    null,
  );
});
test("evidence reports actual derivatives, explicit caps, and escaped CI annotations", () => {
  const rows = [
      { episode_id: "a", time: 0, joint_shoulder_position: 0 },
      { episode_id: "a", time: 0.1, joint_shoulder_position: 1 },
    ],
    e = buildEvidence(rows, [
      {
        name: "robotics_derived_limit:joint_shoulder_velocity",
        column: "joint_shoulder_velocity",
        indices: [1],
        detail: "too fast",
      },
    ]);
  assert.equal(e.entries[0].observed, 10);
  assert.equal(e.entries[0].episode_id, "a");
  assert.equal(e.entries[0].time, 0.1);
  const many = buildEvidence(
    Array.from({ length: 1001 }, (_, i) => ({ time: i, joint_a_position: 2 })),
    [],
    { joint_a_position: [-1, 1] },
  );
  assert.equal(many.entries.length, 1000);
  assert.equal(many.total, 1001);
  assert.equal(many.truncated, true);
  const lines = githubAnnotations(
    {
      robotics_evidence: [
        { ...e.entries[0], detail: "bad\n::error::injected" },
      ],
    },
    "run.csv",
    [2, 3],
  );
  assert.match(lines[0], /line=3/);
  assert.ok(lines[0].includes("%0A"));
  assert.equal(lines.length, 1);
});
function cli(args, env) {
  return new Promise((resolve) => {
    const p = spawn(
      process.execPath,
      [new URL("../bin/simapi.js", import.meta.url).pathname, ...args],
      { env: { ...process.env, NO_COLOR: "1", ...env } },
    );
    let out = "",
      err = "";
    p.stdout.on("data", (b) => (out += b));
    p.stderr.on("data", (b) => (err += b));
    p.on("close", (code) => resolve({ code, out, err }));
  });
}
test("CLI profiles/import/CI gating/comparison/repair work together without changing input", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "simapi-flow-")),
    env = { SIMAPI_CONFIG_DIR: join(dir, "config") },
    urdfPath = join(dir, "arm.urdf"),
    input = join(dir, "run.csv"),
    output = join(dir, "run.json");
  await writeFile(urdfPath, urdf);
  await writeFile(
    input,
    "episode_id,time,joint_shoulder_position\na,0,0\na,0.1,2\n",
  );
  let r = await cli(["profile", "import", urdfPath, "--name", "arm"], env);
  assert.equal(r.code, 0, r.err);
  r = await cli(["profile", "show", "arm"], env);
  assert.deepEqual(
    JSON.parse(r.out).robotics_limits.joint_shoulder_velocity,
    [-2, 2],
  );
  r = await cli(["import", input, "--output", output], env);
  assert.equal(r.code, 0, r.err);
  assert.equal(JSON.parse(await readFile(output, "utf8")).length, 2);
  const response = report("failed", {
    issues: [{ name: "limit", status: "failed", detail: "outside range" }],
    robotics_evidence: [
      {
        check: "limit",
        signal: "joint_shoulder_position",
        episode_id: "a",
        sample_index: 1,
        time: 0.1,
        detail: "outside range",
        status: "failed",
      },
    ],
  });
  let received;
  const server = createServer(async (req, res) => {
    let text = "";
    for await (const b of req) text += b;
    received = JSON.parse(text);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(response));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  env.SIMAPI_BASE_URL = `http://127.0.0.1:${server.address().port}`;
  const path = join(dir, "report.json");
  r = await cli(
    [
      "validate",
      input,
      "--profile",
      "arm",
      "--no-ai",
      "--format",
      "github",
      "--json",
      "--report",
      path,
      "--fail-on",
      "failed",
    ],
    env,
  );
  assert.equal(r.code, 1);
  assert.equal(JSON.parse(r.out).status, "failed");
  assert.equal(received.run_ai, false);
  assert.deepEqual(received.robotics_limits.joint_shoulder_position, [-1, 1]);
  assert.match(r.err, /::error file=.*line=3/);
  const baseline = join(dir, "baseline.json");
  await writeFile(baseline, JSON.stringify(report("passed")));
  r = await cli(
    ["compare", baseline, path, "--json", "--fail-on", "regression"],
    env,
  );
  assert.equal(r.code, 1);
  assert.equal(JSON.parse(r.out).regressed, true);
  const broken = join(dir, "broken.csv");
  await writeFile(
    broken,
    "episode_id,time,joint_a_position\na,0,0\na,0,0\na,1,1\n",
  );
  r = await cli(["repair", broken, "--apply", "--json"], env);
  assert.equal(r.code, 0, r.err);
  assert.equal(JSON.parse(r.out).repaired_samples, 2);
  assert.match(await readFile(broken, "utf8"), /a,0,0\na,0,0/);
  r = await cli(["repair", broken, "--apply", "--output", broken], env);
  assert.equal(r.code, 1);
  assert.match(await readFile(broken, "utf8"), /a,0,0\na,0,0/);
});

test("CSV source locations account for multiline quoted records and inspection keeps unknown time null", () => {
  const doc = parseCsvDocument(
    'note,time,joint_a_position\n"two\nlines",0,1\nnext,1,2\n',
  );
  assert.deepEqual(doc.sourceLines, [2, 4]);
  const lines = githubAnnotations(
    {
      robotics_evidence: [
        {
          check: "limit",
          status: "failed",
          sample_index: 1,
          episode_id: "a",
          signal: "q",
          time: 1,
          detail: "bad",
        },
      ],
    },
    "run.csv",
    doc.sourceLines,
  );
  assert.match(lines[0], /line=4/);
  assert.equal(
    inspectRows([{ joint_a_position: 0 }, { joint_a_position: null }])
      .episodes[0].duration_seconds,
    null,
  );
});

test('browser and CLI helpers are the same implementation', async () => {
  for (const name of ['robotics-import.js','robotics-import.d.ts','robotics-workflow.js','robotics-workflow.d.ts']) {
    assert.equal(await readFile(new URL(`../lib/${name}`,import.meta.url),'utf8'),await readFile(new URL(`../../web/lib/${name}`,import.meta.url),'utf8'));
  }
});


test("FTC/FRC profile flags power 1.4 and accepts a wrapped heading", () => {
  const rows = parseCsvDocument(readFileSync(new URL("../../tests/fixtures/ftc-drive-log.csv", import.meta.url), "utf8")).rows;
  const report = validateFtcLog(rows);
  assert.equal(report.verdict, "failed");
  assert.deepEqual(report.failed_checks.map((check) => check.name), ["power_range"]);
  assert.equal(report.excluded_rows["1"][0], "left_motor_power=1.4 outside [-1, 1]");
  assert.ok(!report.failed_checks.some((check) => check.name === "heading_jump"));
  assert.equal(resolveFtcProfile("frc").robotics_profile, "ftc");
  assert.deepEqual(resolveFtcProfile("ftc").ftc_limits.motor_power, [-1, 1]);
});

test("simapi validate --profile ftc sends the FTC request discriminator", async () => {
  const dir = await mkdtemp(join(tmpdir(), "simapi-ftc-cli-"));
  const csvPath = new URL("../../tests/fixtures/ftc-drive-log.csv", import.meta.url).pathname;
  let posted;
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    posted = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "failed", trials_submitted: 2, trials_excluded: 1, failed: 1, warnings: 0, issues: [], exclusions: [] }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    const cli = new URL("../bin/simapi.js", import.meta.url).pathname;
    const child = spawn(process.execPath, [cli, "validate", csvPath, "--profile", "ftc", "--no-ai", "--json"], {
      env: { ...process.env, SIMAPI_BASE_URL: `http://127.0.0.1:${port}/api`, SIMAPI_CONFIG_DIR: join(dir, "config"), NO_COLOR: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "", stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    const exitCode = await new Promise((resolve) => child.on("close", resolve));
    assert.equal(exitCode, 0, stderr || stdout);
    assert.equal(posted.robotics_profile, "ftc");
    assert.deepEqual(posted.ftc_limits.motor_power, [-1, 1]);
    assert.equal(posted.simulation_type, "robotics");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
