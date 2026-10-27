"""user:“该调的模块就是该写的东西”+(独立页面通过同一宿主目录调用自己的操作)。"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request


def create_plugin_router(host_provider, catalog_provider):
    router = APIRouter()

    @router.post("/plugin-system/{plugin}/rpc")
    async def plugin_rpc(plugin: str, request: Request):
        host, catalog = host_provider(), catalog_provider()
        if host is None or catalog is None or not host.available(plugin):
            raise HTTPException(409, "插件未就绪或已停用")
        payload = await request.json()
        method, params = payload.get("method"), payload.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            raise HTTPException(400, "method 和 params 格式错误")
        own_operation = catalog.owner_of(method) == f"plugin:{plugin}"
        own_config = method in {"plugin.system.config.get", "plugin.system.config.update"} and params.get("name") == plugin
        consent = getattr(host, "operation_consent", None)
        approval = consent.pending.get(str(params.get("id", ""))) if consent else None
        own_approval = method == "plugin.system.operation.respond" and approval is not None and approval[1].plugin == plugin
        if not (own_operation or own_config or own_approval):
            raise HTTPException(403, "窗口只能调用所属插件的操作与配置")
        try:
            result = await catalog.execute(method, params, metadata={"source": "plugin-window", "plugin": plugin})
        except KeyError:
            raise HTTPException(409, "插件操作已更新，请刷新窗口")
        return asdict(result)

    return router
