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

    async def list_indexes(self):
        self._scope.acquire()
        try:
            self._check()
            if (self._catalog is None or not self._catalog.has("plugin.market.list")
                    or self._catalog.owner_of("plugin.market.list") != "plugin-system"):
                raise HostOperationError("host/unavailable", "Original market provider is unavailable")
            # user:“第二阶段结束后 就继续开展第三阶段”+(只报告已挂载原市场的固定来源，不声称网络或安装包可用)。
            from .market import CATALOG_URL
            result = [{"url": CATALOG_URL}]
            self._check()
            return result
        finally:
            self._scope.release()

    async def list(self):
        self._scope.acquire()
        try:
            self._check()
            # user:“不用静态扫描、空壳或未安装提供方冒充可用”+(读取和搜索只使用原插件系统拥有的市场操作)。
            if (self._catalog is None or not self._catalog.has("plugin.market.list")
                    or self._catalog.owner_of("plugin.market.list") != "plugin-system"):
                raise HostOperationError("host/unavailable", "Original market provider is unavailable")
            token = self._catalog.binding_token("plugin.market.list")
            # user:“复用原宿主权威”+(原市场可能在线程中取索引和写缓存；取消后等待真实读取结算再释放租约)。
            async def call_original():
                # user:“不用静态扫描、空壳或未安装提供方冒充可用”+(异步派发实际开始前再核对原操作绑定)。
                self._check()
                if (not self._catalog.has("plugin.market.list")
                        or self._catalog.owner_of("plugin.market.list") != "plugin-system"
                        or self._catalog.binding_token("plugin.market.list") is not token):
                    raise HostOperationError("host/changed", "Market provider changed")
                return await self._catalog.execute("plugin.market.list", {},
                    metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            result = await finish_on_cancel(call_original(), name="plugin-market-read")
            self._check()
            if (not self._catalog.has("plugin.market.list")
                    or self._catalog.owner_of("plugin.market.list") != "plugin-system"
                    or self._catalog.binding_token("plugin.market.list") is not token):
                raise HostOperationError("host/changed", "Market provider changed")
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
