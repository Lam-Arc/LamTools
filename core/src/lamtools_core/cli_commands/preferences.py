"""Onboarding, network, language and runtime preference commands."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from lamtools_core.config.provider_store import ProviderStore
from lamtools_core.config.settings_store import delete_setting, get_setting, set_setting


_ONBOARDING_NAMESPACE = "core.onboarding"


def _onboarding_settings() -> dict[str, Any]:
    """Read core.onboarding settings from settings.jsonc."""
    value = get_setting(_ONBOARDING_NAMESPACE)
    return dict(value) if isinstance(value, dict) else {}


def _onboarding_providers_configured() -> bool:
    """True when at least one provider (jsonc) has a non-empty API key."""
    providers = ProviderStore().list_sync()
    return any(bool(p.api_key) for p in providers)


async def cmd_onboarding_show(args: argparse.Namespace) -> int:
    del args
    value = _onboarding_settings()
    configured = _onboarding_providers_configured()
    completed = bool(value.get("completed"))
    skipped = bool(value.get("skipped"))
    print(f"completed: {'yes' if completed else 'no'}")
    if completed:
        print(f"completed_at: {value.get('completed_at') or ''}")
    print(f"skipped:   {'yes' if skipped else 'no'}")
    print(f"provider_configured: {'yes' if configured else 'no'}")
    print("说明:     未完成且未配置供应商时，启动会弹出首次引导向导；onboarding complete 标记完成，onboarding reset 清除标记")
    return 0


async def cmd_onboarding_complete(args: argparse.Namespace) -> int:
    from .settings import _now_iso
    del args
    value = {"completed": True, "version": 1, "completed_at": _now_iso()}
    set_setting(_ONBOARDING_NAMESPACE, value)
    print("[onboarding] marked completed; the wizard will not show on next start")
    return 0


async def cmd_onboarding_reset(args: argparse.Namespace) -> int:
    del args
    delete_setting(_ONBOARDING_NAMESPACE)
    print("[onboarding] reset; the wizard will show again on next start if no provider is configured")
    return 0


async def cmd_load_context_get(args: argparse.Namespace) -> int:
    from lamtools_core.app.project_context import ContextConfig
    from lamtools_core.config.root import core_config_file

    path = core_config_file("load_context.jsonc")
    config = ContextConfig.from_file(path) if path.is_file() else None
    print(json.dumps(
        {
            "path": str(path),
            "exists": config is not None,
            "addition": [dict(item) for item in config.addition] if config is not None else [],
            "except": list(config.except_files) if config is not None else [],
        },
        ensure_ascii=False,
        indent=2,
    ), flush=True)
    return 0


async def cmd_command_shell_get(args: argparse.Namespace) -> int:
    from lamtools_core.tool.command_runner import resolve_command_shell

    saved = get_setting("core.commandShell")
    preference = saved.get("preference") if isinstance(saved, dict) else None
    if preference not in {"auto", "wsl", "git-bash", "powershell"}:
        preference = "auto"
    shell = resolve_command_shell()
    print(json.dumps({
        "preference": preference,
        "effective": {"name": shell.name, "kind": shell.kind, "executable": shell.executable},
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_command_shell_set(args: argparse.Namespace) -> int:

    preference = str(args.preference)
    set_setting("core.commandShell", {"preference": preference})
    print(json.dumps({"preference": preference}, ensure_ascii=False), flush=True)
    return 0


async def cmd_network_get(args: argparse.Namespace) -> int:
    from lamtools_core.config.network import network_config

    print(json.dumps(network_config(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_network_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.network import NETWORK_NAMESPACE, merge_network

    update: dict[str, str] = {}
    if args.proxy is not None:
        update["proxy"] = args.proxy
    if args.no_proxy is not None:
        update["no_proxy"] = args.no_proxy
    if args.ca_cert is not None:
        update["ca_cert"] = args.ca_cert
    if not update:
        print("error: nothing to change (pass --proxy, --no-proxy or --ca-cert)", file=sys.stderr)
        return 1
    try:
        merged = merge_network(get_setting(NETWORK_NAMESPACE), update)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    set_setting(NETWORK_NAMESPACE, merged)
    print(json.dumps(merged, ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_language_get(args: argparse.Namespace) -> int:
    from lamtools_core.config.language import language_status

    print(json.dumps(language_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_language_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.language import LANGUAGE_NAMESPACE, merge_language, language_status

    set_setting(LANGUAGE_NAMESPACE, merge_language({}, {"locale": args.locale}))
    print(json.dumps(language_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_keep_awake_get(args: argparse.Namespace) -> int:
    from lamtools_core.runtime.power import keep_awake_status

    print(json.dumps(keep_awake_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_keep_awake_set(args: argparse.Namespace) -> int:
    from lamtools_core.runtime.power import KEEP_AWAKE_NAMESPACE, apply_keep_awake, keep_awake_status

    enabled = str(args.state) == "on"
    set_setting(KEEP_AWAKE_NAMESPACE, {"enabled": enabled})
    apply_keep_awake(enabled)
    print(json.dumps(keep_awake_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_ask_auto_continue_get(args: argparse.Namespace) -> int:
    from lamtools_core.config.automation import ask_auto_continue_status

    print(json.dumps(ask_auto_continue_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_ask_auto_continue_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.automation import ASK_AUTO_CONTINUE_NAMESPACE, ask_auto_continue_status

    set_setting(ASK_AUTO_CONTINUE_NAMESPACE, {"enabled": str(args.state) == "on"})
    print(json.dumps(ask_auto_continue_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_memory_resume_get(args: argparse.Namespace) -> int:
    from lamtools_core.runtime.memory_guard import memory_resume_status

    print(json.dumps(memory_resume_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_memory_resume_set(args: argparse.Namespace) -> int:
    from lamtools_core.runtime.memory_guard import (
        MEMORY_RESUME_NAMESPACE,
        memory_resume_status,
        merge_memory_resume,
    )

    incoming: dict[str, object] = {}
    if args.state is not None:
        incoming["enabled"] = str(args.state) == "on"
    if args.threshold_gb is not None:
        incoming["threshold_gb"] = float(args.threshold_gb)
    if not incoming:
        print("error: give a state (on|off) and/or --threshold-gb", file=sys.stderr)
        return 2
    merged = merge_memory_resume(get_setting(MEMORY_RESUME_NAMESPACE), incoming)
    if merged is None:
        print("error: threshold-gb must be a number between 0.5 and 1024", file=sys.stderr)
        return 2
    set_setting(MEMORY_RESUME_NAMESPACE, merged)
    print(json.dumps(memory_resume_status(), ensure_ascii=False, indent=2), flush=True)
    return 0


async def cmd_load_context_set(args: argparse.Namespace) -> int:
    import json as _json

    from lamtools_core.config.root import core_config_file

    if args.source_file == "-":
        raw_text = sys.stdin.read()
    else:
        try:
            raw_text = Path(args.source_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        data = _json.loads(raw_text)
    except _json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("error: expected a JSON object with addition/except", file=sys.stderr)
        return 1
    additions: list[dict[str, object]] = []
    for item in data.get("addition") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            print("error: addition items must be objects with a string name", file=sys.stderr)
            return 1
        additions.append({
            "name": str(item["name"]).strip(),
            "priority": int(item.get("priority") or 50),
            "kind": str(item.get("kind") or "system"),
        })
    exceptions = [str(item).strip() for item in (data.get("except") or []) if isinstance(item, str) and str(item).strip()]
    path = core_config_file("load_context.jsonc")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"addition": additions, "except": exceptions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[load-context] saved {len(additions)} additions, {len(exceptions)} exceptions to {path}")
    return 0
