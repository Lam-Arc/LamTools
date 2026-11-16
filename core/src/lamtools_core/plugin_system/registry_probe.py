"""user:“宿主能力补齐和接口完善与文档更新”+(固定公开npm ping地址，按调用触发并在插件停用时清理请求)。"""
from __future__ import annotations

import asyncio
import math
import time

import httpx

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.config.network import httpx_client_kwargs
from .services import ServiceError

_ENDPOINTS = (
    ("https://registry.npmjs.org/-/ping", "https://registry.npmjs.org/"),
    ("https://registry.npmmirror.com/-/ping", "https://registry.npmmirror.com/"),
)
_MAX_TIMER_DELAY_MS = 2**31 - 1
_MAX_CACHE_TTL_MS = 2**53 - 1


class PluginRegistryProbeAPI:
    """Bounded, shared HTTPS reachability probe for the fixed npm registries."""

    def __init__(self, context, scope, *, enabled=True, timeout_ms=1500, cache_ttl_ms=300000):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= _MAX_TIMER_DELAY_MS:
            raise ValueError("timeout_ms must be a bounded positive integer")
        if type(cache_ttl_ms) is not int or not 0 <= cache_ttl_ms <= _MAX_CACHE_TTL_MS:
            raise ValueError("cache_ttl_ms must be a nonnegative safe integer")
        self._context, self._scope = context, scope
        self._enabled, self._timeout_ms, self._ttl_ms = enabled, timeout_ms, cache_ttl_ms
        self._cached: tuple[float, str | None] | None = None
        self._pending: asyncio.Task | None = None
        self._closed = False
        scope.on_dispose(self.close)

    def _check(self):
        self._scope.check_open()
        if self._closed or self._context._registration_scope is not self._scope:
            raise ServiceError("service/scope-closed", "pluginRegistryProbe", "probe is no longer available")

    @property
    def enabled(self):
        self._check()
        return self._enabled

    async def fastest(self) -> str | None:
        self._check()
        if not self._enabled:
            return None
        now = time.monotonic()
        if self._cached is not None and self._cached[0] > now:
            return self._cached[1]
        task = self._pending
        if task is None:
            task = asyncio.create_task(self._probe_and_cache(), name="plugin-registry-probe")
            self._pending = task
            task.add_done_callback(self._clear_pending)
        return await asyncio.shield(task)

    def _clear_pending(self, task):
        if self._pending is task:
            self._pending = None
        if not task.cancelled():
            task.exception()

    async def _ping(self, endpoint, registry):
        async with httpx.AsyncClient(timeout=self._timeout_ms / 1000, follow_redirects=False,
                                     **httpx_client_kwargs(endpoint)) as client:
            async with client.stream("GET", endpoint) as response:
                if not response.is_success:
                    raise RuntimeError("Registry ping failed")
        return registry

    async def _probe(self) -> str | None:
        requests = [asyncio.create_task(self._ping(endpoint, registry), name="registry-ping")
                    for endpoint, registry in _ENDPOINTS]
        winner = None
        try:
            # user:“逐项核对固定上游源码及手册，建立真实请求、错误、作用域、取消/流和清理验收”+(赢家结束后停止并等待另一条真实HTTPS请求清理)。
            async with asyncio.timeout(self._timeout_ms / 1000):
                pending = set(requests)
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        try:
                            winner = task.result()
                        except Exception:
                            continue
                        break
                    if winner is not None:
                        break
        except TimeoutError:
            pass
        finally:
            async def cancel_and_join():
                for task in requests:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*requests, return_exceptions=True)

            await finish_on_cancel(cancel_and_join(), name="plugin-registry-probe-cleanup")
        return winner

    async def _probe_and_cache(self):
        try:
            result = await self._probe()
            self._check()
            self._cached = (time.monotonic() + self._ttl_ms / 1000, result)
            return result
        finally:
            if self._pending is asyncio.current_task():
                self._pending = None

    async def close(self):
        self._closed = True
        task = self._pending
        if task is None or task is asyncio.current_task():
            return

        async def cancel_and_join():
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        await finish_on_cancel(cancel_and_join(), name="plugin-registry-probe-close")
