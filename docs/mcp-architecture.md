# SimAPI MCP architecture

The MCP server makes the existing robotics engine available as tools in an AI
client. It is a wrapper: validation rules stay in SimAPI's core and recording
conversion stays in the existing integrations.

## Request path

```text
Local client                         Hosted client
     |                                     |
     | MCP over stdio                     | HTTPS through a TLS proxy
     v                                     v
+------------------+            +--------------------------+
| FastMCP tools    |            | ASGI security wrapper    |
| (no HTTP auth)   |            | 1. bearer-token check   |
+--------+---------+            | 2. per-token rate limit  |
         |                      +------------+-------------+
         +----------------------+             |
                                v             v
                         +--------------------------+
                         | FastMCP Streamable HTTP  |
                         +------------+-------------+
                                      |
                                      v
             +------------------------+------------------------+
             |                                                 |
             v                                                 v
+----------------------------+                    +--------------------------+
| core.robotics_validation   |                    | integrations/            |
| robotics engine + suites   |<-------------------| ros2_loader, lerobot     |
+----------------------------+                    +--------------------------+
```

The arrows show the code path, not an additional validation layer. The MCP
server shapes the engine report into a small tool result with a verdict,
failed checks, excluded rows, and episode summaries.

## Tools and data flow

The six local tools validate a list of episode rows, validate a CSV, validate a
recording by path, export whole clean episodes, return default screening
limits, and explain a check name. The optional hosted upload tool accepts
base64 file content and a filename; HTTP mode disables path-based recording
access so a remote caller cannot ask the process to open arbitrary local files.

CSV rows are read up to the configured cap plus one row so over-limit files are
rejected instead of silently truncated. Recording uploads are content-checked,
written to a private temporary directory, decoded through the existing
integration loaders, and removed when the tool call completes. HTTP uploads are
limited to 3 MiB so base64 and MCP framing fit within the SDK's default request
body ceiling.

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
whole. It preserves the caller's original row order, including interleaved
episodes, and lists removed episodes with the checks that caused removal.

## Transport and security

### stdio

Stdio is for a local client launched on the same machine. The client talks to
the MCP process through its input and output streams. Authentication and HTTP
rate limiting are not used in this mode; local file paths remain available to
the user running the process.

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

HTTP mode accepts uploaded recordings rather than local filesystem paths.
Stdio mode's path-based tool remains available and unchanged.
