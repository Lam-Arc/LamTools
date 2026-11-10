"""Core listener access control, independent of browser Origin filtering."""

from __future__ import annotations

import hmac
import ipaddress
import os
from collections.abc import MutableMapping
from dataclasses import dataclass, field

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


PLUGIN_ASSET_PREFIX = "/api/core/plugin-system/"
# 标注层页面和 Core 永远不同源：开发是 5299 对 5298，打包后是 WebView 自定义源
# 对 127.0.0.1。表情包图片只是服务端生成名字的只读临时文件，必须允许跨源嵌入，
# 否则浏览器按 CORP: same-origin 直接拦掉，页面上只剩一个 0 高的 img。
OVERLAY_ASSET_PREFIX = "/api/core/overlay/assets/"


def is_plugin_asset_path(path: str) -> bool:
    return path.startswith(PLUGIN_ASSET_PREFIX) and "/assets/" in path


def apply_response_security_headers(
    path: str,
    headers: MutableMapping[str, str],
    *,
    runtime_path: str,
) -> None:
    """按路径给响应补安全头；跨源需要嵌入的只读资源单独放开。"""
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "no-referrer")
    if is_plugin_asset_path(path):
        # Plugin pages are imported as ES modules by the desktop WebView,
        # whose origin can differ from the backend port. Module scripts
        # need CORS plus a cross-origin resource policy; the content is
        # read-only plugin code, never Core API data.
        headers["Access-Control-Allow-Origin"] = "*"
        headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        # Module scripts are credential-free; a wildcard origin combined
        # with allow-credentials is invalid and some WebViews reject it.
        # user:“我看看界面什么的有没有 bug”+(Starlette 响应头不是 dict，删除跨域凭证头不能使插件资源请求崩溃)。
        if "access-control-allow-credentials" in headers:
            del headers["access-control-allow-credentials"]
        headers["Access-Control-Allow-Private-Network"] = "true"
        headers.setdefault("Vary", "Origin")
    elif path == runtime_path:
        # The runtime document is intentionally framed by the local Tauri
        # host, which uses a different loopback port in development and the
        # Tauri custom origin in packaged builds.
        headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors http://127.0.0.1:* http://localhost:* tauri://localhost http://tauri.localhost",
        )
        headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
    elif path.startswith(OVERLAY_ASSET_PREFIX):
        # user:“图片表情包和 emoji 表情包实际可见”+(表情包图片要被标注层页面跨源贴出来)。
        headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
    else:
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")


def is_loopback_address(host: str) -> bool:
    """Trust numeric socket peers only; never resolve caller-supplied names."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


@dataclass(frozen=True)
class CoreApiAccessPolicy:
    allow_lan: bool = False
    token: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.allow_lan and (
            len(self.token) < 32
            or not self.token.isascii()
            or any(char.isspace() or not char.isprintable() for char in self.token)
        ):
            raise ValueError(
                "LAN access requires LAMTOOLS_CORE_API_TOKEN with at least 32 printable ASCII characters and no whitespace"
            )

    @classmethod
    def from_env(cls, *, allow_lan: bool | None = None) -> CoreApiAccessPolicy:
        if allow_lan is None:
            value = os.environ.get("LAMTOOLS_CORE_ALLOW_LAN", "0").strip().lower()
            if value not in {"0", "false", "no", "off", "1", "true", "yes", "on"}:
                raise ValueError("LAMTOOLS_CORE_ALLOW_LAN must be on or off")
            allow_lan = value in {"1", "true", "yes", "on"}
        return cls(allow_lan=allow_lan, token=os.environ.get("LAMTOOLS_CORE_API_TOKEN", "") if allow_lan else "")

    def validate_bind_host(self, host: str) -> str:
        # Canonicalize localhost instead of depending on mutable DNS/hosts files.
        host = "127.0.0.1" if host.lower() == "localhost" else host
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("Core --host must be a numeric IP address or localhost") from exc
        if not is_loopback_address(host) and not self.allow_lan:
            raise ValueError("Non-loopback Core binding requires --allow-lan (or LAMTOOLS_CORE_ALLOW_LAN=1) and LAMTOOLS_CORE_API_TOKEN")
        return host

    def rejection(self, scope: Scope) -> tuple[int, str] | None:
        if not self.allow_lan:
            peer = scope.get("client")
            if not peer or not is_loopback_address(str(peer[0])):
                return 403, "Core API accepts loopback connections only"
            return None
        # LAN mode authenticates *every* caller, including loopback proxies.
        # Origin, Host, Forwarded, query strings and cookies grant no access.
        headers = [value for key, value in scope.get("headers", []) if key.lower() == b"authorization"]
        if len(headers) == 1:
            parts = headers[0].split(b" ")
            if len(parts) == 2 and parts[0].lower() == b"bearer" and hmac.compare_digest(parts[1], self.token.encode("ascii")):
                return None
        return 401, "Core API bearer authentication required"


class CoreApiAccessMiddleware:
    """Protect every HTTP route/mount and WebSocket before dispatch/accept."""

    def __init__(self, app: ASGIApp, policy: CoreApiAccessPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            rejection = self.policy.rejection(scope)
            if rejection:
                status, detail = rejection
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008, "reason": detail})
                else:
                    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
                    await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, send)
                return
        await self.app(scope, receive, send)
