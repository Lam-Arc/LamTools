"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(市场只读复用原固定官方目录和缓存，不触发安装)。"""
import unicodedata

from lamtools_core.async_tasks import finish_on_cancel
from .durable_access import _json
from .management_access import HostOperationError


class PluginMarketAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._catalog = context.resolved_operation_catalog()

    def _check(self):
        self._scope.check_open()
        if self._context._registration_scope is not self._scope or self._context.resolved_operation_catalog() is not self._catalog:
            raise HostOperationError("host/changed", "Market operation catalog changed")

    async def list(self):
        self._scope.acquire()
        try:
            self._check()
            if self._catalog is None or not self._catalog.has("plugin.market.list"):
                raise HostOperationError("host/unavailable", "Original market provider is unavailable")
            # user:“复用原宿主权威”+(原市场可能在线程中取索引和写缓存；取消后等待真实读取结算再释放租约)。
            result = await finish_on_cancel(self._catalog.execute("plugin.market.list", {},
                metadata={"source": "plugin-sdk", "plugin": self._scope.owner}), name="plugin-market-read")
            self._check()
            if result.status != "ok":
                raise HostOperationError("host/operation-rejected", "Original market lookup failed", status=result.status)
            return _json(result.payload)
        finally:
            self._scope.release()

    async def search(self, text="", *, offset=0, limit=50):
        if (type(text) is not str or len(text) > 200 or "\x00" in text
                or type(offset) is not int or not 0 <= offset <= 2**53 - 1
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError("Use bounded text, non-negative offset and limit 1–100")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise ValueError("Search text must be valid UTF-8") from None
        # user:“复用原宿主权威”+(搜索只过滤原市场实际返回的目录，保留不可用来源和安装状态)。
        result = await self.list()
        query = unicodedata.normalize("NFKC", text).casefold().strip()
        matches = []
        for row in result["plugins"]:
            fields = (row["id"], row["title"], row["description"], row["category"], *row["capabilities"])
            if not query or any(query in unicodedata.normalize("NFKC", field).casefold() for field in fields):
                matches.append(row)
        items = matches[offset:offset + limit]
        next_offset = offset + len(items)
        return {"items": items, "total": len(matches), "next_offset": next_offset if next_offset < len(matches) else None,
                "source": result["source"], "error": result["error"]}

    async def entry(self, name):
        # user:“复用原宿主权威”+(精确读取固定目录条目，并保留原来源与不可用状态)。
        if type(name) is not str or not name or len(name) > 200 or "\x00" in name:
            raise ValueError("Use a non-empty bounded plugin id")
        try:
            name.encode("utf-8")
        except UnicodeError:
            raise ValueError("Plugin id must be valid UTF-8") from None
        result = await self.list()
        item = next((row for row in result["plugins"] if row["id"] == name), None)
        return {"item": item, "source": result["source"], "error": result["error"]}
