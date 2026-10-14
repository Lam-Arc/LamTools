# Core API access boundary

The internal Core API is local by default. Browser Origin filtering prevents
cross-site requests; it is not authentication. `app/api_access.py` separately
enforces access before routing HTTP or accepting WebSockets.

| Mode | Listener | Access |
| --- | --- | --- |
| Desktop sidecar | Loopback only | Local socket peers; Rust gateway authenticates remote clients before bridging |
| CLI/ASGI default | CLI defaults to `127.0.0.1` | Numeric loopback peers only; other or unknown peers rejected |
| Explicit LAN | Numeric address chosen by operator | Bearer authentication for **every** caller, including loopback/proxy connections |

## Optional direct LAN service

From `core/`, set a strong random server credential in the process environment;
do not put it in command arguments, source control, URLs, or logs:

```powershell
$env:LAMTOOLS_CORE_API_TOKEN = py -3.14 -c 'import secrets; print(secrets.token_urlsafe(32))'
py -3.14 -m lamtools_core.cli serve --host 192.168.1.10 --allow-lan --ssl-certfile server-cert.pem --ssl-keyfile server-key.pem
```

Use the actual LAN address and a certificate clients trust. TLS is optional at
the CLI, but plaintext HTTP/WS exposes bearer credentials to network observers.
Use HTTPS/WSS or an encrypted VPN. Both certificate flags must be supplied
together. The token must contain at least 32 printable ASCII characters without
whitespace; minimum length does not establish entropy. Restart to rotate it.

HTTP and WebSocket clients send `Authorization: Bearer <credential>`. Existing
Core CLI clients support `LAMTOOLS_CORE_TOKEN` and `--token`; prefer the client
environment variable to avoid exposing secrets in process arguments:

```powershell
$env:LAMTOOLS_CORE_API_URL = 'https://192.168.1.10:5172'
# Set LAMTOOLS_CORE_TOKEN privately to the same credential as the server.
py -3.14 -m lamtools_core.cli goal ls
```

The ordinary desktop/mobile UI continues to use the authenticated Rust gateway.
Direct bearer LAN mode supports HTTP and WebSocket clients capable of setting
Authorization headers; no browser login/cookie flow was added.

For the exported `lamtools_core.app.http_agent_server:app`, explicitly set
`LAMTOOLS_CORE_ALLOW_LAN=1` and `LAMTOOLS_CORE_API_TOKEN` before importing it.
Without that configuration, directly binding Uvicorn to a public address does
not make remote peers trusted. CLI and packaged launchers disable Uvicorn proxy
header processing. External ASGI launchers must also disable proxy headers
(`uvicorn ... --no-proxy-headers`) so socket trust is not rewritten. Custom
embedders must retain the middleware supplied by `create_app`.

## Coverage and trust limitations

The access middleware covers REST reads/writes, health, OpenAPI/docs, member and
plugin routes, static assets, SPA fallback, and all WebSocket routes. There is no
health, preflight, query-token, cookie, Origin or forwarded-header auth exemption.
Unauthorized HTTP requests return 401 in LAN mode (403 in local-only mode).
WebSockets close before acceptance with policy violation 1008; on a real HTTP
upgrade Uvicorn returns 403. Browser Origin restrictions still apply after auth.

Desktop dev children discard standalone LAN credentials/configuration; packaged
children also pin `LAMCORE_HOST=127.0.0.1`. The packaged backend independently
rejects non-loopback `LAMCORE_HOST` values. Normal gateway bridges connect over
loopback and need no additional Core bearer token.

Local-only mode trusts programs running on the same machine. An independently
configured unauthenticated local reverse proxy, TCP forwarder or tunnel can
extend that trust to outsiders; do not forward the internal listener. Expose an
explicit authenticated LAN listener or use the existing gateway instead.
LAN bearer credentials grant full Core authority, not per-user authorization;
protect them as administrative credentials and constrain exposure by firewall.

Focused regressions are in `core/tests/test_core_api_access.py`: remote and
spoofed peers, HTTP/WS auth, all route classes, real-socket Core CLI compatibility,
startup refusal, TLS forwarding, and packaged local isolation.
