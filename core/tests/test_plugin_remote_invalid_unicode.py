"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(非法Unicode参数在原操作派发前明确拒绝)。"""
import httpx
import pytest
from fastapi import FastAPI
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

@pytest.mark.asyncio
@pytest.mark.parametrize('escaped', [b'\\ud800', b'\\udfff'])
async def test_invalid_unicode_argument_never_enters_operation(tmp_path, monkeypatch, escaped):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    calls=[]; original=catalog.execute
    async def tracked(*args, **kwargs):
        calls.append(args[0]); return await original(*args, **kwargs)
    monkeypatch.setattr(catalog, 'execute', tracked)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host, lambda:catalog))
    headers={'x-plugin-token':plugin_http_token(host,'hook-demo'), 'content-type':'application/json'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        path='/plugin-remote/hook-demo/demo/echo'
        bad=await client.post(path, content=b'{"args":{"text":"'+escaped+b'"}}', headers=headers)
        assert bad.status_code==400 and calls==[]
        good=await client.post(path, json={'args':{'text':'\u4f60\u597d'}}, headers=headers)
        assert good.status_code==200 and calls==['hook-demo.echo']
