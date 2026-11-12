# SimAPI: Simulations you can trust

Hosted validation for robotics data, joint trajectories, and Physical AI workflows. Check a
run in the browser, from the CLI, or through an SDK. Use the hosted service, or self-host the Python API, validation engine,
dashboard, and MCP server included in this repository.

[Open the playground](https://simapilander.vercel.app/play) · [Read the docs](https://simapilander.vercel.app/docs) · [View the source](https://github.com/TaxCollector23/simAPI)

## What SimAPI does

SimAPI checks simulation records for values and relationships that are outside
their expected physical ranges. It returns a machine-readable status, the checks
that ran, affected samples, and findings that can be reviewed or used to stop a
pipeline. The goal is to catch bad simulation data before it is used for model
training, evaluation, planning, or control.

SimAPI is focused on two workflows:

- **Physical AI:** review synthetic and simulated data before it enters a
  training or evaluation dataset. Use the report to inspect exclusions and
  decide whether a run is suitable for the next step.
- **Robotics, starting with manipulation arms:** check joint signals, actuator
  outputs, and end-effector measurements. Supply per-signal limits from the
  robotics model or controller configuration so SimAPI can flag samples that leave
  the arm's allowed range.

SimAPI checks data; it does not certify a robot, prove sim-to-real transfer, or
replace engineering review. A clean report means only that the checks in that
run did not find a reported violation.

## Feature bundle deployment map

The Physical-AI bundle adds focused modules around the existing validation
engine. These are the repository destinations for its files:

| Bundle file | Repository destination | Purpose |
| --- | --- | --- |
| `simapi_mcp.py` | `simapi_mcp.py` | Expose robotics validation as MCP tools for local and authenticated hosted clients. |
| `mcp-architecture.md` | `docs/mcp-architecture.md` | Explain the MCP request path and its stdio/HTTP security boundaries. |
| `physical_ai.py` | `core/physical_ai.py` | Add episode labels, stream synchronization, action/state checks, and clean episode export. |
| `ftc_frc.py` | `core/ftc_frc.py` | Validate FTC/FRC power, encoders, battery, heading, and odometry signals. |
| `dashboard_extras.js` | `dashboard/dashboard_extras.js` | Add episode chips, clean CSV export, and MCP setup to the existing static dashboard. |

The engine modules live under `core/`; the browser add-on sits beside the
static dashboard it extends; deployment and contributor guidance stay in the
README and `docs/`.

## Manipulation-arm validation

For robotics runs, SimAPI applies broad plausibility checks to recognized signals
such as joint position, velocity, acceleration and torque; end-effector force,
torque and velocity; position error; manipulability; condition number; and
control response metrics. These broad ranges are screening checks. They are not
the limits for a specific robot.

Pass model-specific ranges with `robotics_limits`. A violation fails the run and
identifies the affected samples. If a configured signal is missing, validation
fails closed because the requested limit could not be checked.

```json
{
  "simulation_type": "robotics",
  "robotics_limits": {
    "joint_1_position": [-1.57, 1.57],
    "joint_1_velocity": [-2.0, 2.0],
    "joint_1_torque": [-70.0, 70.0]
  },
  "data": [
    { "joint_1_position": 0.2, "joint_1_velocity": 0.4, "joint_1_torque": 12.0 },
    { "joint_1_position": 0.3, "joint_1_velocity": 0.5, "joint_1_torque": 14.0 }
  ]
}
```

The ranges must use the same units as the input data. The CLI and playground can import limits from URDF and extract JointState signals from ROS 1 bags and ROS 1/2 MCAP recordings. The API accepts the resulting numeric records.

## Trajectory checks

The manipulation engine also checks motion between samples within each episode:

- **Velocity implied by position:** compare `Δposition / Δtime` with a configured
  limit for the corresponding joint velocity.
- **Acceleration implied by velocity:** compare `Δvelocity / Δtime` with a
  configured joint acceleration range.
- **Sampling gaps:** set `conditions.max_time_step` in seconds to catch intervals
  longer than the sampling budget.
- **State agreement:** opt into `conditions.velocity_tolerance` or
  `conditions.acceleration_tolerance` to compare finite differences with the
  average recorded velocity or acceleration at the interval endpoints.
- **Coverage:** missing time, matching signals, or valid intervals are reported
  as checks that could not be evaluated, rather than a silent pass.

Timestamps must be numeric seconds. Positions must be unwrapped and use the
same units as the limits; tolerances are absolute values in the corresponding
velocity or acceleration units. Finite differences estimate interval-average
motion, not peak velocity or acceleration. No joint-wrap convention is inferred.

Reports include `robotics_checks` and `robotics_summary`: the motion engine
version, episode IDs, sample counts, duration when available, flagged samples,
and assumptions. The playground can export a JSON report or complete unflagged
episodes as CSV. It keeps episode samples together to avoid introducing gaps
by removing individual rows.

A reusable CLI or playground profile can contain limits and check settings:

```json
{
  "robotics_limits": {
    "joint_1_velocity": [-2, 2],
    "joint_1_acceleration": [-5, 5]
  },
  "conditions": {
    "max_time_step": 0.02,
    "velocity_tolerance": 0.1,
    "acceleration_tolerance": 0.5
  }
}
```

These are example values. Use the limits, sampling requirements, and units for
your arm. `simapi validate episode.csv --profile arm-profile.json --no-ai
--report report.json --fail-on failed` writes a report and returns a failure
exit code if a blocking check fails, including when `--json` output is used.

## Robotics workflow tools

- **URDF profiles:** import revolute, continuous, and prismatic joint limits. Original joint names map to stable signal names such as `joint_shoulder_position`. Prismatic effort uses `_force` in newtons; revolute effort uses `_torque` in newton metres. No acceleration limit or continuous position bound is invented.
- **Recording ingestion:** read ROS 1 `.bag` and ROS 1/2 `.mcap` JointState messages, including BZ2/LZ4 ROS bags and BZ2/LZ4/Zstd MCAP chunks. MCAP supports `ros1msg` + ROS 1 serialization, `ros2msg` + CDR, and JSON messages. ROS 2 `.db3` bags and IDL-only schemas require conversion first. Select a topic when multiple channels exist.
- **Reusable profiles:** save named profiles in the CLI or browser. Download the same JSON profile for the CLI, SDK, or API. Browser storage is local to that browser; profiles are not synchronized to an account.
- **Trajectory comparison:** view position, velocity, acceleration, and effort on aligned plots, each in its own units. Overlay another episode or CSV/JSON run. Missing samples remain gaps; comparison does not resample or estimate missing values.
- **Report comparison:** inspect new, resolved, and worsened checks and changed episode counts. Reports include the settings used so a configuration change is visible. Older reports without settings show that comparison coverage as unknown.
- **CI output:** emit GitHub Actions annotations with episode and sample information. CSV annotations identify the source line. JSON annotations identify the sample in the message. Exit gates also apply to JSON output.
- **Repair previews:** propose exact duplicate removal when timestamps agree, ordering within an episode, and interpolation of at most two missing joint/tool samples bracketed by valid timestamps and values. Conflicting timestamps and unbounded gaps need manual review. Repairs write a new file and refuse to overwrite an existing file.

```bash
simapi profile import arm.urdf --name arm --output arm-profile.json
simapi import capture.mcap --list-topics
simapi import capture.mcap --topic /joint_states --profile arm --output run.json
simapi validate run.json --profile arm --no-ai --format github --report report.json --fail-on failed
simapi compare baseline.json report.json --fail-on regression
simapi repair run.json
simapi repair run.json --apply --output run.repaired.json
```

URDF is imported after Xacro expansion. JointState arrays use the exact joint name to create the profile’s canonical signal names; names that collide after normalization are rejected. Missing optional velocity or effort arrays stay absent. Joint header timestamps are preferred, with recording timestamps as a fallback. Numeric times are seconds. Import assigns one episode by default (`--episode` changes its ID); time resets are reported by validation rather than silently split into new episodes.

A request accepts up to 10,000 samples. Hosted recording uploads accept files up to 100 MB, expand ZIPs up to the same byte limit and 10,000 archive entries, and refuse recordings over the sample limit during conversion instead of truncating them. Export shorter captures or split complete episodes before submission.

Reports add `validation_context` and `robotics_evidence`: episode ID, zero-based sample index, timestamp, signal, observed value, expected range, and check detail. Evidence details are capped at 1,000 entries with explicit `robotics_evidence_total` and `robotics_evidence_truncated` fields; verdicts and episode counts cover the full dataset.

The playground runs deterministic robotics checks with AI review disabled. Recorded data can support a policy review, but SimAPI does not execute policies, simulate collisions, or certify hardware.

### Local ROS 2 and LeRobot adapters

The Python repository includes optional adapters for ROS 2 rosbag2 `.db3`
recordings and LeRobot parquet datasets. Install their dependencies with
`pip install -e '.[robotics-data]'`. Both adapters preserve episode boundaries
and send the resulting records through the same deterministic robotics engine
used by the API. ROS effort remains measured effort; it is not relabeled as a
commanded action. LeRobot action vectors remain `action_N` signals.

```bash
python -m integrations.ros2_loader recording.db3 --out ros2-rows.csv \
  --report ros2-report.json
python -m integrations.lerobot_loader ./dataset --max-episodes 20 \
  --out robot-rows.csv --report lerobot-report.json
```

The local report endpoint also exports JUnit XML, SARIF, or a Markdown training
data card from the standard validation request:

```bash
curl -X POST 'http://localhost:8000/v1/validate/report?format=junit' \
  -H 'Content-Type: application/json' \
  -d '{"simulation_type":"robotics","run_ai":false,"data":[{"episode_id":"ep1","t":0,"joint_1_position":0.1},{"episode_id":"ep1","t":0.01,"joint_1_position":0.11}]}'
```

These adapters run in the repository's Python environment. The hosted validator
continues to accept tabular numeric records; send the adapter's converted rows
to the API when validating through the hosted service.

## Use the hosted service

The same hosted endpoint can be called from a browser, a CI job, or an
application. No local server or deployment is required.

### Browser

Open the [playground](https://simapilander.vercel.app/play) to upload a run and
inspect its validation report.

### CLI

Install the CLI and validate a robotics dataset:

```bash
# Build the current source CLI (new robotics commands are in sdk-node).
git clone https://github.com/TaxCollector23/simAPI.git
cd simAPI/sdk-node
npm ci
npm run build
npm install -g .
simapi validate episode.json --type robotics --fail-on warning
```

The CLI reads CSV trajectories directly. CSV input defaults to robotics; add a
JSON profile to reuse limits for your arm:

```bash
simapi validate episode.csv --profile arm-profile.json --fail-on warning
```

```json
{
  "robotics_limits": {
    "joint_1_position": [-1.57, 1.57],
    "joint_1_velocity": [-2.0, 2.0],
    "joint_1_torque": [-70.0, 70.0]
  }
}
```

The CSV needs a header row. Numeric cells are sent as numbers; text fields such
as `episode_id` are preserved. Use the same units as the robot model or
controller values in the profile. The CLI uses the hosted SimAPI endpoint by
default. Set `SIMAPI_BASE_URL` only when you have been given another endpoint.

### Python SDK

The published `simapi` package in `python-pkg/` is the canonical Python SDK.

```bash
pip install simapi
```

```python
from simapi import SimAPI

client = SimAPI()  # SIMAPI_BASE_URL can point to a local server.
result = client.validate(
    [{"joint_1_position": 0.2, "joint_1_velocity": 0.4, "joint_1_torque": 12.0},
     {"joint_1_position": 0.3, "joint_1_velocity": 0.5, "joint_1_torque": 14.0}],
    simulation_type="robotics",
    robotics_limits={
        "joint_1_position": (-1.57, 1.57),
        "joint_1_velocity": (-2.0, 2.0),
        "joint_1_torque": (-70.0, 70.0),
    },
)

print(result["status"], result["training_ready"])
for issue in result["issues"]:
    print(issue["human_name"], issue["detail"])
```

### REST API and Node.js SDK

```bash
curl -X POST https://simapilander.vercel.app/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{
    "simulation_type": "robotics",
    "robotics_limits": {"joint_1_position": [-1.57, 1.57]},
    "data": [
      {"joint_1_position": 0.2},
      {"joint_1_position": 0.3}
    ]
  }'
```

The response includes `status`, `training_ready`, `issues`, `exclusions`, and
per-signal statistics. The Node.js SDK accepts the same limits as
`roboticsLimits` in its validation options. See the [API quickstart](https://simapilander.vercel.app/docs/quickstart)
and [CLI guide](https://simapilander.vercel.app/docs/sdks/cli).

## MCP server

`simapi_mcp.py` exposes the robotics checks to MCP clients. Install the
optional SDK dependency with `pip install "mcp<2"`. Local stdio mode keeps
using the caller's local files:

```bash
SIMAPI_PATH=/path/to/simAPI python simapi_mcp.py
```

Streamable HTTP mode requires at least one bearer token before it starts.
Keep keys in the process environment or a secrets manager; do not commit them
to the repository. Multiple keys may be comma separated.

```bash
SIMAPI_MCP_TRANSPORT=streamable-http \
SIMAPI_MCP_API_KEYS="$SIMAPI_MCP_KEY" \
SIMAPI_MCP_RATE_LIMIT=60 \
SIMAPI_MCP_MAX_ROWS=10000 \
SIMAPI_MCP_HOST=0.0.0.0 \
SIMAPI_MCP_ALLOWED_HOSTS="mcp.example.com:*" \
SIMAPI_PATH=/path/to/simAPI \
python simapi_mcp.py
```

`GET /healthz` returns a fixed liveness status without authentication; MCP
requests need `Authorization: Bearer <token>`. Each token gets a fixed
60-second request window; requests over `SIMAPI_MCP_RATE_LIMIT` receive
HTTP 429 and a `Retry-After` header. Rate counters are held in process memory,
so run one server process per deployment unless you add a shared limiter.
The server binds to `127.0.0.1` by default; set `SIMAPI_MCP_HOST=0.0.0.0`
behind a TLS terminating reverse proxy when remote clients need to connect.
Set `SIMAPI_MCP_ALLOWED_HOSTS` to the public hostnames and ports served by the
proxy. Browser based MCP clients can also set `SIMAPI_MCP_ALLOWED_ORIGINS`;
the SDK keeps its local-only defaults when these allowlists are unset.
The episode, CSV, clean-episode, and recording tools reject more than
`SIMAPI_MCP_MAX_ROWS` rows (default 10,000) instead of truncating them. The
recording cap is passed into the LeRobot and ROS readers so they can reject
oversized inputs before retaining a larger converted frame. ZIP uploads also
reject more than `SIMAPI_MCP_MAX_ZIP_ENTRIES` entries (default 10,000).

All path-based tools, including `validate_robotics_csv` and
`validate_recording`, are disabled in HTTP mode. Send row data to
`validate_robotics_episode`, or use `validate_recording_upload` with base64
file content and a filename. Accepted `.parquet`, `.db3`, `.mcap`, and `.zip`
files are written to a private temporary directory and removed after
validation. The HTTP upload is capped at 3 MiB to fit the MCP SDK's default
request-body limit. Stdio mode remains local and does not require a key.

## Current scope

The hosted validator accepts tabular numeric records. Robotics limit checks are
available for recognized scalar signals and caller-provided per-signal ranges;
timestamps are checked for increasing order within each episode. Local Python
adapters handle ROS 2 `.db3` and LeRobot parquet ingestion. Direct hosted upload
for those formats, URDF-derived limit import, contact and collision validation,
and peak-motion reconstruction remain future work.

## Contributing

The hosted service is the normal way to use SimAPI. This repository contains the
service and validation engine for contributors working on it:

```bash
git clone https://github.com/TaxCollector23/simAPI.git
cd simAPI
make dev
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for repository development guidance.

## License

MIT — see [LICENSE](LICENSE).
