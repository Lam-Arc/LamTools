"""Local security helpers for the Core HTTP/WS surface.

LamTools' backend binds to a loopback port and is reachable from the browser.
A malicious web page could otherwise drive the local agent through cross-site
requests (CSRF / DNS-rebinding style).  We cannot rely on a token alone for
non-browser clients (CLI, member processes), so the baseline defence is:

* every browser-style request (one carrying an ``Origin`` header) must come
  from an allowed local origin (dev vite servers, Tauri WebView);
* requests without an ``Origin`` header (CLI / Python clients / same-origin
  static assets) are trusted as local callers.

``LAMTOOLS_CORE_ALLOWED_ORIGINS`` (comma separated) can extend the list for
member products that run their own frontend on a different port.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

_DEFAULT_ORIGINS = frozenset({
    # vite dev servers (the ui proxy rewrites the browser origin to the
    # backend port, so both ports must be listed)
    "http://localhost:5172",
    "http://127.0.0.1:5172",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # Tauri WebView (v1 / v2)
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
})

_ALLOWED_ORIGINS: frozenset[str] | None = None


def _allowed_origins() -> frozenset[str]:
    global _ALLOWED_ORIGINS
    if _ALLOWED_ORIGINS is None:
        extra = os.environ.get("LAMTOOLS_CORE_ALLOWED_ORIGINS", "")
        origins = set(_DEFAULT_ORIGINS)
        for item in extra.split(","):
            item = item.strip().lower()
            if item:
                origins.add(item.rstrip("/"))
        _ALLOWED_ORIGINS = frozenset(origins)
    return _ALLOWED_ORIGINS


def allowed_origins() -> list[str]:
    """Explicit origin allow-list (for CORSMiddleware, sorted for stability)."""
    return sorted(_allowed_origins())


def normalize_origin(origin: str) -> str:
    """Normalize an Origin header value for comparison."""
    return origin.strip().lower().rstrip("/")


def is_allowed_origin(origin: str | None) -> bool:
    """True when the request is safe to serve.

    ``None`` (non-browser client such as the Python live client or curl) is
    allowed; a browser ``Origin`` must be on the allow-list.
    """
    if not origin:
        return True
    return normalize_origin(origin) in _allowed_origins()


def is_same_server_origin(
    origin: str | None,
    *,
    scheme: str,
    server: tuple[str, int] | None,
) -> bool:
    """Return whether ``origin`` exactly matches the ASGI listener.

    Core can bind a random loopback port in Tauri. Unsafe same-origin browser
    requests and WebSocket handshakes include that dynamic origin, so it
    cannot live in the static allow-list. Comparing with ASGI's listener tuple
    instead of the request Host header keeps DNS-rebinding origins rejected.
    """
    if not origin or not server:
        return False
    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError:
        return False
    expected_scheme = {"ws": "http", "wss": "https"}.get(scheme.lower(), scheme.lower())
    server_host, server_port = server
    return (
        parsed.scheme.lower() == expected_scheme
        and (parsed.hostname or "").lower() == str(server_host).lower()
        and origin_port == int(server_port)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
