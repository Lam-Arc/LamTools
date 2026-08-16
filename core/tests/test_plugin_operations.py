from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import (
    HookRegistry,
    HookTrustStore,
    PluginRegistry,
    PluginStateStore,
    build_plugin_operation_catalog,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.asyncio
async def test_plugin_operations_list_enable_disable_and_trust(tmp_path: Path):
    plugin_root = tmp_path / "plugins" / "repo-policy"
    write_json(plugin_root / "plugin.json", {"name": "repo-policy", "version": "0.1.0"})
    write_json(plugin_root / "hooks" / "hooks.json", {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python ok.py"}]}]}
    })
    state = PluginStateStore(tmp_path / "plugin-state.json")
    trust = HookTrustStore(tmp_path / "hook-trust.json")
    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"], state_store=state)

    def hook_registry_factory():
        return HookRegistry(plugins=registry.discover(), trust_store=trust)

    catalog = build_plugin_operation_catalog(
        plugin_registry=registry,
        plugin_state_store=state,
        hook_registry_factory=hook_registry_factory,
        hook_trust_store=trust,
    )

    plugins = await catalog.execute("plugin.list")
    assert plugins.payload["plugins"][0]["name"] == "repo-policy"
    assert plugins.payload["plugins"][0]["enabled"] is True

    await catalog.execute("plugin.disable", {"name": "repo-policy"})
    assert state.is_enabled("repo-policy") is False

    await catalog.execute("plugin.enable", {"name": "repo-policy"})
    assert state.is_enabled("repo-policy") is True

    hooks = await catalog.execute("hook.list")
    hook_id = hooks.payload["hooks"][0]["id"]
    hook_hash = hooks.payload["hooks"][0]["definition_hash"]

    await catalog.execute("hook.trust", {"hook_id": hook_id})
    assert trust.is_trusted(hook_hash) is True


@pytest.mark.asyncio
async def test_websearch_config_save_preserves_urls_in_strings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A URL inside a quoted value must survive JSONC validation — the old
    comment-stripping regex corrupted it into ``https:`` (audit 11)."""
    from lamtools_core.config.root import core_config_file

    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path))
    monkeypatch.setenv("LAMTOOLS_CORE_CONFIG_ROOT", str(tmp_path / "config"))

    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[]),
        plugin_state_store=PluginStateStore(tmp_path / "plugin-state.json"),
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(tmp_path / "hook-trust.json"),
        data_dir=tmp_path,
    )

    content = (
        "{\n"
        '  // 搜索引擎配置\n'
        '  "url": "https://example.com/search?q={query}", /* 注意 URL */\n'
        '  "fallback": "http://127.0.0.1:8080/path//deep"\n'
        "}\n"
    )
    result = await catalog.execute("websearch.config.update", {"content": content})
    assert result.status != "error", result.payload

    # D5：配置迁入插件配置位置 {data_dir}/plugins/websearch.jsonc
    from lamtools_core.plugins.config_store import plugin_config_path

    saved = plugin_config_path(tmp_path, "websearch").read_text(encoding="utf-8")
    assert 'https://example.com/search?q={query}' in saved

    # Round-trip: read back and validate as JSON after comment stripping.
    read = await catalog.execute("websearch.config.get")
    assert read.status != "error"
    import json as _json

    from lamtools_core.plugins.operations import _strip_jsonc_comments
    parsed = _json.loads(_strip_jsonc_comments(read.payload["content"]))
    assert parsed["url"] == "https://example.com/search?q={query}"
    assert parsed["fallback"] == "http://127.0.0.1:8080/path//deep"


@pytest.mark.asyncio
async def test_plugin_config_detect_dirs_case_insensitive(tmp_path: Path):
    """detect-dirs：大小写不敏感识别 docs/Docs/DOCS，缺失目录进 missing，
    命中目录返回工作区相对路径（relative）。"""
    work_root = tmp_path / "ws"
    # 只建一份目录（大小写敏感盘上真实存在的是 "Docs"）
    (work_root / "Docs").mkdir(parents=True)
    (work_root / ".lam" / "docs").mkdir(parents=True)
    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[]),
        plugin_state_store=PluginStateStore(tmp_path / "plugin-state.json"),
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(tmp_path / "hook-trust.json"),
        work_root=work_root,
    )

    result = await catalog.execute(
        "plugin.config.detect-dirs",
        {"dirs": ["docs", "DOCS", "Docs", ".lam/docs", "nodir", "sub/nope"], "case_insensitive": True},
    )
    assert result.status != "error", result.payload

    found = result.payload["found"]
    assert len(found) == 4, found
    # docs/DOCS/Docs 三种写法都命中同一个真实目录
    paths = {item["dir"]: item for item in found}
    assert set(paths) == {"docs", "DOCS", "Docs", ".lam/docs"}
    rels = {item["relative"] for item in found}
    # "Docs" 是磁盘上的真实名字（相对路径还原为真实大小写）
    assert "Docs" in rels
    assert ".lam/docs" in rels
    assert result.payload["missing"] == ["nodir", "sub/nope"]
    # path 是解析后的绝对路径且目录真实存在
    for item in found:
        assert Path(item["path"]).is_dir()

    # 默认 base = work_root（payload 不带 base）
    default = await catalog.execute(
        "plugin.config.detect-dirs",
        {"dirs": ["docs"], "case_insensitive": True},
    )
    assert default.payload["base"] == str(work_root.resolve())
    assert default.payload["found"][0]["relative"] == "Docs"


@pytest.mark.asyncio
async def test_plugin_config_detect_dirs_absolute_and_case_sensitive(tmp_path: Path):
    """detect-dirs：绝对路径直接命中（无 relative）；大小写敏感模式不改写
    大小写不匹配的目录（仅对大小写敏感盘有意义，故只断言契约形状）。"""
    work_root = tmp_path / "ws"
    docs = work_root / "docs"
    docs.mkdir(parents=True)
    # 越界目录：在 work_root 之外，命中时不应有 relative
    outside = tmp_path / "elsewhere" / "shared-docs"
    outside.mkdir(parents=True)
    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[]),
        plugin_state_store=PluginStateStore(tmp_path / "plugin-state.json"),
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(tmp_path / "hook-trust.json"),
        work_root=work_root,
    )

    # 绝对路径：命中且不含 relative（越界）
    abs_result = await catalog.execute(
        "plugin.config.detect-dirs",
        {"dirs": [str(docs), str(outside)], "case_insensitive": True},
    )
    assert abs_result.status != "error"
    by_dir = {item["dir"]: item for item in abs_result.payload["found"]}
    assert len(by_dir) == 2
    assert by_dir[str(docs)]["path"] == str(docs.resolve())
    assert by_dir[str(docs)]["relative"] == "docs"  # 在 base 内 → 有 relative
    assert "relative" not in by_dir[str(outside)]  # 越界 → 仅绝对路径

    # 缺失 + 非法入参
    missing_result = await catalog.execute(
        "plugin.config.detect-dirs",
        {"dirs": ["does-not-exist"], "case_insensitive": True},
    )
    assert missing_result.payload["missing"] == ["does-not-exist"]
    assert missing_result.payload["found"] == []

    bad = await catalog.execute("plugin.config.detect-dirs", {"dirs": "not-a-list"})
    assert bad.status == "error"


@pytest.mark.asyncio
async def test_plugin_config_get_returns_work_root(tmp_path: Path):
    """plugin.config.get 附带 work_root，供前端把浏览选中的绝对路径转成
    工作区相对路径。"""
    plugin_root = tmp_path / "plugins" / "demo"
    write_json(plugin_root / "plugin.json", {"name": "demo", "version": "0.1.0"})
    write_json(plugin_root / "config" / "schema.jsonc", {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    })
    work_root = tmp_path / "ws"
    work_root.mkdir()
    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[tmp_path / "plugins"], state_store=PluginStateStore(tmp_path / "plugin-state.json")),
        plugin_state_store=PluginStateStore(tmp_path / "plugin-state.json"),
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(tmp_path / "hook-trust.json"),
        work_root=work_root,
        data_dir=tmp_path,
    )

    result = await catalog.execute("plugin.config.get", {"name": "demo"})
    assert result.status != "error", result.payload
    assert result.payload["work_root"] == str(work_root)
