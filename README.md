<div align="center">

# SimAPI: Simulations you can trust

Simulation CI/CD for Physical AI and robotics. Check simulation data against
physical laws, catch bad runs, and gate what reaches training or autonomy.
Use SimAPI from the web dashboard, CLI, or SDK.

[![CI](https://github.com/TaxCollector23/simAPI/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-black)](LICENSE)

[Open the SimAPI dashboard](https://simapilander.vercel.app/dashboard) · [Read the docs](https://simapilander.vercel.app/docs) · [Use the CLI](https://simapilander.vercel.app/docs/sdks/cli)

</div>

---

## Why SimAPI

Physical AI and robotics depend on simulated worlds: synthetic sensor data,
scenarios, trajectories, and solver outputs. A plausible looking run can still
break physical constraints, contain unit mistakes, or carry bad values into a
training set or autonomy stack.

SimAPI is a hosted validation service for that gap. Send it simulation data and
get a structured verdict you can inspect in the dashboard or use as a CI gate.
The deterministic checks cover physical plausibility, conservation, dimensions,
relationships between variables, statistical consistency, and outliers. An
optional AI review adds a second pass over the result.

### Built for two workflows

- **Physical AI:** validate synthetic and simulated data before using it to train
  or evaluate models. Check the `training_ready` result and inspect warnings.
- **Robotics:** validate simulated sensor, motion, and environment outputs before
  they enter autonomy and planning pipelines. Fail a run when its verdict does
  not meet your configured threshold.

## Use SimAPI

SimAPI runs as a hosted service. You do not need to deploy or maintain the API.
Choose the interface that fits your workflow:

| Interface | Use it for |
| --- | --- |
| [Web dashboard](https://simapilander.vercel.app/dashboard) | Get an API key, try validation, and review results. |
| [CLI](https://simapilander.vercel.app/docs/sdks/cli) | Validate files locally or add a pass/fail check to CI. |
| [SDK and REST API](https://simapilander.vercel.app/docs) | Call validation from Python, Node.js, or your own application. |

### Validate from CI with the CLI

Install the CLI, authenticate once, then add a validation step to your workflow:

```bash
npm install -g simapi-cli
simapi login
simapi validate simulation.json --type robotics --fail-on warning
```

In CI, provide `SIMAPI_API_KEY` as a secret instead of using interactive login.
`SIMAPI_BASE_URL` defaults to the hosted SimAPI API. See the [CLI guide](https://simapilander.vercel.app/docs/sdks/cli)
for install options and command details.

### Call the API from an application

```bash
curl -X POST https://sim-api.vercel.app/api/v1/validate \
  -H "X-API-Key: $SIMAPI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "simulation_type": "robotics",
    "data": [
      { "condition_number": 12.4, "workspace_volume": 0.84, "end_effector_velocity": 0.42 },
      { "condition_number": 13.1, "workspace_volume": 0.82, "end_effector_velocity": 0.39 }
    ]
  }'
```

The response includes a `passed`, `warning`, or `failed` status, the checks and
issues behind it, and whether the data is marked `training_ready`. See the
[API quickstart](https://simapilander.vercel.app/docs/quickstart) for Python and
Node.js examples.

## What gets checked

- Physical plausibility and domain-specific bounds
- Conservation laws and dimensional consistency
- Cross-variable and statistical relationships
- Outliers and anomalous distributions
- Optional AI review for a second opinion

Validation returns a structured result that you can inspect or use to continue,
warn, or fail a pipeline. Treat the verdict as a quality signal for simulation
data; it does not certify a physical system or replace engineering review.

## For contributors

The hosted service is the normal way to use SimAPI. To work on the service itself,
clone the repository and run the local development environment:

```bash
git clone https://github.com/TaxCollector23/simAPI.git
cd simAPI
make dev
make test
python launch.py  # local API at http://localhost:8000
```

The repository includes the API, validation engine, SDKs, CLI, dashboard, docs,
and tests. See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidance.

## License

MIT — see [LICENSE](LICENSE).
