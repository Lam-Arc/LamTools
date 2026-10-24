"""收尾方案步骤 2 验收：装配纯化与后端生命周期单例。

user:“连续 N 轮装配后 study/workflow 后端实例数恒为 1”+声明装配每轮可跑，
后端句柄进程内唯一；宿主按（根集合, 账本）共享；discover 有指纹缓存。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_backend_plugin(root: Path) -> Path:
    plugin = root / "counter"
    (plugin / "backend").mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "counter", "version": "0.1.0"}),
        encoding="utf-8",
    )
    (plugin / "backend" / "__init__.py").write_text(
        "VALUE = {'backend': 'counter-1'}\n"
        "\n"
        "def create_plugin(context):\n"
        "    return VALUE\n",
        encoding="utf-8",
    )
    return plugin


@pytest.mark.asyncio
async def test_repeated_assemblies_load_each_backend_once(tmp_path, monkeypatch):
    from lamtools_core import plugin_system
    from lamtools_core.plugin_system import lifecycle

    roots = tmp_path / "plugins"
    roots.mkdir()
    _make_backend_plugin(roots)

    loads: list[str] = []
    original = lifecycle.load_plugin_backend

    def counting_load(plugin, context):
        loads.append(plugin.name)
        return original(plugin, context)

    monkeypatch.setattr(plugin_system.lifecycle, "load_plugin_backend", counting_load)

    from lamtools_core.app.base_agent import assemble_core_agent_plugins

    first = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[roots],
    )
    # 首轮会加载 counter 与全部带后端的内置插件（内置根永远在扫描链路）。
    first_loads = list(loads)
    assert "counter" in first_loads

    # 每轮装配复用同一份句柄：显式传入与不传（读共享管理器）都不重新加载。
    for index in range(3):
        assembly = assemble_core_agent_plugins(
            data_dir=tmp_path / "data",
            work_root=tmp_path,
            plugin_roots=[roots],
            plugin_runtimes=first["plugin_runtimes"] if index < 2 else None,
        )
        # 句柄本体必须同一（列表可能被复制，句柄对象不许换新）。
        assert {id(handle) for handle in assembly["plugin_runtimes"]} == {
            id(handle) for handle in first["plugin_runtimes"]
        }
    assert loads == first_loads, loads


def test_hosts_are_shared_per_roots_and_ledger(tmp_path):
    from lamtools_core.plugin_system import PluginHost, shared_host

    roots = [tmp_path / "plugins"]
    state = tmp_path / "data" / "plugin-system.jsonc"
    one = shared_host(roots=roots, state_path=state)
    two = shared_host(roots=roots, state_path=state)
    assert one is two
    assert isinstance(one, PluginHost)
    # 不同账本不同宿主
    other = shared_host(roots=roots, state_path=tmp_path / "other.jsonc")
    assert other is not one


def test_manager_is_reused_not_recreated(tmp_path):
    from lamtools_core.plugin_system import PluginHost, shared_host
    from lamtools_core.plugin_system.backend_runtime import register_manager

    host = shared_host(
        roots=[tmp_path / "plugins"],
        state_path=tmp_path / "data" / "plugin-system.jsonc",
    )
    first = register_manager(host, [], None)
    second = register_manager(host, [], None)
    assert first is second
    assert host.backend_manager is first


def test_discover_cache_reuses_results_until_roots_change(tmp_path, monkeypatch):
    plugin = tmp_path / "plugins" / "demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0"}), encoding="utf-8"
    )

    from lamtools_core.plugin_system import PluginHost

    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "s.jsonc")
    first = host.discover()
    second = host.discover()
    # 缓存命中：同一批清单对象，不再扫盘。
    assert first is second

    # 账本变化（启停）让缓存失效并反映新状态。
    host.disable("demo")
    third = host.discover()
    assert third is not first
    assert next(item for item in third if item.name == "demo").enabled is False

    # 清单文件变化让缓存失效。
    host.enable("demo")
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "2.0.0"}), encoding="utf-8"
    )
    fourth = host.discover()
    assert next(item for item in fourth if item.name == "demo").version == "2.0.0"


def test_discover_cache_keeps_errors_visible(tmp_path):
    root = tmp_path / "plugins"
    bad = root / "bad"
    bad.mkdir(parents=True)
    (bad / "plugin.json").write_text('{"name": "bad"}', encoding="utf-8")

    from lamtools_core.plugin_system import PluginHost

    host = PluginHost(roots=[root], state_path=tmp_path / "s.jsonc")
    discovered = host.discover()
    assert discovered == []  # version 缺失：不进列表，错误可见
    assert host.errors and "version is required" in host.errors[0]["error"]
    # 缓存命中路径同样保留 errors。
    host.discover()
    assert host.errors and "version is required" in host.errors[0]["error"]
