# SimAPI MCP architecture

The MCP server makes the existing robotics engine available as tools in an AI
client. It is a wrapper: validation rules stay in SimAPI's core and recording
conversion stays in the existing integrations.

## Request path

```text
Local MCP client                              Hosted MCP client
      |                                              |
      | stdio                                        | HTTPS through TLS proxy
      v                                              v
+--------------------+                  +--------------------------+
| FastMCP stdio      |                  | ASGI security wrapper    |
| local paths allowed|                  | 1. bearer-token check   |
+---------+----------+                  | 2. per-token rate limit  |
          |                             +------------+-------------+
          |                                          |
          |                             +------------v-------------+
          |                             | FastMCP Streamable HTTP  |
          |                             | uploads; no local paths |
          |                             +------------+-------------+
          +-------------------+----------------------+
                              |
                              v
             +------------------------+------------------------+
             |                                                 |
             v                                                 v
+----------------------------+                    +--------------------------+
| core.robotics_validation   |                    | integrations/            |
| robotics engine + suites   |<-------------------| ROS 2, LeRobot loaders  |
+----------------------------+                    +--------------------------+
```

The arrows show the code path, not an additional validation layer. The MCP
server shapes the engine report into a small tool result with a verdict,
failed checks, excluded rows, and episode summaries.

## Tools and data flow

The tools validate episode rows, validate a CSV by local path, validate a
recording by local path, export clean episodes, return default screening
limits, and explain a check name. The CSV-path and recording-path tools are
stdio-only. Streamable HTTP rejects both kinds of local path; its upload tool
accepts base64 file content and a filename for supported `.parquet`, `.db3`,
`.mcap`, or `.zip` recordings instead. Uploads are content-checked, written to
a temporary directory for decoding, and removed when the tool call completes.
HTTP uploads are limited to 3 MiB so base64 and MCP framing fit within the
SDK's default request body ceiling.

File row limits are enforced as input is read or decoded. CSV reading stops at
the configured cap plus one row, which detects an oversized file without
loading it all or silently truncating it. Recording loaders receive the row
cap while decoding, and reject oversized input before full conversion. An
in-memory episode row list is checked against the same cap before validation.
ZIP recordings are checked before extraction against
`SIMAPI_MCP_MAX_ZIP_ENTRIES` (default 10,000).

```text
rows / CSV / recording
          |
          v
    format adapter (recordings only)
          |
          v
    shared robotics engine
          |
          v
 verdict + checks + excluded rows + episodes
```

Clean export validates each episode independently and keeps or removes it as a
whole. It includes only episodes with a passed verdict; an episode with a
warning or failure is excluded and listed with the checks that caused removal.
The export preserves the caller's original row order, including interleaved
episodes.

## Transport and security

### stdio

Stdio is for a local client launched on the same machine. The client talks to
the MCP process through its input and output streams. Authentication and HTTP
rate limiting are not used in this mode. Both CSV validation by path and
recording validation by local path are available to the user running the
process.

### Streamable HTTP

HTTP mode is for a remote client behind HTTPS. SimAPI refuses to start unless
`SIMAPI_MCP_API_KEYS` contains at least one bearer token. The ASGI wrapper
checks every HTTP request before it reaches the MCP application. It compares
tokens with `hmac.compare_digest`, stores only a SHA-256 token digest for rate
accounting, and returns 401 for missing or invalid credentials.

Each token has a fixed 60-second request window controlled by
`SIMAPI_MCP_RATE_LIMIT` (default 60). Requests past the limit receive 429 and a
`Retry-After` header. The counter is held in memory for one process; it is not a
shared cluster limiter. For remote deployment, bind behind a TLS-terminating
proxy, set the host/origin allowlists, and keep API keys in the deployment's
secret store.

HTTP accepts recording uploads rather than local filesystem paths. The CSV
path and recording path tools reject calls in HTTP mode, so a remote request
cannot make the process open a caller-specified local file. A client can send
episode rows directly or use the recording upload tool for a supported file.
