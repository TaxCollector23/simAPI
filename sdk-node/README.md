# SimAPI CLI

Check robot recordings, trajectories, and joint limits from a terminal or CI. Validation uses the same hosted engine as the SimAPI playground. The public service requires no account, key, or local server.

## Install and run

```sh
npm install -g simapi-cli
simapi
```

Use Node.js 18 or later. To try the CLI without a global install, run `npx --yes --package simapi-cli simapi`. If npm can't install global packages with your current permissions, use the `npx` form or install Node with a version manager.

```sh
simapi doctor
simapi inspect episode.csv
simapi validate episode.csv
```

Use a CSV or JSON recording from your project. To save default settings for the directory, run `simapi init` and edit the generated `simapi.json`. It creates a new file and keeps any existing settings file intact. Run `simapi --help` for all commands or `simapi validate --help` for validation options.

## Profiles and recordings

```bash
simapi profile import arm.urdf --name arm --output arm-profile.json
simapi profile list
simapi inspect capture.mcap --topic /joint_states --profile arm
simapi profile show arm
simapi import capture.mcap --list-topics
simapi import capture.mcap --topic /joint_states --profile arm --episode pick --output run.json
simapi validate run.json --profile arm --format github --report report.json --fail-on failed
simapi compare baseline.json report.json --json --fail-on regression
simapi repair run.json
simapi repair run.json --apply --output run.repaired.json
simapi watch run.json --profile arm
```

`inspect` reports sample/episode counts, valid durations, signal ranges, and missing values locally. `--summary` prints a compact validation report; CI environments use it automatically. Project `simapi.json` settings for `profile` and `fail_on` are honored unless overridden.

`validate` reads CSV, JSON, ROS 1 bags, and ROS 1/2 MCAP. The default domain is robotics; `--type` selects another domain. Named profiles live under `~/.simapi/profiles`; `--profile` accepts a name or JSON path. `SIMAPI_CONFIG_DIR` selects a different local config directory.

`profile import` reads resolved URDF or JSON. URDF imports declared joint position, velocity, and effort bounds. It leaves acceleration limits and continuous position bounds unset. Prismatic effort is force in N; revolute effort is torque in Nm. URDF notes explain missing bounds. Joint names map consistently to signals in recording imports. Import the profile before importing a recording so prismatic effort is identified correctly.

ROS bag supports uncompressed, BZ2, and LZ4 files. MCAP supports ROS 1 (`ros1msg` / `ros1`), ROS 2 (`ros2msg` / `cdr`), and JSON messages, with BZ2, LZ4, and Zstd chunks. ROS 2 SQLite `.db3` bags and IDL-only schemas must be converted first. Multiple topics require `--topic`. Import rejects over 10,000 samples or 100 MB, rather than truncating data. An import is one episode unless assigned another ID with `--episode`; timestamp resets remain visible to validation.

`--format github` writes up to 50 escaped workflow annotations to stderr. CSV findings include the source line. Other formats identify the episode, sample, and signal in the message. With `--json`, stdout contains only the JSON report.

`compare` checks severity changes, episode counts, exclusions, and configuration. `--fail-on regression` returns 1 for new/worsened checks or a worse verdict. Changed or unknown settings are reported explicitly.

`repair` runs locally without an API call. Preview the plan first. It can remove exact repeated timestamped samples, reorder within an episode, and interpolate at most two missing joint/tool values between valid neighbours. It does not bridge episodes, choose between conflicting timestamps, or infer wrapped angles. `--apply` writes a separate `.repaired.json`/`.repaired.csv`; existing files are never overwritten. Revalidate the repaired copy before use.

`--report` writes the complete validation response, including configuration and per-sample evidence. It replaces a previous report at that path. Use a separate path from the recording and profile. Evidence details are capped at 1,000, with total and truncation fields that describe the full run.

## Reproduce a playground run in CI

Download the run input and profile from the playground report and put them in your repository. The copied command points to those files. `--exact-profile` applies the downloaded check settings and ignores extra settings in a local config or a recording's JSON envelope.

```sh
simapi validate ./simapi-run.json --profile ./simapi-profile.json --exact-profile --no-ai --report ./simapi-report.json --fail-on failed
```

Use `--fail-on failed` to gate on errors or `--fail-on warning` to also gate on warnings. Exit code `1` marks a run that met the chosen threshold, and the JSON report is still written. Exit code `0` means validation completed without crossing the threshold. Exit code `2` means the CLI could not complete validation or write the report. Diagnostics go to stderr.

### GitHub Actions

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
      - run: npm install -g simapi-cli@1.1.4
      - run: simapi validate ./data/run.csv --profile ./arm-profile.json --exact-profile --no-ai --format github --report ./report.json --fail-on failed
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

Profiles, `compareReports`, `repairPreview`, `parseCsv`, and `toCsv` are also exported as local utilities. The browser and CLI use the same helper implementation. Use `npm install simapi-cli` to add the SDK to an application.

## Endpoint and settings

Validation sends the recording to `https://simapilander.vercel.app/api` by default. Inspection, profile import, comparison, and repair run locally. The CLI runs deterministic checks by default. Opt in to AI review and text parsing with `--ai`. That setting can send statistics and selected sample rows to a model provider.

Set `SIMAPI_BASE_URL` to use a different validation service. For a private endpoint that requires credentials, pass `SIMAPI_API_KEY` from your environment or pipe a key to `simapi api-key set --stdin` to store it with the local CLI config. Key displays are masked. The hosted public endpoint needs no credentials.

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
