"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(市场只读复用原固定官方目录和缓存，不触发安装)。"""
import copy
import secrets
import time
import unicodedata
from collections import OrderedDict

from lamtools_core.async_tasks import finish_on_cancel
from .durable_access import _json
from .management_access import HostOperationError
from .market import compare_versions


def _now():
    return time.monotonic()


def _validate_search(text, offset, limit, category):
    if (type(text) is not str or len(text) > 200 or "\x00" in text
            or type(offset) is not int or not 0 <= offset <= 2**53 - 1
            or type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError("Use bounded text, non-negative offset and limit 1–100")
    if category is not None and (type(category) is not str or not category.strip() or len(category) > 200 or "\x00" in category):
        raise ValueError("Use a bounded nonblank category name")
    try:
        text.encode("utf-8")
        if category is not None:
            category.encode("utf-8")
    except UnicodeError:
        raise ValueError("Search text must be valid UTF-8") from None


class PluginMarketAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._catalog = context.resolved_operation_catalog()

    def _check(self):
        self._scope.check_open()
        if self._context._registration_scope is not self._scope or self._context.resolved_operation_catalog() is not self._catalog:
            raise HostOperationError("host/changed", "Market operation catalog changed")

    def _plugin_list_binding(self):
        self._check()
        operation = "plugin.system.list"
        if (self._catalog is None or not self._catalog.has(operation)
                or self._catalog.owner_of(operation) != "plugin-system"):
            raise HostOperationError("host/unavailable", "Original plugin inventory provider is unavailable")
        binding = self._catalog.binding_token(operation)
        if binding is None:
            raise HostOperationError("host/unavailable", "Original plugin inventory provider is unavailable")
        return binding

    async def _installed_versions(self, expected_binding):
        if self._plugin_list_binding() is not expected_binding:
            raise HostOperationError("host/changed", "Original plugin inventory provider changed")
        # user:“复用原宿主权威”+(安装信息每页重新读取原插件管理清单，只投影插件ID和版本)。
        result = await self._context.plugins.list()
        self._check()
        if self._plugin_list_binding() is not expected_binding:
            raise HostOperationError("host/changed", "Original plugin inventory provider changed")
        rows = result.get("plugins") if type(result) is dict else None
        if type(rows) is not list:
            raise HostOperationError("host/invalid-result", "Original plugin inventory returned an invalid result")
        versions = {}
        for row in rows:
            if (type(row) is not dict or type(row.get("id")) is not str
                    or type(row.get("version")) is not str or row["id"] in versions):
                raise HostOperationError("host/invalid-result", "Original plugin inventory returned an invalid result")
            versions[row["id"]] = row["version"]
        return versions

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

    async def search(self, text="", *, offset=0, limit=50, category=None):
        _validate_search(text, offset, limit, category)
        # user:“复用原宿主权威”+(搜索只过滤原市场实际返回的目录，保留不可用来源和安装状态)。
        result = await self.list()
        query = unicodedata.normalize("NFKC", text).casefold().strip()
        selected_category = unicodedata.normalize("NFKC", category).casefold().strip() if category is not None else None
        matches = []
        for row in result["plugins"]:
            # user:“复用原宿主权威”+(只按原目录真实分类名称过滤，不虚构上游分类ID或标签)。
            if selected_category is not None and unicodedata.normalize("NFKC", row["category"]).casefold() != selected_category:
                continue
            fields = (row["id"], row["title"], row["description"], row["category"], *row["capabilities"])
            if not query or any(query in unicodedata.normalize("NFKC", field).casefold() for field in fields):
                matches.append(row)
        items = matches[offset:offset + limit]
        next_offset = offset + len(items)
        return {"items": items, "total": len(matches), "next_offset": next_offset if next_offset < len(matches) else None,
                "source": result["source"], "error": result["error"]}

    async def search_snapshot(self, text="", *, offset=0, limit=50, category=None, snapshot=None):
        _validate_search(text, offset, limit, category)
        if snapshot is not None and (type(snapshot) is not str or not snapshot.isascii() or not 1 <= len(snapshot) <= 128):
            raise ValueError("Use a valid snapshot token")
        self._scope.acquire()
        try:
            self._check()
            operation = "plugin.market.list"
            if (self._catalog is None or not self._catalog.has(operation)
                    or self._catalog.owner_of(operation) != "plugin-system"):
                raise HostOperationError("host/unavailable", "Original market provider is unavailable")
            binding = self._catalog.binding_token(operation)
            if binding is None:
                raise HostOperationError("host/unavailable", "Original market provider is unavailable")
            cache = getattr(self._scope, "_market_search_snapshots", None)
            if cache is None:
                cache = OrderedDict()
                async def clear_snapshots(): cache.clear()
                self._scope.on_dispose(clear_snapshots)
                self._scope._market_search_snapshots = cache
            for key, row in tuple(cache.items()):
                if row[0] <= _now():
                    cache.pop(key, None)
            if snapshot is None:
                # user:“复用原宿主权威”+(只固定真实原目录读取结果，超过有界容量时明确拒绝)。
                plugin_list_binding = self._plugin_list_binding()
                page = await self.search(text, offset=0, limit=100, category=category)
                self._check()
                if self._catalog.binding_token(operation) is not binding or not self._catalog.has(operation) or self._catalog.owner_of(operation) != "plugin-system":
                    raise HostOperationError("host/changed", "Market provider changed")
                if self._plugin_list_binding() is not plugin_list_binding:
                    raise HostOperationError("host/changed", "Original plugin inventory provider changed")
                if page["next_offset"] is not None:
                    raise HostOperationError("market/snapshot-too-large", "Market snapshot exceeds 100 entries")
                stored = None
            else:
                stored = cache.get(snapshot)
                if stored is None or stored[1] is not binding or stored[3] != text or stored[4] != category:
                    raise HostOperationError("market/invalid-snapshot", "Market snapshot is expired or belongs to another query")
                plugin_list_binding = stored[2]
                page = stored[5]
            items = copy.deepcopy(page["items"][offset:offset + limit])
            installed_versions = await self._installed_versions(plugin_list_binding)
            # user:“逐项核对固定上游源码及手册”+(目录结果固定为首次快照，每页安装版本及升级状态沿用上游实时重算语义)。
            for item in items:
                installed_version = installed_versions.get(item["id"], "")
                item["installed_version"] = installed_version
                item["update_available"] = bool(
                    installed_version and item["version"]
                    and compare_versions(item["version"], installed_version) > 0
                )
            next_offset = offset + len(items)
            self._check()
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(安装状态读取成功后才发布新快照，旧快照在等待期间失效则拒绝结果)。
            if (not self._catalog.has(operation) or self._catalog.owner_of(operation) != "plugin-system"
                    or self._catalog.binding_token(operation) is not binding):
                raise HostOperationError("host/changed", "Market provider changed")
            if stored is None:
                for key, row in tuple(cache.items()):
                    if row[0] <= _now():
                        cache.pop(key, None)
                while len(cache) >= 16:
                    cache.popitem(last=False)
                snapshot = secrets.token_urlsafe(24)
                while snapshot in cache:
                    snapshot = secrets.token_urlsafe(24)
                cache[snapshot] = (_now() + 120, binding, plugin_list_binding, text, category, copy.deepcopy(page))
            else:
                if cache.get(snapshot) is not stored or stored[0] <= _now():
                    if cache.get(snapshot) is stored:
                        cache.pop(snapshot, None)
                    raise HostOperationError("market/invalid-snapshot", "Market snapshot expired or was evicted during lookup")
                cache.move_to_end(snapshot)
            return {"items": items, "total": page["total"], "next_offset": next_offset if next_offset < page["total"] else None,
                    "source": page["source"], "error": page["error"], "snapshot": snapshot}
        finally:
            self._scope.release()

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
