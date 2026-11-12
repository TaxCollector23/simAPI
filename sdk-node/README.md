# SimAPI: Simulations you can trust

Node.js SDK and CLI for hosted robotics validation. Check trajectories, joint limits, timing, and training data from your terminal or application.

## Install the current source

```bash
git clone https://github.com/TaxCollector23/simAPI.git
cd simAPI/sdk-node
npm ci
npm run build
npm install -g .
```

The source package is version 1.1.3. A source update does not publish a new npm release. Check the npm version before relying on its commands.

## CLI

```bash
simapi init
simapi profile import arm.urdf --name arm --output arm-profile.json
simapi profile list
simapi inspect capture.mcap --topic /joint_states --profile arm
simapi profile show arm
simapi import capture.mcap --list-topics
simapi import capture.mcap --topic /joint_states --profile arm --episode pick --output run.json
simapi validate run.json --profile arm --no-ai --format github --report report.json --fail-on failed
simapi compare baseline.json report.json --json --fail-on regression
simapi repair run.json
simapi repair run.json --apply --output run.repaired.json
simapi watch run.json --profile arm --no-ai
```

`inspect` reports sample/episode counts, valid durations, signal ranges, and missing values locally. `--summary` prints a compact validation report; CI environments use it automatically. Project `simapi.json` settings for `profile` and `fail_on` are honored unless overridden.

`validate` reads CSV, JSON, ROS 1 bags, and ROS 1/2 MCAP. The default domain is robotics; `--type` selects another domain. Named profiles live under `~/.simapi/profiles`; `--profile` accepts a name or JSON path. `SIMAPI_CONFIG_DIR` selects a different local config directory.

`profile import` reads resolved URDF or JSON. URDF imports declared joint position, velocity, and effort bounds. It leaves acceleration limits and continuous position bounds unset. Prismatic effort is force in N; revolute effort is torque in Nm. URDF notes explain missing bounds. Joint names map consistently to signals in recording imports. Import the profile before importing a recording so prismatic effort is identified correctly.

ROS bag supports uncompressed, BZ2, and LZ4 files. MCAP supports ROS 1 (`ros1msg` / `ros1`), ROS 2 (`ros2msg` / `cdr`), and JSON messages, with BZ2, LZ4, and Zstd chunks. ROS 2 SQLite `.db3` bags and IDL-only schemas must be converted first. Multiple topics require `--topic`. Import rejects over 10,000 samples or 100 MB, rather than truncating data. An import is one episode unless assigned another ID with `--episode`; timestamp resets remain visible to validation.

`--format github` writes up to 50 escaped workflow annotations to stderr, while `--json` remains clean JSON on stdout. CSV findings annotate a source line. Other formats identify the episode, sample, and signal in the message. `--fail-on failed` or `--fail-on warning` sets exit code 1 at that threshold. Unexpected errors also return nonzero.

`compare` checks severity changes, episode counts, exclusions, and configuration. `--fail-on regression` returns 1 for new/worsened checks or a worse verdict. Changed or unknown settings are reported explicitly.

`repair` runs locally without an API call. Preview the plan first. It can remove exact repeated timestamped samples, reorder within an episode, and interpolate at most two missing joint/tool values between valid neighbours. It does not bridge episodes, choose between conflicting timestamps, or infer wrapped angles. `--apply` writes a separate `.repaired.json`/`.repaired.csv`; existing files are never overwritten. Revalidate the repaired copy before use.

`--report` writes the complete validation response, including configuration and per-sample evidence. Evidence details are capped at 1,000 with explicit total/truncated fields; check and episode totals cover the entire run.

## GitHub Actions

This workflow installs the source CLI in a separate directory. Pin `ref` to the source revision you have reviewed.

```yaml
name: Robotics checks
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - uses: actions/checkout@v4
        with:
          repository: TaxCollector23/simAPI
          ref: main
          path: .simapi-tool
      - run: npm ci --prefix .simapi-tool/sdk-node
      - run: node .simapi-tool/sdk-node/bin/simapi.js validate data/run.csv --profile arm-profile.json --no-ai --format github --report report.json --fail-on failed
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: robotics-report
          path: report.json
```

## SDK

```ts
import { SimAPI, profileFromUrdf, readRecording } from 'simapi-cli';
import { readFile } from 'node:fs/promises';

const client = new SimAPI();
const profile = profileFromUrdf(await readFile('arm.urdf', 'utf8'));
const recording = await readRecording(new Uint8Array(await readFile('capture.mcap')), 'capture.mcap', {
  topic: '/joint_states', profile,
});
const report = await client.validate(recording.rows, {
  simulationType: 'robotics', roboticsLimits: profile.robotics_limits,
  conditions: profile.conditions, runAi: false,
});
```

Profiles, `compareReports`, `repairPreview`, `parseCsv`, and `toCsv` are also exported as local utilities. The browser and CLI use the same helper implementation.

The hosted API defaults to `https://simapilander.vercel.app/api`. Use `SIMAPI_BASE_URL` for another service. No local server or account is required by the public endpoint. Optional AI review can transmit statistics and selected sample rows to a model provider; `--no-ai` disables it.

A passing report describes the checks that ran. It does not certify hardware, policies, or safe execution.

## FTC / FRC telemetry

Use the built-in school robotics profile for common motor, encoder, battery,
heading, and odometry checks:

```sh
simapi validate drive-log.csv --profile ftc
# frc is an alias for ftc
simapi validate drive-log.csv --profile frc
```

The defaults check motor power in `[-1, 1]`, battery voltage in a warning
band, encoder velocity agreement, battery sag under load, wrapped gyro
heading, and odometry speed. The profile accepts common headers such as
`leftMotorPower`, `leftEncoderTicks`, `batteryVoltage`, `heading`, and
`odometry_x`/`odometry_y`. A custom JSON profile can override any default:

```json
{
  "schema_version": 1,
  "name": "My FTC robot",
  "robotics_profile": "ftc",
  "ftc_limits": {
    "motor_power": [-0.9, 0.9],
    "heading_jump_deg": 75
  },
  "robotics_limits": {},
  "conditions": {}
}
```

The CLI sends FTC requests with `robotics_profile: "ftc"` and `ftc_limits`
alongside the standard robotics rows and conditions. FTC limits remain separate
from arm joint limits; selecting `ftc` does not change the arm profile.
