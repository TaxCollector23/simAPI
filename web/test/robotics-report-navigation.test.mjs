import test from "node:test";
import assert from "node:assert/strict";
import {
  ciValidationCommand,
  findingUnits,
  findingWindow,
  reportRowKeys,
} from "../lib/robotics-report-navigation.ts";

test("CI command uses relative snapshot paths and preserves the selected exit gate", () => {
  const command = "simapi validate ./simapi-run.json --profile ./simapi-profile.json --exact-profile --no-ai --report ./simapi-report.json --fail-on";
  assert.equal(ciValidationCommand("failed"), command + " failed");
  assert.equal(ciValidationCommand("warning"), command + " warning");
});

test("original row columns follow the report's chosen time and episode aliases", () => {
  const rows = [{ Timestamp: 123, "T": 0.1, "Match": "red", episode_id: "other" }];
  assert.deepEqual(reportRowKeys(rows, Object.keys(rows[0]), { time_column: "t", episode_column: "match" }), {
    time: "T",
    group: "Match",
  });
});

test("a flagged sample gets a neighborhood without the entire episode", () => {
  const window = findingWindow([0, 1, 2, null, 4, 5, 6, 7, 8, 9, 10], 6, {
    check: "robotics_limit:joint_1_position",
    time: 6,
  });
  assert.equal(window.time, 6);
  assert.equal(window.start, 6);
  assert.equal(window.end, 6);
  assert.ok(window.left < 4 && window.left > 0);
  assert.ok(window.right > 9 && window.right < 10);
});

test("interval findings include the prior timestamp or the explicit interval", () => {
  const times = [0, 0.1, 0.2, 2, 2.1];
  const interval = findingWindow(times, 3, { check: "robotics_sample_gaps", time: 2 });
  assert.equal(interval.start, 0.2);
  assert.equal(interval.end, 2);
  assert.ok(interval.left < interval.start && interval.right > interval.end);
  const explicit = findingWindow(times, 3, {
    check: "ftc_frc:encoder_velocity", time: 2, interval_start: 0.1,
  });
  assert.equal(explicit.start, 0.1);
});

test("an invalid timestamp has no plot window", () => {
  assert.equal(findingWindow([1, null, 3], 1, { check: "robotics_time_order", time: null }), null);
});

test("focused plots convert raw series to authoritative evidence units", () => {
  assert.deepEqual(
    findingUnits({ signal: "joint_1_position", check: "robotics_limit:joint_1_position" },
      { "Joint 1 position": "deg" }, { joint_1_position: "deg->rad" }),
    { unit: "rad", factor: Math.PI / 180 },
  );
  assert.deepEqual(
    findingUnits({ signal: "timestamp", check: "robotics_sample_gaps" }, {}, {}),
    { unit: "s", factor: 1 },
  );
});
