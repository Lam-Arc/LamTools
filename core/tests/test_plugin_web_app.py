"""user:“给我把 2 阶段做完，前端除外”+(Web运行胶合仅接既有后端启动/静态路由，不修改前端文件)。"""
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from lamtools_core.plugin_system import PluginContext


@pytest.mark.asyncio
async def test_actual_http_host_publishes_url_before_plugin_start(tmp_path, isolated_config_root, monkeypatch):
    from lamtools_core.app import http_agent_app
    from lamtools_core.app.api_access import CoreApiAccessPolicy
    from lamtools_core.plugin_system.web_app import PluginWebAppAPI
    from .test_plugin_llm_extensions import native_client
    # user:“如果对你的工作产生了阻塞，那么跳过并报告，最后统一处理”+(不改并行provider_id必填导致的未配置模型启动分支；Web验收使用明确测试模型)。
    monkeypatch.setattr(http_agent_app,"load_llm_config",lambda **kwargs:native_client().config)
    monkeypatch.setattr(http_agent_app,"warm_command_shell",lambda:None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake",lambda:None)
    frontend = tmp_path / "static-test-fixture"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>existing static route proof</html>")
    plugin = tmp_path / "plugins" / "url-reader"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({"name":"url-reader","version":"1","backend":"./backend.py"}))
    (plugin / "backend.py").write_text('''
import json
class Runtime:
    def start(self,ctx):
        (ctx.work_root/'web-startup.json').write_text(json.dumps({'url':ctx.web_app.get_advertised_url()}))
def create_plugin(ctx):
    return Runtime()
''')
    captured=[]
    original=PluginWebAppAPI.get_advertised_url
    def observe(self):
        captured.append(self)
        return original(self)
    monkeypatch.setattr(PluginWebAppAPI,"get_advertised_url",observe)
    app=http_agent_app.create_core_agent_http_app(core_db=tmp_path/"core.db",data_dir=tmp_path/"data",work_root=tmp_path,
        frontend_dir=frontend,plugin_roots=(plugin.parent,),access_policy=CoreApiAccessPolicy(),advertised_url="http://127.0.0.1:8765",model_id="route-one")
    async with app.router.lifespan_context(app):
        assert json.loads((tmp_path/"web-startup.json").read_text())["url"] == "http://127.0.0.1:8765/"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://127.0.0.1:8765") as client:
            response=await client.get("/")
            assert response.status_code==200 and "existing static route proof" in response.text
    from lamtools_core.plugin_system.services import ServiceError
    with pytest.raises(ServiceError):
        original(captured[0])


@pytest.mark.asyncio
async def test_web_url_is_explicit_without_tokens_and_replacement_revokes_old_view(tmp_path):
    from lamtools_core.plugin_system.web_app import WebAppValues, WebAppAccessError
    ctx=PluginContext(tmp_path)
    ctx._begin_registration_scope("example",1)
    with pytest.raises(WebAppAccessError):
        ctx.web_app.get_advertised_url()
    for url in ["file:///local", "http://user:secret@host/", "http://host/?token=secret", "http://host/#x", "http://0.0.0.0:8000/", "http://host:0/"]:
        with pytest.raises(WebAppAccessError):
            WebAppValues.from_url(url)
    value=WebAppValues.from_url("https://example.invalid/ui")
    ctx.set_service("web_app",value)
    api=ctx.web_app
    assert api.get_advertised_url()=="https://example.invalid/ui/"
    ctx.services.pop("web_app")
    with pytest.raises(WebAppAccessError) as error:
        api.get_advertised_url()
    assert error.value.code=="web-app/host-changed"
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("port",[8765,0])
async def test_original_serve_launcher_only_advertises_known_frontend_port(tmp_path,monkeypatch,port):
    from lamtools_core.cli import build_parser
    from lamtools_core.cli_commands.server import cmd_serve
    from lamtools_core.app import http_agent_app
    captured={}
    def create(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(http_agent_app,"create_core_agent_http_app",create)
    monkeypatch.setattr("lamtools_core.config.defaults.ensure_default_config_files",lambda:None)
    class Server:
        def __init__(self,config):
            self.config=config
        async def serve(self):
            return None
    monkeypatch.setitem(sys.modules,"uvicorn",SimpleNamespace(Config=lambda *a,**kw:kw,Server=Server))
    args=build_parser().parse_args(["serve","--host","127.0.0.1","--port",str(port),"--frontend-dir",str(tmp_path)])
    assert await cmd_serve(args)==0
    if port:
        assert captured["advertised_url"]=="http://127.0.0.1:8765/"
    else:
        assert "advertised_url" not in captured


@pytest.mark.asyncio
async def test_http_host_without_model_config_starts_with_empty_provider(tmp_path,monkeypatch,isolated_config_root):
    """user:“如果不需要，就自己继续”+(统一处理前轮跳过的并行集成缺陷，未配模型也须能启动宿主)。"""
    from lamtools_core.app import http_agent_app
    from lamtools_core.app.api_access import CoreApiAccessPolicy
    monkeypatch.setattr(http_agent_app,"warm_command_shell",lambda:None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake",lambda:None)
    def unconfigured(**kwargs):
        raise ValueError("No configured model")
    monkeypatch.setattr(http_agent_app,"load_llm_config",unconfigured)
    app=http_agent_app.create_core_agent_http_app(core_db=tmp_path/"no-model.db",data_dir=tmp_path/"data",
                                               work_root=tmp_path,access_policy=CoreApiAccessPolicy(),plugin_roots=(tmp_path/"plugins",))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://127.0.0.1") as client:
            response=await client.get("/api/health")
            assert response.status_code==200
            assert response.json()["model_configured"] is False
