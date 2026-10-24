"""运行档（run profile）验收：清单解析 / 名字解析 / 宿主强制 / 预算。

user:“给拉起的会话完整定义任意工具面与运行档是第一类缺口”+profiles 段
声明四件套，宿主按声明强制：白名单内自动、白名单外拒绝、预算超限终止。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system import (
    PluginHost,
    apply_profile,
    available_profiles,
    read_profiles,
    resolve_profile,
)
from lamtools_core.plugin_system.capabilities import PluginToolSpec
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.runtime import _tool_spec
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


def _write_plugin(root: Path, name: str, manifest: dict) -> Path:
    plugin = root / name
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return plugin / "plugin.json"


def _host(root: Path) -> PluginHost:
    return PluginHost(roots=[root], state_path=root.parent / "plugin-system.jsonc")


def _echo_handler(tag: str):
    from lamtools_core.tool import ToolResult

    async def handler(call: ToolCall):
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content=tag,
        )

    return handler


# ── 清单解析 ─────────────────────────────────────────────────────────


def test_read_profiles_parses_the_full_declaration(tmp_path: Path) -> None:
    manifest_path = _write_plugin(
        tmp_path,
        "demo",
        {
            "name": "demo",
            "version": "1.0.0",
            "profiles": {
                "duty": {
                    "title": "值班轮",
                    "tools": ["search", "report"],
                    "approval": "auto",
                    "modelScene": "background",
                    "budget": {"maxToolCalls": 120, "maxTokens": 300000},
                }
            },
        },
    )
    specs = read_profiles(load_manifest(manifest_path))

    assert set(specs) == {"duty"}
    spec = specs["duty"]
    assert spec.full_name == "demo:duty"
    assert spec.tools == ("search", "report")
    assert spec.approval == "auto"
    assert spec.model_scene == "background"
    assert spec.budget.max_tool_calls == 120
    assert spec.budget.max_tokens == 300000


@pytest.mark.parametrize(
    "profiles, fragment",
    [
        ({"duty": {"tools": []}}, "non-empty tools"),
        ({"duty": {"tools": ["search"], "approval": "yolo"}}, "approval must be one of"),
        ({"duty": {"tools": ["search"], "budget": {"maxToolCalls": -1}}}, "positive integer"),
        ({"bad name": {"tools": ["search"]}}, "one token"),
    ],
)
def test_read_profiles_rejects_bad_declarations(
    tmp_path: Path, profiles: dict, fragment: str
) -> None:
    manifest_path = _write_plugin(
        tmp_path, "demo", {"name": "demo", "version": "1.0.0", "profiles": profiles}
    )
    with pytest.raises(Exception, match=fragment):
        read_profiles(load_manifest(manifest_path))


# ── 名字解析 ─────────────────────────────────────────────────────────


def test_resolve_by_full_name_and_unique_short_name(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    _write_plugin(root, "alpha", {"name": "alpha", "version": "1.0.0", "profiles": {"duty": {"tools": ["a"]}}})
    _write_plugin(root, "beta", {"name": "beta", "version": "1.0.0", "profiles": {"night": {"tools": ["b"]}}})
    manifests = _host(root).discover()

    exact = resolve_profile(manifests, "alpha:duty")
    assert exact.plugin == "alpha"
    short = resolve_profile(manifests, "duty")
    assert short.full_name == "alpha:duty"
    assert [spec.full_name for spec in available_profiles(manifests)] == [
        "alpha:duty",
        "beta:night",
    ]


def test_resolve_reports_ambiguity_and_unknown(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    _write_plugin(root, "alpha", {"name": "alpha", "version": "1.0.0", "profiles": {"duty": {"tools": ["a"]}}})
    _write_plugin(root, "beta", {"name": "beta", "version": "1.0.0", "profiles": {"duty": {"tools": ["b"]}}})
    manifests = _host(root).discover()

    with pytest.raises(ValueError, match="ambiguous"):
        resolve_profile(manifests, "duty")
    with pytest.raises(ValueError, match="available profiles"):
        resolve_profile(manifests, "nope")


def test_disabled_plugin_profiles_are_not_resolvable(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    _write_plugin(root, "off", {"name": "off", "version": "1.0.0", "profiles": {"duty": {"tools": ["a"]}}})
    host = _host(root)
    host.disable("off")

    with pytest.raises(ValueError, match="not found"):
        resolve_profile(host.discover(), "duty")


# ── 宿主强制：白名单 fail closed / 审批覆盖 / 预算 ────────────────────


def _stub_toolbox(tmp_path: Path) -> object:
    specs = [
        _tool_spec(
            PluginToolSpec(
                name=name,
                permission="ask_user",
                handler=f"mod:{name}",
                plugin="demo",
                plugin_root=str(tmp_path),
            )
        )
        for name in ("in_tool", "out_tool", "secret_tool")
    ]
    handlers = {
        "in_tool": _echo_handler("in"),
        "out_tool": _echo_handler("out"),
        "secret_tool": _echo_handler("secret"),
    }
    return build_core_toolbox(
        work_root=tmp_path,
        plugin_tool_specs=specs,
        plugin_tool_handlers=handlers,
    )


@pytest.mark.asyncio
async def test_apply_profile_whitelist_is_fail_closed(tmp_path: Path) -> None:
    from lamtools_core.plugin_system.profiles import ProfileBudget, ProfileSpec

    spec = ProfileSpec(
        full_name="demo:duty",
        plugin="demo",
        profile="duty",
        tools=("in_tool",),
        budget=ProfileBudget(),
    )
    toolbox = _stub_toolbox(tmp_path)
    apply_profile(toolbox, spec)

    # user:“白名单管模型可见面”+配置面（tool_specs）显示全集，模型面收窄。
    model_visible = {
        item["function"]["name"] for item in toolbox.model_tools()
    }
    assert "in_tool" in model_visible
    assert not ({"out_tool", "secret_tool"} & model_visible)

    blocked = await toolbox.execute(ToolCall(id="c1", name="out_tool", arguments={}))
    # user:“白名单外自动拒绝”+宿主的白名单拒绝语义是 status=blocked。
    assert blocked.status == "blocked"

    allowed = await toolbox.execute(ToolCall(id="c2", name="in_tool", arguments={}))
    assert allowed.status == "ok"


@pytest.mark.asyncio
async def test_apply_profile_approval_override(tmp_path: Path) -> None:
    from lamtools_core.plugin_system.profiles import ProfileBudget, ProfileSpec

    spec = ProfileSpec(
        full_name="demo:duty",
        plugin="demo",
        profile="duty",
        tools=("in_tool", "secret_tool"),
        approval="auto",
        budget=ProfileBudget(),
    )
    toolbox = _stub_toolbox(tmp_path)
    apply_profile(toolbox, spec)

    call = toolbox.prepare_call(ToolCall(id="c1", name="secret_tool", arguments={}))
    # user:“无人值守 = 白名单内自动放行”+ask_user 工具在运行档内不再逐次询问。
    assert call.requires_approval is False


@pytest.mark.asyncio
async def test_apply_profile_budget_exhaustion(tmp_path: Path) -> None:
    from lamtools_core.plugin_system.profiles import ProfileBudget, ProfileSpec

    spec = ProfileSpec(
        full_name="demo:duty",
        plugin="demo",
        profile="duty",
        tools=("in_tool",),
        budget=ProfileBudget(max_tool_calls=2),
    )
    toolbox = _stub_toolbox(tmp_path)
    apply_profile(toolbox, spec)

    await toolbox.execute(ToolCall(id="c1", name="in_tool", arguments={}))
    await toolbox.execute(ToolCall(id="c2", name="in_tool", arguments={}))
    exhausted = await toolbox.execute(ToolCall(id="c3", name="in_tool", arguments={}))

    # user:“预算超限终止”+超限后所有后续调用都收到预算耗尽错误。
    assert exhausted.status == "failed"
    assert "预算耗尽" in (exhausted.error or "")


# ── 真实声明：bili-scroll 的值班档 ───────────────────────────────────


def test_bili_scroll_duty_profile_resolves(tmp_path: Path) -> None:
    manifest_path = _write_plugin(
        tmp_path,
        "bili-scroll",
        {
            "name": "bili-scroll",
            "version": "0.3.0",
            "profiles": {
                "duty": {
                    "title": "值班轮",
                    "tools": ["bili_brief", "bili_search"],
                    "approval": "auto",
                    "modelScene": "background",
                    "budget": {"maxToolCalls": 120},
                }
            },
        },
    )
    spec = resolve_profile([load_manifest(manifest_path)], "bili-scroll:duty")

    assert spec.tools == ("bili_brief", "bili_search")
    assert spec.budget.max_tool_calls == 120
