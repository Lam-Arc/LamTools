"""Plugin-owned HTTP routes.

A plugin can expose a small HTTP surface for webhooks, OAuth callbacks or a
local integration.  Routes are declared in ``plugin.json`` and dispatch to the
plugin's own operations; the host never runs arbitrary Python from a request.

```json
"http": {
  "routes": [
    {"method": "POST", "path": "/webhook", "operation": "demo.webhook"}
  ]
}
```

Every route requires a bearer token by default.  The token lives in the
plugin's secret store under ``httpToken`` and is generated on first use; the
plugin can read it through ``context.service("secrets")`` and show it in its
settings page.  ``"auth": "none"`` is allowed only when the plugin explicitly
opts out, and is intended for local-only integrations.
"""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .capabilities import CapabilityError
from .manifest import PluginManifest
from .operation_bridge import read_operations

VALID_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
VALID_AUTH = ("token", "none")
MAX_ROUTES = 32


@dataclass(frozen=True)
class PluginHttpRoute:
    plugin: str
    method: str
    path: str
    operation: str
    auth: str = "token"


def _normalize_path(value: Any) -> str:
    path = str(value or "").strip()
    if not path.startswith("/"):
        raise ValueError(f"http route path must start with '/': {path}")
    if "?" in path or "#" in path or ".." in path:
        raise ValueError(f"http route path is not a plain path: {path}")
    return path.rstrip("/") or "/"


def read_http_routes(manifest: PluginManifest) -> list[PluginHttpRoute]:
    raw = manifest.raw.get("http") if isinstance(manifest.raw, dict) else None
    if raw is None:
        return []
    items = raw.get("routes") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise CapabilityError(manifest.name, "http.routes must be an array")
    if len(items) > MAX_ROUTES:
        raise CapabilityError(manifest.name, f"http.routes may declare at most {MAX_ROUTES} routes")
    routes: list[PluginHttpRoute] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise CapabilityError(manifest.name, f"http.routes[{index}] must be an object")
        method = str(item.get("method") or "POST").strip().upper()
        if method not in VALID_METHODS:
            raise CapabilityError(manifest.name, f"http.routes[{index}] has an invalid method: {method}")
        try:
            path = _normalize_path(item.get("path"))
        except ValueError as exc:
            raise CapabilityError(manifest.name, str(exc)) from exc
        operation = str(item.get("operation") or "").strip()
        if not operation or "." not in operation:
            raise CapabilityError(manifest.name, f"http.routes[{index}] needs an operation name")
        auth = str(item.get("auth") or "token").strip().lower()
        if auth not in VALID_AUTH:
            raise CapabilityError(manifest.name, f"http.routes[{index}] has an invalid auth mode: {auth}")
        key = (method, path)
        if key in seen:
            raise CapabilityError(manifest.name, f"duplicate http route: {method} {path}")
        seen.add(key)
        routes.append(
            PluginHttpRoute(
                plugin=manifest.name,
                method=method,
                path=path,
                operation=operation,
                auth=auth,
            )
        )
    return routes


def plugin_http_token(host: Any, plugin: str) -> str:
    """Return the plugin's HTTP bearer token, creating it on first use."""
    manager = getattr(host, "backend_manager", None)
    context = getattr(manager, "context", None)
    store = getattr(context, "_secret_store", None)
    if store is None or not hasattr(store, "view"):
        return ""
    view = store.view(plugin)
    token = str(view.get("httpToken") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    view.set("httpToken", token)
    return token


def _provided_token(headers: dict[str, str]) -> str:
    value = str(headers.get("x-plugin-token") or "").strip()
    if value:
        return value
    authorization = str(headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    hidden = {"authorization", "cookie", "set-cookie", "proxy-authorization"}
    return {str(key).lower(): str(value) for key, value in headers.items() if str(key).lower() not in hidden}


async def dispatch_http_request(
    *,
    host: Any,
    catalog: Any,
    plugin: str,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
    remote: str = "",
) -> tuple[int, dict[str, Any]]:
    """Resolve one plugin HTTP request. Returns ``(status_code, payload)``."""
    if host is None or catalog is None:
        return 503, {"error": "plugin system is not ready"}
    plugin = str(plugin or "").strip()
    if not plugin:
        return 404, {"error": "plugin is required"}
    if not host.available(plugin):
        return 409, {"error": f"plugin '{plugin}' is not available"}
    manifest = host.get(plugin)
    if manifest is None:
        return 404, {"error": f"plugin '{plugin}' is not installed"}
    try:
        routes = read_http_routes(manifest)
    except CapabilityError as exc:
        return 400, {"error": exc.message}
    request_method = str(method or "").upper()
    try:
        request_path = _normalize_path(unquote(str(path or "")))
    except ValueError:
        return 404, {"error": "route not found"}
    route = next(
        (item for item in routes if item.method == request_method and item.path == request_path),
        None,
    )
    if route is None:
        return 404, {"error": "route not found"}

    raw_headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    safe_headers = _safe_headers(raw_headers)
    if route.auth == "token":
        expected = plugin_http_token(host, plugin)
        provided = _provided_token(raw_headers)
        if not expected or not provided or not hmac.compare_digest(expected, provided):
            return 401, {"error": "invalid plugin token"}

    try:
        operations = {spec.name: spec for spec in read_operations(manifest)}
    except CapabilityError as exc:
        return 400, {"error": exc.message}
    spec = operations.get(route.operation)
    if spec is None or catalog.owner_of(route.operation) != f"plugin:{plugin}":
        return 403, {"error": "route operation is not owned by this plugin"}
    if spec.permission != "auto_allow":
        # ask_user / hard_block cannot be approved from an HTTP request.
        return 403, {"error": "route operation requires interactive approval"}

    payload = {
        "method": request_method,
        "path": request_path,
        "query": dict(query or {}),
        "body": body,
        "headers": safe_headers,
    }
    try:
        result = await catalog.execute(
            route.operation,
            payload,
            metadata={"source": "plugin-http", "plugin": plugin, "remote": str(remote or "")},
        )
    except KeyError:
        return 409, {"error": "route operation is not mounted"}
    status_code = 200 if result.status == "ok" else 400
    return status_code, {"name": result.name, "status": result.status, "payload": result.payload}


def create_plugin_http_router(host_provider, catalog_provider) -> APIRouter:
    router = APIRouter()

    @router.api_route(
        "/plugin-http/{plugin}/{path:path}",
        methods=list(VALID_METHODS),
    )
    async def plugin_http(plugin: str, path: str, request: Request):
        raw = await request.body()
        body: Any = None
        if raw:
            content_type = str(request.headers.get("content-type") or "")
            if "application/json" in content_type:
                try:
                    body = json.loads(raw)
                except ValueError:
                    raise HTTPException(400, "request body is not valid JSON") from None
            else:
                body = raw.decode("utf-8", errors="replace")
        status_code, payload = await dispatch_http_request(
            host=host_provider(),
            catalog=catalog_provider(),
            plugin=plugin,
            method=request.method,
            path=path if path.startswith("/") else f"/{path}",
            query=dict(request.query_params),
            body=body,
            headers=dict(request.headers),
            remote=str(request.client.host if request.client else ""),
        )
        return JSONResponse(payload, status_code=status_code)

    return router


__all__ = [
    "PluginHttpRoute",
    "create_plugin_http_router",
    "dispatch_http_request",
    "plugin_http_token",
    "read_http_routes",
]
