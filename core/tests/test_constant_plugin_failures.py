import ast
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tomllib
from unittest.mock import AsyncMock, Mock

import pytest

CORE = Path(__file__).resolve().parents[1]


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(作业插件所用 requests 必须进入桌面包；网络控制器退出不能再伪装成 JSON 格式错误)。
def test_homework_http_dependency_is_declared_and_frozen():
    deps = tomllib.loads((CORE / 'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
    assert any(d.split('>')[0].strip() == 'requests' for d in deps)
    tree = ast.parse((CORE / 'lamtools-core-backend.spec').read_text(encoding='utf-8'))
    imports = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == '_hiddenimports' for t in n.targets))
    assert 'requests' in imports


@pytest.mark.asyncio
@pytest.mark.parametrize('reply,reason', [(b'', '提前退出'), (b'not json\n', '响应格式'),
    (b'[]\n', '响应格式'), (b'{"id":999,"result":{}}\n', '不匹配')])
async def test_controller_protocol_failure_is_explicit_and_invalidates_stream(reply, reason, tmp_path):
    path = CORE / 'src/lamtools_core/plugins/bundled/network-exploration/backend.py'
    spec = importlib.util.spec_from_file_location('constant_network_backend', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = module.NetworkRuntime(SimpleNamespace(app_data_dir=tmp_path, data_dir=tmp_path))
    reader = asyncio.StreamReader()
    reader.feed_data(reply)
    reader.feed_eof()
    stdin = SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock())
    runtime.process = SimpleNamespace(returncode=None, stdin=stdin, stdout=reader)
    with pytest.raises(RuntimeError, match=reason):
        await runtime.call('status', {})
    stdin.close.assert_called_once()
    with pytest.raises(RuntimeError, match='未运行|不可用'):
        await runtime.call('status', {})
