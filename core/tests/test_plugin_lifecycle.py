"""生命周期测试：依赖解析/探测 / 配置读写校验 / 安装与卸载操作 /
模型可调管理工具 / 依赖缺失占位 handler。

user:“删 v1 成单一系统”+全部走统一操作目录（plugin.system.* 与旧名别名）；
v1 安装适配器（zip 内部安全解压、GitHub URL 解析）随 install.py 退役，
链接安装在插件页完整化一步补齐。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from lamtools_core.plugin_system.deps import (
    check_dependencies,
    dry_run_install,
    install_dependencies,
    parse_requirement,
)
from lamtools_core.plugin_system.manager_tools import (
    PLUGIN_DEPS_TOOL,
    PLUGIN_INSTALL_TOOL,
    PLUGIN_LIST_TOOL,
    plugin_manager_tool_handlers,
    plugin_manager_tool_specs,
)
from lamtools_core.plugin_system.plugin_data import (
    merged_with_defaults,
    plugin_config_path,
    read_plugin_config,
    validate_config,
    write_plugin_config,
)
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
    from lamtools_core.plugin_system.deps import validated_requirements

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

    monkeypatch.setattr("lamtools_core.plugin_system.deps.run_subprocess", fake_run_subprocess)

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

    monkeypatch.setattr("lamtools_core.plugin_system.deps.run_subprocess", fake_run_subprocess)

    ok, conflicts, detail = await dry_run_install(["-r", "/tmp/requirements.txt"], cwd=tmp_path)

    assert ok is False
    assert conflicts == []
    assert "invalid requirement" in detail
    assert calls == []


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



# ── 统一操作目录：安装 / 列表 / 卸载 / 依赖状态 ─────────────────────

@pytest.fixture()
def lifecycle(tmp_path):
    from lamtools_core.app.base_agent import build_core_plugin_operation_catalog

    roots = tmp_path / "roots"
    roots.mkdir()
    data_dir = tmp_path / "data"
    catalog = build_core_plugin_operation_catalog(
        data_dir=data_dir,
        work_root=tmp_path / "work",
        plugin_roots=[roots],
        start_lifecycle=False,
    )
    return catalog, data_dir, roots


def _make_plugin_dir(tmp_path, name="demo-plugin", version="1.0.0", *, deps=None):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version}
    if deps:
        manifest["dependencies"] = deps
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


async def test_plugin_install_local_then_list_then_uninstall(lifecycle, tmp_path):
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="demo-plugin")

    installed = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})
    assert installed.status == "ok", installed.payload
    assert (roots / "demo-plugin" / "plugin.json").exists()

    listed = await catalog.execute("plugin.list")
    names = {item["name"] for item in listed.payload["plugins"]}
    assert "demo-plugin" in names

    removed = await catalog.execute("plugin.uninstall", {"name": "demo-plugin", "keep_data": False})
    assert removed.status == "ok", removed.payload
    assert not (roots / "demo-plugin").exists()


async def test_plugin_install_zip_source(lifecycle, tmp_path):
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="zipped-plugin")
    archive = tmp_path / "zipped-plugin.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(src / "plugin.json", "plugin.json")

    result = await catalog.execute("plugin.install", {"source": "zip", "path": str(archive)})

    assert result.status == "ok", result.payload
    assert (roots / "zipped-plugin" / "plugin.json").exists()


async def test_plugin_deps_status(lifecycle, tmp_path):
    catalog, _data_dir, _roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="needy", deps=["json", "no-such-pkg-xyz"])
    await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    result = await catalog.execute("plugin.deps-status", {"name": "needy"})

    assert result.status == "ok"
    by_name = {item["name"]: item["status"] for item in result.payload["dependencies"]}
    assert by_name["json"] == "ok"
    assert by_name["no-such-pkg-xyz"] == "missing"
    assert result.payload["missing"] == 1


async def test_skill_create_roundtrip(lifecycle, tmp_path, monkeypatch):
    """skill.create：标题/描述/内容 → 用户级 SKILL.md → skill.list 可见。"""
    catalog, _data_dir, _roots = lifecycle
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

    dup = await catalog.execute("skill.create", {
        "name": "my-skill", "description": "x", "content": "y",
    })
    assert dup.status == "error"

    missing = await catalog.execute("skill.create", {"name": "", "description": "x", "content": "y"})
    assert missing.status == "error"
    bad_name = await catalog.execute("skill.create", {"name": "bad name!", "description": "x", "content": "y"})
    assert bad_name.status == "error"


async def test_plugin_install_refuses_a_wrong_engine_platform(lifecycle, tmp_path):
    """user:“环境不满足就拒绝并说清哪一条”+engine.platform 不匹配在安装
    这一步报错，插件根里不留东西。"""
    catalog, _data_dir, roots = lifecycle
    src = _make_plugin_dir(tmp_path, name="phone-only")
    manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
    manifest["engine"] = {"platform": "linux-arm64"}
    (src / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = await catalog.execute("plugin.install", {"source": "local", "path": str(src)})

    assert result.status == "error"
    assert "requires platform linux-arm64" in result.payload["error"]
    assert [item.name for item in roots.iterdir()] == []


# ── 依赖缺失占位 handler（toolbox 集成） ──────────────────────────

async def test_toolbox_missing_dependency_placeholder(tmp_path, monkeypatch):
    from lamtools_core.plugin_system.capabilities import PluginToolSpec
    from lamtools_core.plugin_system.runtime import _tool_spec
    from lamtools_core.tool.default_toolbox import build_core_toolbox

    spec = _tool_spec(
        PluginToolSpec(
            name="dep_tool",
            permission="auto_allow",
            handler="x:y",
            plugin="needy",
            plugin_root=str(tmp_path),
        ),
        dependencies=("no-such-pkg-xyz",),
    )
    toolbox = build_core_toolbox(work_root=tmp_path, plugin_tool_specs=[spec])
    call = ToolCall(id="c1", name="dep_tool", arguments={})
    result = await toolbox.execute(call)
    assert result.status == "failed"
    assert "missing dependencies" in (result.error or "")
    assert "pip install" in (result.error or "")
    assert "no-such-pkg-xyz" in toolbox._plugin_handler_errors["dep_tool"]
