"""Core listener access control, independent of browser Origin filtering."""

from __future__ import annotations

import hmac
import ipaddress
import os
from dataclasses import dataclass, field

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


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
