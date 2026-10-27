"""user:“该调的模块就是该写的东西”+(独立窗口必须有真实宿主通道，不能依赖主页面全局变量)。"""
import httpx
import pytest
from fastapi import FastAPI
from tests.test_plugin_host_rebuild import boot


@pytest.mark.asyncio
async def test_window_uses_same_readiness_and_operation_path(tmp_path):
    from lamtools_core.plugin_system.http import create_plugin_router
    host, manager, catalog, folder = await boot(tmp_path)
    app = FastAPI()
    app.include_router(create_plugin_router(lambda: host, lambda: catalog), prefix="/api/core")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        response = await client.post("/api/core/plugin-system/demo/rpc", json={"method": "demo.read", "params": {}})
        assert response.status_code == 200 and response.json()["payload"]["generation"] == "1"
        denied = await client.post("/api/core/plugin-system/demo/rpc", json={"method": "plugin.system.uninstall", "params": {"name": "demo"}})
        assert denied.status_code == 403
        await catalog.execute("plugin.system.disable", {"name": "demo"})
        response = await client.post("/api/core/plugin-system/demo/rpc", json={"method": "demo.read", "params": {}})
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_real_application_serves_plugin_module_asset(tmp_path, monkeypatch, isolated_config_root):
    # user:“我看看界面什么的有没有 bug”+(验收实际应用路由，插件已加载后模块资源必须返回 JavaScript)。
    import inspect
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    host, manager, catalog, folder = await boot(tmp_path)
    (folder / "page.mjs").write_text("export function mount() {}", encoding="utf-8")
    app = create_core_agent_http_app(core_db=tmp_path / "app.db", data_dir=tmp_path / "app-data", work_root=tmp_path)
    route = next(item for item in app.routes if getattr(item, "path", "") == "/api/core/plugin-system/{plugin_name}/assets/{asset_path:path}")
    inspect.getclosurevars(route.endpoint).nonlocals["app_state"]["plugin_system_host"] = host
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            response = await client.get("/api/core/plugin-system/demo/assets/page.mjs")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/javascript")
            assert response.text == "export function mount() {}"
    finally:
        await manager.stop("demo")
