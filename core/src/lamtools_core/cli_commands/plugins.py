"""Plugin management, widgets and skill command handlers."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
import uuid
from typing import Any


async def cmd_plugin_market(args: argparse.Namespace) -> int:
    # user:“插件页再加上插件市场的界面”+(CLI 与界面共用市场目录和校验安装流程)。
    from .connection import _invoke_live
    if args.action == "install" and not args.name:
        raise ValueError("plugin market install requires a name")
    method = "plugin.market.install" if args.action == "install" else "plugin.market.list"
    result = await _invoke_live(args, lambda client: client.request(method, {"name": args.name} if args.name else {}))
    print(json.dumps(result, ensure_ascii=False, indent=None if args.raw else 2), flush=True)
    return 0


async def cmd_plugin_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("plugin.list", {}))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    plugins = result.get("plugins") if isinstance(result, dict) else []
    if not plugins:
        print("No plugins installed.", flush=True)
        return 0
    for item in plugins:
        deps = item.get("dependencies") or []
        tools = [
            tool["name"]
            for tool_file in (item.get("tools") or [])
            for tool in tool_file.get("tools", [])
        ]
        state = "enabled" if item.get("enabled") else "disabled"
        backend = item.get("backend") or {}
        if backend.get("state"):
            state += f", backend={backend['state']}"
        line = (
            f"{item.get('name')} {item.get('version')} [{state}]"
            f" ({item.get('root')})"
        )
        if tools:
            line += f"\n  tools: {', '.join(tools)}"
        if deps:
            line += f"\n  deps: {', '.join(deps)}"
        diagnostic = backend.get("error") or {}
        if diagnostic.get("message"):
            line += f"\n  backend error: {diagnostic['message']}"
        print(line, flush=True)
    for error in result.get("errors") or []:
        print(f"[error] {error.get('name')}: {error.get('error')}", flush=True)
    return 0


async def cmd_plugin_enable(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args, lambda client: client.request("plugin.enable", {"name": args.name})
    )
    _print_live_result(args, result, f"plugin '{args.name}' enabled")
    return 0


async def cmd_plugin_disable(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args, lambda client: client.request("plugin.disable", {"name": args.name})
    )
    _print_live_result(args, result, f"plugin '{args.name}' disabled")
    return 0


async def cmd_plugin_install(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    payload: dict[str, Any] = {
        "source": args.source,
        "target": args.target,
    }
    if args.source == "url":
        payload["url"] = args.path_or_url
        if args.sha256:
            payload["sha256"] = args.sha256
    else:
        payload["path"] = args.path_or_url
    if args.no_deps:
        payload["install_deps"] = False
    if not args.yes and not args.raw:
        try:
            reply = input(
                f"Install plugin from {args.path_or_url}? This may run pip for dependencies. [y/N] "
            ).strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes", "ok"):
            print("Install cancelled.", flush=True)
            return 1
    result = await _invoke_live(
        args, lambda client: client.request("plugin.install", payload)
    )
    _print_live_result(args, result, f"plugin '{result.get('name', '')}' installed")
    return 0


async def cmd_plugin_uninstall(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    payload: dict[str, Any] = {"name": args.name}
    if args.deps:
        payload["uninstall_deps"] = True
    result = await _invoke_live(
        args, lambda client: client.request("plugin.uninstall", payload)
    )
    _print_live_result(args, result, f"plugin '{args.name}' uninstalled")
    return 0


async def cmd_plugin_deps(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(
        args, lambda client: client.request("plugin.deps-status", {"name": args.name})
    )
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    items = result.get("items") or []
    if not items:
        print(f"plugin '{args.name}' declares no pip dependencies", flush=True)
        return 0
    for item in items:
        mark = "ok" if item.get("ok") else "MISSING" if not item.get("installed") else "MISMATCH"
        print(
            f"{item.get('raw')}: {mark}"
            + (f" (installed {item.get('installed')})" if item.get("installed") else ""),
            flush=True,
        )
    if result.get("install_hint"):
        print(f"install: {result['install_hint']}", flush=True)
    return 0


async def cmd_plugin_config_get(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(
        args, lambda client: client.request("plugin.config.get", {"name": args.name})
    )
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    print(json.dumps(result.get("config") or {}, ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_plugin_operations_list(args: argparse.Namespace) -> int:
    """G 组：列插件声明的 operations（RPC 面直调入口，GUI 能力必有 CLI）。"""
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("plugin.list", {}))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    plugins = result.get("plugins") if isinstance(result, dict) else []
    if args.name:
        plugins = [item for item in plugins if item.get("name") == args.name]
    found = False
    for item in plugins:
        operations = [
            op
            for operation_file in (item.get("operations") or [])
            for op in operation_file.get("operations", [])
        ]
        if not operations:
            continue
        found = True
        state = "enabled" if item.get("enabled") else "disabled"
        print(f"{item.get('name')} {item.get('version')} [{state}]", flush=True)
        for op in operations:
            permission = op.get("permission") or "auto_allow"
            print(f"  {op.get('name')} [{permission}] {op.get('handler')}", flush=True)
    if not found:
        target = f" plugin '{args.name}'" if args.name else ""
        print(f"No plugin-declared operations{target}.", flush=True)
    for error in result.get("errors") or []:
        print(f"[error] {error.get('name')}: {error.get('error')}", flush=True)
    return 0


async def cmd_plugin_config_set(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON value: {exc}", flush=True)
        return 1
    if not isinstance(value, dict):
        print("error: config value must be a JSON object", flush=True)
        return 1
    result = await _invoke_live(
        args,
        lambda client: client.request("plugin.config.update", {"name": args.name, "config": value}),
    )
    _print_live_result(args, result, f"plugin '{args.name}' config saved")
    return 0


async def cmd_plugin_widget_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("plugin.widget.list", {}))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    widgets = result.get("widgets") if isinstance(result, dict) else []
    if not widgets:
        print("No enabled plugin widgets.", flush=True)
        return 0
    for item in widgets:
        print(
            f"{item.get('id')} [{item.get('pluginId')}, {item.get('renderer')}, {item.get('scope')}] "
            f"{item.get('title')}",
            flush=True,
        )
    return 0


def _plugin_widget_scope_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if getattr(args, "work_root", ""):
        payload["work_root"] = args.work_root
    if getattr(args, "thread_id", ""):
        payload["thread_id"] = args.thread_id
    return payload


async def cmd_plugin_widget_show(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    payload = {"id": args.id, **_plugin_widget_scope_payload(args)}
    result = await _invoke_live(args, lambda client: client.request("plugin.widget.get", payload))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        print(json.dumps(result.get("snapshot"), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_plugin_widget_action(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    try:
        inputs = json.loads(args.input)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON input: {exc}", flush=True)
        return 1
    if not isinstance(inputs, dict):
        print("error: action input must be a JSON object", flush=True)
        return 1
    listed = await _invoke_live(args, lambda client: client.request("plugin.widget.list", {}))
    widget = next(
        (item for item in (listed.get("widgets") or []) if item.get("id") == args.id), None
    )
    action = next(
        (item for item in ((widget or {}).get("actions") or []) if item.get("id") == args.action), None
    )
    if action is None:
        print(f"error: widget action '{args.id}/{args.action}' is not declared", flush=True)
        return 1
    confirmed = bool(args.yes)
    if action.get("dangerous") and not confirmed:
        try:
            reply = input(f"Invoke dangerous widget action {args.id}/{args.action}? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes", "ok"):
            print("Action cancelled.", flush=True)
            return 1
        confirmed = True
    idempotency_key = str(args.idempotency_key or "")
    if action.get("mutates") and not idempotency_key:
        import uuid

        idempotency_key = str(uuid.uuid4())
    payload = {
        "id": args.id,
        "action": args.action,
        "input": inputs,
        "confirmed": confirmed,
        **_plugin_widget_scope_payload(args),
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    result = await _invoke_live(args, lambda client: client.request("plugin.widget.invoke", payload))
    _print_live_result(args, result, f"widget action '{args.id}/{args.action}' invoked")
    return 0


async def cmd_skill_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("skill.list", {}))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    skills = result.get("skills") if isinstance(result, dict) else []
    if not skills:
        print("No skills discovered.", flush=True)
        return 0
    for item in skills:
        state = "enabled" if item.get("enabled") else "disabled"
        access = "deletable" if item.get("deletable") else "read-only"
        group = str(item.get("group") or "")
        suffix = f" <{group}>" if group else ""
        print(
            f"{item.get('name')} [{state}, {item.get('source')}, {access}] ({item.get('location')}){suffix}",
            flush=True,
        )
    return 0


# user:“我希望能够在插件界面中看见 skill 的调用统计”+(与技能页同数据源：
# skill.usage 直接读用量账本，命令行也能看每个技能的调用次数与最近调用时间。)
async def cmd_skill_usage(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("skill.usage", {}))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    skills = result.get("skills") if isinstance(result, dict) else {}
    summary = result.get("summary") if isinstance(result, dict) else {}
    if not skills:
        print("No skill invocations recorded yet.", flush=True)
        return 0
    ordered = sorted(
        skills.items(),
        key=lambda item: -int(item[1].get("count") or 0) if isinstance(item[1], dict) else 0,
    )
    for name, entry in ordered:
        entry = entry if isinstance(entry, dict) else {}
        last = entry.get("last_used_at") or "-"
        print("%s: %d calls (last %s)" % (name, int(entry.get("count") or 0), last), flush=True)
    if isinstance(summary, dict):
        print(
            "Total %d calls across %d skills."
            % (int(summary.get("total_calls") or 0), int(summary.get("skills_used") or 0)),
            flush=True,
        )
    return 0


async def cmd_skill_create(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "skill.create",
            {"name": args.name, "description": args.description, "content": args.content},
        ),
    )
    _print_live_result(args, result, f"skill '{args.name}' created")
    return 0


async def cmd_skill_enable(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.request("skill.enable", {"name": args.name}))
    _print_live_result(args, result, f"skill '{args.name}' enabled")
    return 0


async def cmd_skill_disable(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.request("skill.disable", {"name": args.name}))
    _print_live_result(args, result, f"skill '{args.name}' disabled")
    return 0


async def cmd_skill_delete(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    if not args.yes and not args.raw:
        try:
            reply = input(f"Delete skill '{args.name}' and its directory? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes", "ok"):
            print("Delete cancelled.", flush=True)
            return 1
    result = await _invoke_live(args, lambda client: client.request("skill.delete", {"name": args.name}))
    _print_live_result(args, result, f"skill '{args.name}' deleted")
    return 0


# user:“skill 界面也做成瀑布流，并分组管理”+(分组管理与 GUI 同能力集：
# list/create/rename/delete/assign 全部转发宿主 skill.group.* RPC。)
async def cmd_skill_group_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("skill.list", {}))
    groups = result.get("groups") if isinstance(result, dict) else []
    if args.raw:
        print(json.dumps({"groups": groups}, ensure_ascii=False), flush=True)
        return 0
    if not groups:
        print("No skill groups defined.", flush=True)
        return 0
    for name in groups:
        print(name, flush=True)
    return 0


async def cmd_skill_group_create(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.request("skill.group.create", {"name": args.name}))
    _print_live_result(args, result, f"skill group '{args.name}' created")
    return 0


async def cmd_skill_group_rename(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "skill.group.rename", {"from": args.from_group, "to": args.to_group}
        ),
    )
    _print_live_result(args, result, f"skill group '{args.from_group}' renamed to '{args.to_group}'")
    return 0


async def cmd_skill_group_delete(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.request("skill.group.delete", {"name": args.name}))
    _print_live_result(args, result, f"skill group '{args.name}' deleted")
    return 0


async def cmd_skill_group_assign(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request("skill.group.assign", {"name": args.name, "group": args.group}),
    )
    detail = f"skill '{args.name}' assigned to group '{args.group}'" if args.group else f"skill '{args.name}' ungrouped"
    _print_live_result(args, result, detail)
    return 0
