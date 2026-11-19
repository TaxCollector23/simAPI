# SimAPI Python SDK and local CLI

Python 3.9+ client and local validation tools. The Python CLI runs its bundled
engine on your machine. To use the hosted validator shared with the playground,
install the Node CLI with `npm install -g simapi-cli`.

## Install

```bash
pip install simapi
```

## Python SDK

The public hosted service does not require a key:

```python
from simapi import SimAPI

client = SimAPI()
result = client.validate("simulation.json", simulation_type="aerodynamics")
print(result["status"], result["all_checks"])
```

Pass `api_key=` or set `SIMAPI_API_KEY` only when using a private service that
requires authentication. `SIMAPI_BASE_URL` selects another endpoint.

## Local CLI

The Python package also provides a standalone `simapi` command. It does not
have a browser login flow; its validation runs locally without an account or
API key.

```bash
simapi
simapi init
simapi validate simulation.csv --domain robotics
simapi ci simulation.csv --domain robotics --fail-on any
simapi doctor
```

Use `simapi --help` for all commands and options. `--report` writes a Markdown
report, `--export` writes clean rows, and `--sarif` emits GitHub code-scanning
results.
