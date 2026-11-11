# Contributing to SimAPI

Thanks for your interest in improving SimAPI. This guide gets you productive fast.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
make dev            # installs deps + pre-commit hooks
cp .env.example .env
make test           # should be green
make run            # starts API + dashboard
```

## Project layout

```
api/     FastAPI server, config, security, observability, error contract
core/    Validation engine: ingestion, physics rules, AI reasoning layer
integrations/  Optional robotics data adapters (ROS 2 rosbag2, LeRobot parquet)
sdk/     Python client SDK
tests/   Pytest suite (unit + API contract)
dashboard/  Static demo dashboard
```

## Ground rules

- **No secrets in code.** Configuration comes from the environment (`api/config.py`).
- **Keep the public response schema backward compatible.** If a break is truly
  necessary, document the rationale in the PR and `CHANGELOG.md`.
- **Every new physics check** goes in a layer method on `PhysicsValidator` and
  should emit a `PhysicsCheck` via the `_c`/`_w` helpers with a category.
- **Add tests** for new endpoints (contract test in `tests/test_api.py`) and new
  logic (unit test).

## Before opening a PR

```bash
make format lint typecheck test
```

CI must be green. PRs are squash-merged; write a clear, imperative title.

## Adding a new simulation domain

1. Add the enum value to `SimulationType`.
2. Add bounds to `BOUNDS` and a `_domain_<name>` layer method.
3. Register the method in the `layers` list in `PhysicsValidator.validate`.
4. Add column aliases to `COLUMN_ALIASES` in `core/ingestion.py`.
5. Add a contract test.

## Extending the robotics validation engine

Robotics validation runs through an ordered collection of check suites. The API
holds one `RoboticsValidationEngine`; each run passes through its suites and
then receives the shared episode summary and evidence report. Existing suites
live in `core/robotics_engine.py`, while interval motion checks are implemented
in `core/robotics_trajectory.py`.

Add a suite by implementing `run(context)` and returning a
`RoboticsSuiteResult` with checks and zero-based excluded sample indices. The
context provides the input frame, source records, configured and resolved
limits, and conditions. Append the suite to `ROBOTICS_ENGINE.suites` in
`api/server.py` so the existing defaults continue to run. Keep checks
deterministic and include the signal, limits, or assumptions needed to explain
each finding. The compatibility function
`check_robotics_limits` remains available to Python callers and accepts an
injected engine when custom suites are needed. The API response schema and
standard check and evidence assembly remain centralized in the engine.

The `integrations/` modules convert external robot datasets into this engine's
episode-aware table format. Keep optional file-format dependencies out of the
core validation path; install them with `pip install -e '.[robotics-data]'`.
CI exports are generated from the public validation response by
`core/report_export.py`, while `core/training_data_card.py` builds the
deterministic Markdown provenance report.
