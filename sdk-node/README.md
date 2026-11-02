# simapi (Node.js SDK + CLI)

Validate simulation results against physical laws from Node.js or the terminal.
Requires Node 18+.

## Install

```bash
npm install simapi-cli          # SDK
npm install -g simapi-cli       # CLI (`simapi` command)
```

## SDK

```ts
import { SimAPI } from "simapi-cli";

const client = new SimAPI(process.env.SIMAPI_API_KEY);

const result = await client.validate(rows, {
  simulationType: "aerodynamics",
  conditions: { velocity: 15.0 },
});

if (result.status === "failed") {
  throw new Error("Simulation rejected");
}

// Or validate a file directly:
const r2 = await client.validateFile("simulation.json", { simulationType: "structural" });
```

Configuration falls back to environment variables:

- `SIMAPI_API_KEY` — your key
- `SIMAPI_BASE_URL` — API base URL (default `https://simapilander.vercel.app/api`)

Errors throw `SimAPIError` with `code`, `status`, and `requestId`.

## CLI

```bash
simapi login                 # paste your key (saved to ~/.simapi/config.json)
simapi init                  # write a sample simulation.json
simapi validate simulation.json
simapi validate run.json --type structural --json
simapi validate run.csv --fail-on warning   # non-zero exit for CI
simapi validate arm.csv --profile arm-profile.json --no-ai --report report.json --fail-on failed
simapi whoami
simapi logout
simapi version
simapi help
```

`SIMAPI_API_KEY` overrides the saved key, which is convenient in CI.

For robotics trajectories, the CLI reads CSV headers and numeric samples
directly. CSV input defaults to the robotics domain. A profile is a JSON file
with the arm's model or controller limits:

```json
{
  "robotics_limits": {
    "joint_1_position": [-1.57, 1.57],
    "joint_1_velocity": [-2.0, 2.0],
    "joint_1_torque": [-70.0, 70.0],
    "joint_1_acceleration": [-5.0, 5.0]
  },
  "conditions": {
    "max_time_step": 0.02,
    "velocity_tolerance": 0.1
  }
}
```

Keep units consistent with the trajectory data. SimAPI does not infer safe
limits from observed samples.

## Build (for contributors)

```bash
npm install
npm run build     # compiles src/ → dist/
```

The CLI (`bin/simapi.js`) is plain Node ESM and runs without a build step.
