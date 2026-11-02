# SimAPI: Simulations you can trust

Hosted validation for simulation data used in Physical AI and robotics. Check a
run in the browser, from the CLI, or through an SDK. SimAPI is a service to use,
not software you need to host.

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
  robot model or controller configuration so SimAPI can flag samples that leave
  the arm's allowed range.

SimAPI checks data; it does not certify a robot, prove sim-to-real transfer, or
replace engineering review. A clean report means only that the checks in that
run did not find a reported violation.

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

The ranges must use the same units as the input data. SimAPI does not yet parse
URDF, ROS bag, or MCAP files; provide numeric records and limits directly.

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

## Use the hosted service

The same hosted endpoint can be called from a browser, a CI job, or an
application. No local server or deployment is required.

### Browser

Open the [playground](https://simapilander.vercel.app/play) to upload a run and
inspect its validation report.

### CLI

Install the CLI and validate a robotics dataset:

```bash
npm install -g simapi-cli
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

```bash
pip install simapi
```

```python
from simapi import SimAPI

client = SimAPI()
result = client.validate(
    "episode.json",
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

## Current scope

The hosted validator accepts tabular numeric records. Robotics limit checks are
available for recognized scalar signals and caller-provided per-signal ranges;
timestamps are checked for increasing order within each episode. URDF-derived
limits, ROS 2 bag and MCAP ingestion, contact and collision validation, peak
motion reconstruction, and simulator-specific adapters are not implemented yet. Those are the next steps for supporting more
manipulation-arm workflows.

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
