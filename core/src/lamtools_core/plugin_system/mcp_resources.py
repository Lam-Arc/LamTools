"""user:“给我把 2 阶段做完，前端除外”+(MCP资源复用原配置与传输，连接绑定插件启动代，列表/模板/读取不伪装工具执行授权)。"""
import asyncio
import copy
import json
import math

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.mcp.client import MCPClient, MCPError
from lamtools_core.mcp.config import load_mcp_server_configs


class McpResourceError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginMcpResourcesAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._handles = set()
        scope.on_dispose(self.close)

    def _configs(self):
        self._scope.check_open()
        files = []
        if self._context._plugin_manifest is not None:
            from .capabilities import _read_mcp
            files = _read_mcp(self._context._plugin_manifest)
        return load_mcp_server_configs(self._context.work_root, config_files=files)

    def servers(self):
        return tuple(config.name for config in self._configs() if config.permission != "hard_block" and config.level != 0)

    def open(self, server):
        configs = self._configs()
        if type(server) is not str or len(server) > 256:
            raise McpResourceError("mcp-resource/invalid-server", "Use a configured server name")
        config = next((row for row in configs if row.name == server), None)
        if config is None or config.permission == "hard_block" or config.level == 0:
            raise McpResourceError("mcp-resource/unavailable", "Server is absent, disabled or blocked")
        if not math.isfinite(config.timeout_seconds) or not 0 < config.timeout_seconds <= 120:
            raise McpResourceError("mcp-resource/invalid-timeout", "Server timeout must be in (0, 120] seconds")
        if len(self._handles) >= 8:
            raise McpResourceError("mcp-resource/busy", "At most 8 resource connections per plugin view")
        handle = PluginMcpResourceConnection(self, MCPClient(config))
        self._handles.add(handle)
        return handle

    async def close(self):
        for handle in tuple(self._handles):
            await handle.aclose()


class PluginMcpResourceConnection:
    def __init__(self, api, client):
        self._api, self._client = api, client
        self._entered = self._closed = self._entering = False
        self._close_task = None

    async def __aenter__(self):
        self._api._scope.acquire()
        try:
            if self._entered or self._closed or self._entering:
                raise McpResourceError("mcp-resource/invalid-state", "Connection may only be entered once")
            self._entering = True
            try:
                await self._client.start()
                self._entered = True
                return self
            except BaseException:
                await self.aclose()
                raise
            finally:
                self._entering = False
        finally:
            self._api._scope.release()

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        self._closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._client.close(), name="plugin-mcp-resources-close")
            self._close_task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        async def join():
            await asyncio.shield(self._close_task)
        await finish_on_cancel(join(), name="plugin-mcp-resources-join")
        self._api._handles.discard(self)

    async def _request(self, method, params):
        scope = self._api._scope
        scope.acquire()
        try:
            if not self._entered or self._closed:
                raise McpResourceError("mcp-resource/invalid-state", "Enter an open resource connection before reading")
            try:
                result = await self._client.request(method, params)
            except MCPError:
                raise McpResourceError("mcp-resource/request-failed", "MCP resource request failed; no request was replayed") from None
            try:
                if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf8")) > 8 * 1024 * 1024:
                    raise ValueError
                field = {"resources/list": "resources", "resources/templates/list": "resourceTemplates", "resources/read": "contents"}[method]
                if type(result.get(field)) is not list or len(result[field]) > 1000 or any(type(row) is not dict for row in result[field]):
                    raise ValueError
            except Exception:
                raise McpResourceError("mcp-resource/invalid-response", "Resource response must contain a bounded list of JSON objects") from None
            return copy.deepcopy(result)
        finally:
            scope.release()

    def _cursor(self, cursor):
        if cursor is not None and (type(cursor) is not str or len(cursor) > 4096 or "\x00" in cursor):
            raise McpResourceError("mcp-resource/invalid-cursor", "Use the server's bounded cursor")
        return {} if cursor is None else {"cursor": cursor}

    async def list(self, *, cursor=None):
        return await self._request("resources/list", self._cursor(cursor))

    async def templates(self, *, cursor=None):
        return await self._request("resources/templates/list", self._cursor(cursor))

    async def read(self, uri):
        if type(uri) is not str or not uri or len(uri) > 8192 or any(ord(c) < 32 for c in uri):
            raise McpResourceError("mcp-resource/invalid-uri", "Use a nonempty resource URI, at most 8192 characters")
        return await self._request("resources/read", {"uri": uri})
