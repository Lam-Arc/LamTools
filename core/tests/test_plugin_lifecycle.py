"""S2 生命周期测试：依赖解析/探测 / 安全解压 / URL 解析 / 安装通道 /
配置读写校验 / 新 operation / 模型可调管理工具 / 依赖缺失占位 handler。
"""
from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from lamtools_core.plugins.config_store import (
    merged_with_defaults,
    plugin_config_path,
    read_plugin_config,
    validate_config,
    write_plugin_config,
)
from lamtools_core.plugins.deps import (
    check_dependencies,
    dry_run_install,
    install_dependencies,
    parse_requirement,
)
from lamtools_core.plugins.install import (
    install_from_directory,
    parse_github_release_url,
    safe_extract_zip,
    uninstall_plugin_directory,
)
from lamtools_core.plugins.manager_tools import (
    PLUGIN_DEPS_TOOL,
    PLUGIN_INSTALL_TOOL,
    PLUGIN_LIST_TOOL,
    plugin_manager_tool_handlers,
    plugin_manager_tool_specs,
)
from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore
from lamtools_core.tool import ToolCall


# ── 依赖解析 / 探测 ───────────────────────────────────────────────

def test_parse_requirement():
    req = parse_requirement("sqlite-vec>=0.1.9")
    assert req.name == "sqlite-vec"
    assert req.operator == ">="
    assert req.version == "0.1.9"
    assert parse_requirement("httpx").operator == ""
    assert parse_requirement("pkg==1.2.3").version == "1.2.3"
    assert parse_requirement("bad req!!") is None


def test_check_dependencies_real_packages():
    # httpx 是 core 依赖，必然已装；不存在的包报缺失
    result = check_dependencies(["httpx", "definitely-not-a-real-pkg-xyz"])
    assert result["status"] == "missing"
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["httpx"]["ok"] is True
    assert by_name["definitely-not-a-real-pkg-xyz"]["ok"] is False
    assert result["missing"] == ["definitely-not-a-real-pkg-xyz"]
    # 版本约束
    satisfied = check_dependencies(["httpx>=0.20"])
    assert satisfied["status"] == "ok"


# ── 依赖串不得变成 pip 参数（2026-09-25 审计 P2：清单可注入 --index-url）──

def test_validated_requirements_strips_pip_flags():
    from lamtools_core.plugins.deps import validated_requirements

    valid, invalid = validated_requirements([
        "requests>=2.0",
        "--index-url=https://evil.example/simple",
        "-r",
        "/tmp/requirements.txt",
        "--target=..",
        "pkg name",
    ])

    assert valid == ["requests>=2.0"]
    assert invalid == [
        "--index-url=https://evil.example/simple",
        "-r",
        "/tmp/requirements.txt",
        "--target=..",
        "pkg name",
    ]


async def test_install_dependencies_refuses_flag_injection(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    async def fake_run_subprocess(argv, *, cwd, timeout, **kwargs):
        calls.append(list(argv))
        raise AssertionError("pip must not be invoked for an invalid dependency list")

    monkeypatch.setattr("lamtools_core.plugins.deps.run_subprocess", fake_run_subprocess)

    ok, detail = await install_dependencies(
        ["--index-url=https://evil.example/simple", "requests>=2.0"],
        cwd=tmp_path,
    )

    assert ok is False
    assert "invalid requirement" in detail
    assert calls == []


async def test_dry_run_install_refuses_flag_injection(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    async def fake_run_subprocess(argv, *, cwd, timeout, **kwargs):
        calls.append(list(argv))
        raise AssertionError("pip must not be invoked for an invalid dependency list")

    monkeypatch.setattr("lamtools_core.plugins.deps.run_subprocess", fake_run_subprocess)

    ok, conflicts, detail = await dry_run_install(["-r", "/tmp/requirements.txt"], cwd=tmp_path)

    assert ok is False
    assert conflicts == []
    assert "invalid requirement" in detail
    assert calls == []


# ── 安全解压 / URL 解析 ───────────────────────────────────────────

def test_safe_extract_zip_ok(tmp_path):
    archive = tmp_path / "p.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("plugin.json", '{"name":"p","version":"1.0.0"}')
        zf.writestr("tools/tools.jsonc", '{"tools":[]}')
    target = tmp_path / "out"
    safe_extract_zip(archive, target)
    assert (target / "plugin.json").exists()
    assert (target / "tools" / "tools.jsonc").exists()


def test_safe_extract_zip_escape_blocked(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "boom")
    with pytest.raises(ValueError, match="escapes"):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_zip_entry_limit(tmp_path):
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for i in range(3000):
            zf.writestr(f"f{i}.txt", "x")
    with pytest.raises(ValueError, match="too many entries"):
        safe_extract_zip(archive, tmp_path / "out")


def test_parse_github_release_url():
    parsed = parse_github_release_url(
        "https://github.com/lamtools/lamtools-rag/releases/download/v0.1.0/rag-plugin.zip"
    )
    assert parsed == {"owner": "lamtools", "repo": "lamtools-rag", "tag": "v0.1.0", "asset": "rag-plugin.zip"}
    parsed_latest = parse_github_release_url(
        "https://github.com/a/b/releases/latest/download/x.zip"
    )
    assert parsed_latest["tag"] == "latest"
    assert parse_github_release_url("https://example.com/foo.zip") is None


def test_install_from_directory_and_uninstall(tmp_path):
    src = tmp_path / "src-plugin"
    src.mkdir()
    (src / "plugin.json").write_text('{"name":"demo","version":"1.0.0"}', encoding="utf-8")
    root = tmp_path / "plugins"
    install_from_directory(src, root / "demo")
    assert (root / "demo" / "plugin.json").exists()
    # 重装即更新：覆盖旧目录
    (src / "plugin.json").write_text('{"name":"demo","version":"2.0.0"}', encoding="utf-8")
    install_from_directory(src, root / "demo")
    assert '"2.0.0"' in (root / "demo" / "plugin.json").read_text(encoding="utf-8")
    # 卸载
    uninstall_plugin_directory(root / "demo")
    assert not (root / "demo").exists()


# ── 安装路径边界（2026-09-25 审计 P1：清单 name 目录穿越）────────────

def test_install_from_directory_refuses_source_inside_target(tmp_path):
    root = tmp_path / "plugins"
    target = root / "demo"
    src = target / "inner"
    src.mkdir(parents=True)
    with pytest.raises(ValueError, match="inside its own target"):
        install_from_directory(src, target)


def test_install_from_directory_refuses_target_outside_root(tmp_path):
    src = tmp_path / "src-plugin"
    src.mkdir()
    with pytest.raises(ValueError, match="escapes the plugin root"):
        install_from_directory(src, tmp_path / "elsewhere", root=tmp_path / "plugins")


def test_uninstall_refuses_target_outside_root(tmp_path):
    target = tmp_path / "not-a-plugin-root" / "demo"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="outside the plugin root"):
        uninstall_plugin_directory(target, root=tmp_path / "plugins")
    assert target.exists()


@pytest.mark.parametrize(
    "bad_name",
    ["../victim", "..", ".", "nested/dir", "C:evil", "back\\slash"],
)
async def test_plugin_install_rejects_escaping_manifest_name(lifecycle, tmp_path, bad_name):
    """清单身份必须是单个安全路径段：拒绝且不触碰插件根之外的任何东西。"""
    catalog, _data_dir, roots = lifecycle
    victim = tmp_path / "victim"
    victim.mkdir()
    marker = victim / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    src = _make_plugin_dir(tmp_path, name="placeholder")
    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    manifest["name"] = bad_name
    (src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    assert result.status == "error"
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "plug").exists()
    assert not any(item.name.startswith(".install-") for item in roots.iterdir())
    # 插件根内不应出现任何以该非法名命名的条目
    assert [item.name for item in roots.iterdir()] == []


async def test_plugin_install_uses_id_for_the_directory_and_name_for_display(lifecycle, tmp_path):
    """``id`` 是规范身份（目录名），``name`` 是显示名（可含空格）。"""
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="placeholder")
    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    manifest["id"] = "alpha"
    manifest["name"] = "Display Alpha"
    (src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    assert result.status == "ok"
    assert (roots / "alpha" / "plugin.json").exists()
    assert not (roots / "Display Alpha").exists()
    listed = await catalog.execute("plugin.list")
    entry = next(item for item in listed.payload["plugins"] if item["id"] == "alpha")
    assert entry["name"] == "Display Alpha"


async def test_plugin_install_zip_rejects_escaping_manifest_name(lifecycle, tmp_path):
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="zip-traversal")
    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    manifest["name"] = "../victim-zip"
    (src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    archive = tmp_path / "zip-traversal.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for file in src.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src))
    victim = tmp_path / "victim-zip"
    victim.mkdir()

    result = await catalog.execute("plugin.install", {"source": "zip", "path": str(archive)})

    assert result.status == "error"
    assert victim.exists()
    assert [item.name for item in roots.iterdir()] == []


def test_registry_reports_unsafe_manifest_name(tmp_path):
    """带路径语义的 name 被跳过（其余插件照常加载），错误经 discover_errors 可见。"""
    root = tmp_path / "plugins"
    good = root / "good-plugin"
    good.mkdir(parents=True)
    (good / "plugin.json").write_text('{"name":"good-plugin"}', encoding="utf-8")
    bad = root / "bad-plugin"
    bad.mkdir(parents=True)
    (bad / "plugin.json").write_text('{"name":"../escape"}', encoding="utf-8")

    registry = PluginRegistry(plugin_roots=[root])

    names = [item.name for item in registry.discover()]
    assert names == ["good-plugin"]
    assert len(registry.discover_errors) == 1
    assert "invalid plugin name" in registry.discover_errors[0]["error"]


def test_registry_accepts_a_display_name_with_spaces(tmp_path):
    """显示名允许空格（插件身份靠 id），但不得带路径语义。"""
    root = tmp_path / "plugins"
    plugin = root / "alpha"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"id": "alpha", "name": "Display Alpha"}), encoding="utf-8"
    )

    registry = PluginRegistry(plugin_roots=[root])

    items = registry.discover()
    assert [(item.id, item.name) for item in items] == [("alpha", "Display Alpha")]
    assert registry.discover_errors == []



# ── 插件配置存储 / 校验 ────────────────────────────────────────────

def test_config_store_roundtrip(tmp_path):
    write_plugin_config(tmp_path, "demo", {"embeddingSource": "local"})
    assert read_plugin_config(tmp_path, "demo") == {"embeddingSource": "local"}
    assert plugin_config_path(tmp_path, "demo").exists()


def test_validate_config():
    schema = {
        "type": "object",
        "properties": {
            "embeddingSource": {"type": "string", "enum": ["local", "api"]},
            "topK": {"type": "integer"},
            "autoRoots": {"type": "array", "items": {"type": "string"}},
            "debug": {"type": "boolean"},
        },
    }
    assert validate_config({"embeddingSource": "local", "topK": 10}, schema) == []
    errors = validate_config({"embeddingSource": "remote"}, schema)
    assert any("embeddingSource" in e for e in errors)
    errors = validate_config({"topK": "ten"}, schema)
    assert any("topK" in e for e in errors)
    # 未知键忽略
    assert validate_config({"unknownKey": 1}, schema) == []


def test_merged_with_defaults():
    schema = {
        "properties": {
            "embeddingSource": {"type": "string", "default": "local"},
            "topK": {"type": "integer", "default": 10},
        }
    }
    merged = merged_with_defaults({"topK": 5}, schema)
    assert merged == {"topK": 5, "embeddingSource": "local"}


# ── 新 operation：install / uninstall / config / deps-status ──────

@pytest.fixture()
def lifecycle(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugins.operations import build_plugin_operation_catalog

    roots = tmp_path / "roots"
    roots.mkdir()
    data_dir = tmp_path / "data"
    state_store = PluginStateStore(data_dir / "plugins.jsonc")
    registry = PluginRegistry(plugin_roots=[roots], state_store=state_store)

    catalog = build_plugin_operation_catalog(
        plugin_registry=registry,
        plugin_state_store=state_store,
        hook_registry_factory=lambda: None,
        hook_trust_store=type("T", (), {"untrust": lambda self, h: None, "trusted_hashes": lambda self: []})(),
        work_root=tmp_path / "work",
        data_dir=data_dir,
        install_root=roots,
    )
    return catalog, data_dir, roots


def _make_plugin_dir(tmp_path, name="demo-plugin", version="1.0.0", *, tools=None, deps=None, schema=None):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version}
    if deps:
        manifest["dependencies"] = deps
    if tools is not None:
        (root / "tools").mkdir(exist_ok=True)
        (root / "tools" / "tools.jsonc").write_text(json.dumps({"tools": tools}), encoding="utf-8")
        manifest["tools"] = ["./tools/tools.jsonc"]
    if schema is not None:
        (root / "config").mkdir(exist_ok=True)
        (root / "config" / "schema.jsonc").write_text(json.dumps(schema), encoding="utf-8")
        manifest["configSchema"] = ["./config/schema.jsonc"]
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


async def test_plugin_install_local_then_list_then_uninstall(lifecycle, tmp_path):
    catalog, data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, tools=[{"name": "demo_tool", "handler": "x:y"}])
    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})
    assert result.status == "ok"
    assert result.payload["name"] == "demo-plugin"
    assert result.payload["installed"] is True
    assert (roots / "demo-plugin" / "plugin.json").exists()

    listed = await catalog.execute("plugin.list")
    names = [item["name"] for item in listed.payload["plugins"]]
    assert "demo-plugin" in names
    plugin = next(item for item in listed.payload["plugins"] if item["name"] == "demo-plugin")
    assert plugin["version"] == "1.0.0"
    assert plugin["tools"][0]["tools"][0]["name"] == "demo_tool"

    uninstalled = await catalog.execute("plugin.uninstall", {"name": "demo-plugin"})
    assert uninstalled.payload["uninstalled"] is True
    assert not (roots / "demo-plugin").exists()


async def test_plugin_install_zip_source(lifecycle, tmp_path):
    catalog, data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="zip-plugin")
    archive = tmp_path / "zip-plugin.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for file in src.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src.parent))
    result = await catalog.execute("plugin.install", {"source": "zip", "path": str(archive)})
    assert result.status == "ok"
    assert result.payload["name"] == "zip-plugin"
    assert (roots / "zip-plugin" / "plugin.json").exists()


async def test_plugin_install_conflict_dependency_rolls_back(lifecycle, tmp_path, monkeypatch):
    catalog, data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, deps=["some-pkg>=1.0"])

    async def fake_dry_run(deps, *, cwd):
        return False, ["some-pkg"], "Would upgrade some-pkg"

    monkeypatch.setattr("lamtools_core.plugins.deps.dry_run_install", fake_dry_run)
    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})
    assert result.status == "error"
    assert "conflict" in result.payload["error"]
    assert not (roots / "demo-plugin").exists()  # 回滚：目录已删


async def test_plugin_deps_status(lifecycle, tmp_path):
    catalog, data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, deps=["httpx>=0.20", "no-such-pkg-xyz"])
    await catalog.execute("plugin.install", {"source": "local", "path": str(src)})
    result = await catalog.execute("plugin.deps-status", {"name": "demo-plugin"})
    assert result.status == "ok"
    assert result.payload["status"] == "missing"
    assert "no-such-pkg-xyz" in result.payload["missing"]
    assert "pip install" in result.payload["install_hint"]


async def test_plugin_config_get_update_validation(lifecycle, tmp_path):
    catalog, data_dir, roots = lifecycle
    schema = {"type": "object", "properties": {"embeddingSource": {"type": "string", "enum": ["local", "api"], "default": "local"}}}
    src = _make_plugin_dir(tmp_path, schema=schema)
    await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    got = await catalog.execute("plugin.config.get", {"name": "demo-plugin"})
    assert got.payload["config"] == {"embeddingSource": "local"}  # 默认值合并
    assert got.payload["schema"]["properties"]["embeddingSource"]["enum"] == ["local", "api"]

    ok = await catalog.execute("plugin.config.update", {"name": "demo-plugin", "config": {"embeddingSource": "api"}})
    assert ok.status == "ok"
    assert read_plugin_config(data_dir, "demo-plugin") == {"embeddingSource": "api"}

    bad = await catalog.execute("plugin.config.update", {"name": "demo-plugin", "config": {"embeddingSource": "remote"}})
    assert bad.status == "error"
    assert "validation failed" in bad.payload["error"]


# ── 模型可调管理工具 ──────────────────────────────────────────────

def test_plugin_manager_tool_specs_permissions():
    specs = {spec.name: spec for spec in plugin_manager_tool_specs()}
    assert specs[PLUGIN_INSTALL_TOOL].permission == "ask_user"
    assert specs[PLUGIN_DEPS_TOOL].permission == "auto_allow"
    assert specs[PLUGIN_LIST_TOOL].permission == "auto_allow"


async def test_plugin_manager_handlers_map_operations():
    captured = {}

    async def fake_execute(name, payload, metadata):
        captured["name"] = name
        captured["payload"] = payload
        from lamtools_core.app import OperationResult
        return OperationResult(name=name, payload={"ok": True})

    handlers = plugin_manager_tool_handlers(fake_execute, work_root="C:/w")
    call = ToolCall(id="c1", name=PLUGIN_INSTALL_TOOL, arguments={"source": "local", "path": "C:/p"})
    result = await handlers[PLUGIN_INSTALL_TOOL](call)
    assert captured["name"] == "plugin.install"
    assert captured["payload"]["path"] == "C:/p"
    assert result.status == "ok"


# ── 依赖缺失占位 handler（toolbox 集成） ──────────────────────────

async def test_toolbox_missing_dependency_placeholder(tmp_path, monkeypatch):
    from lamtools_core.plugins.models import PluginToolSpec
    from lamtools_core.plugins.tools import complete_plugin_tool_specs
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    specs = complete_plugin_tool_specs(
        [PluginToolSpec(name="dep_tool", permission="auto_allow", handler="x:y")],
        plugin_name="needy",
        plugin_root=tmp_path,
        dependencies=["no-such-pkg-xyz"],
    )
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=specs)
    call = ToolCall(id="c1", name="dep_tool", arguments={})
    result = await toolbox.execute(call)
    assert result.status == "failed"
    assert "missing dependencies" in (result.error or "")
    assert "pip install" in (result.error or "")
    assert "no-such-pkg-xyz" in toolbox._plugin_handler_errors["dep_tool"]


async def test_plugin_config_secret_masking(lifecycle, tmp_path):
    """密钥字段（api_key）回显打码；掩码提交保留原值。"""
    catalog, data_dir, roots = lifecycle
    schema = {"type": "object", "properties": {
        "api_key": {"type": "string"},
        "model": {"type": "string"},
    }}
    src = _make_plugin_dir(tmp_path, schema=schema)
    await catalog.execute("plugin.install", {"source": "local", "path": str(src)})
    await catalog.execute("plugin.config.update", {"name": "demo-plugin", "config": {"api_key": "sk-real-123", "model": "m1"}})

    got = await catalog.execute("plugin.config.get", {"name": "demo-plugin"})
    assert got.payload["config"]["api_key"] == "********"  # 打码
    assert got.payload["has_secrets"] is True
    assert got.payload["config"]["model"] == "m1"  # 非密钥字段原样

    # 掩码提交 → 保留原值
    kept = await catalog.execute("plugin.config.update", {"name": "demo-plugin", "config": {"api_key": "********", "model": "m2"}})
    assert kept.payload["config"]["api_key"] == "sk-real-123"
    after = await catalog.execute("plugin.config.get", {"name": "demo-plugin"})
    assert after.payload["config"]["model"] == "m2"
    # 真值提交 → 覆盖
    replaced = await catalog.execute("plugin.config.update", {"name": "demo-plugin", "config": {"api_key": "sk-new"}})
    assert replaced.payload["config"]["api_key"] == "sk-new"


async def test_plugin_list_asset_details(lifecycle, tmp_path):
    """plugin.list 返回具体技能名与钩子事件摘要（配置卡片展示用）。"""
    catalog, data_dir, roots = lifecycle
    # 插件带 skills + hooks
    src = tmp_path / "asset-plugin"
    (src / "skills" / "demo-skill").mkdir(parents=True)
    (src / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: d\n---\nbody", encoding="utf-8"
    )
    (src / "skills" / "other").mkdir(parents=True)
    (src / "skills" / "other" / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: o\n---\nbody", encoding="utf-8"
    )
    (src / "hooks").mkdir()
    (src / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {
            "PreToolUse": [{"matcher": "read_file", "hooks": [{"type": "command", "command": "echo x"}]}],
            "SessionStart": [{"matcher": "*", "hooks": [{"type": "prompt", "prompt": "hi"}]}],
        }}),
        encoding="utf-8",
    )
    (src / "plugin.json").write_text(json.dumps({
        "name": "asset-plugin", "version": "1.0.0",
        "skills": ["./skills"], "hooks": ["./hooks/hooks.json"],
    }), encoding="utf-8")
    await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    listed = await catalog.execute("plugin.list")
    plugin = next(p for p in listed.payload["plugins"] if p["name"] == "asset-plugin")
    assert plugin["skill_names"] == ["demo-skill", "other-skill"]
    assert len(plugin["hook_summary"]) == 2
    by_event = {h["event"]: h for h in plugin["hook_summary"]}
    assert by_event["PreToolUse"]["matcher"] == "read_file"
    assert by_event["PreToolUse"]["type"] == "command"
    assert by_event["SessionStart"]["type"] == "prompt"


async def test_skill_create_roundtrip(lifecycle, tmp_path, monkeypatch):
    """skill.create：标题/描述/内容 → 用户级 SKILL.md → skill.list 可见。"""
    catalog, data_dir, roots = lifecycle
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "lamhome"))

    result = await catalog.execute("skill.create", {
        "name": "my-skill", "description": "我的技能", "content": "这是正文",
    })
    assert result.status == "ok", result.payload
    assert result.payload["created"] is True
    md = (tmp_path / "lamhome" / "skills" / "my-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: my-skill" in md
    assert "description: 我的技能" in md
    assert "这是正文" in md

    # 重名拒绝
    dup = await catalog.execute("skill.create", {
        "name": "my-skill", "description": "x", "content": "y",
    })
    assert dup.status == "error"

    # 校验必填与名字字符集
    missing = await catalog.execute("skill.create", {"name": "", "description": "x", "content": "y"})
    assert missing.status == "error"
    bad_name = await catalog.execute("skill.create", {"name": "bad name!", "description": "x", "content": "y"})
    assert bad_name.status == "error"


async def test_plugin_install_refuses_a_plugin_for_another_platform(lifecycle, tmp_path):
    """分类不是本机的插件装上也跑不起来，所以在安装这一步就说清楚。

    发现阶段的过滤是静的（插件页不会出现它），因此这里必须报错而不是静默装进去。
    """
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="phone-only")
    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    manifest["platforms"] = "mobile"
    (src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    assert result.status == "error"
    assert "platforms='mobile'" in result.payload["error"]
    # 拒绝要干净：插件根里不留任何东西。
    assert [item.name for item in roots.iterdir()] == []


async def test_plugin_install_accepts_a_plugin_for_this_platform(lifecycle, tmp_path):
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="desktop-tool")
    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    manifest["platforms"] = "desktop"
    (src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    assert result.status == "ok"
    assert (roots / "desktop-tool" / "plugin.json").exists()
