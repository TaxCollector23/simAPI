#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${PORT:?Render must provide PORT}"
: "${RENDER_EXTERNAL_HOSTNAME:?Render must provide RENDER_EXTERNAL_HOSTNAME}"

export SIMAPI_PATH="${SIMAPI_PATH:-$repo_root}"
export SIMAPI_MCP_TRANSPORT=streamable-http
export SIMAPI_MCP_HOST=0.0.0.0
export SIMAPI_MCP_PORT="$PORT"
if [ -z "${SIMAPI_MCP_ALLOWED_HOSTS:-}" ]; then
    export SIMAPI_MCP_ALLOWED_HOSTS="$RENDER_EXTERNAL_HOSTNAME,$RENDER_EXTERNAL_HOSTNAME:*"
fi

exec python "$repo_root/simapi_mcp.py"
