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

    saved = core_config_file("websearch.jsonc").read_text(encoding="utf-8")
    assert 'https://example.com/search?q={query}' in saved

    # Round-trip: read back and validate as JSON after comment stripping.
    read = await catalog.execute("websearch.config.get")
    assert read.status != "error"
    import json as _json

    from lamtools_core.plugins.operations import _strip_jsonc_comments
    parsed = _json.loads(_strip_jsonc_comments(read.payload["content"]))
    assert parsed["url"] == "https://example.com/search?q={query}"
    assert parsed["fallback"] == "http://127.0.0.1:8080/path//deep"
