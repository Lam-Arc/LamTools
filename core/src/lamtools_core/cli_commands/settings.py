"""Model configuration, permissions, image generation and compaction settings."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
import os
import sys
from dataclasses import field, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from lamtools_core.app.runtime_permissions import read_global_runtime_controls
from lamtools_core.config.settings_store import get_setting, set_setting
from lamtools_core.context_compaction_budget import (
    CONTEXT_COMPACTION_NAMESPACE,
    MAX_RETAINED_STEPS,
    load_retained_steps,
)
from lamtools_core.tool.loadtools import LoadTools


async def cmd_models_list(args: argparse.Namespace) -> int:

    from .config import _get_model_store
    store = _get_model_store()
    models = store.list_sync(work_root=args.work_root or None)
    if not models:
        print("[models] no model definitions configured (add models/*.jsonc under .lam/core/config/)")
        return 0
    default_id = store.default_model_id_sync(work_root=args.work_root or None)
    print(f"[models] {len(models)} configured (default: {default_id or 'none'})")
    for model in models:
        star = "★ " if model.is_default else "  "
        print(f"{star}{model.model_id}  {model.display_name}  [{model.resolved_capability}]  provider={model.provider or '?'}  ctx={model.context_window}")
    return 0


async def cmd_models_show(args: argparse.Namespace) -> int:

    from .config import _get_model_store, list_llm_model_configs
    store = _get_model_store()
    model = store.get_sync(args.model_id, work_root=args.work_root or None)
    if model is None:
        print(f"[models] not found: {args.model_id}", file=sys.stderr)
        return 1
    print(f"model_id:        {model.model_id}")
    print(f"display_name:    {model.display_name}")
    print(f"provider:        {model.provider or model.provider_id or '?'}")
    print(f"capability:      {model.capability or '(builtin)'} -> {model.resolved_capability}")
    print(f"context_window:  {model.context_window}")
    print(f"max_output:      {model.max_output_tokens}")
    print(f"temperature:     {model.temperature}")
    print(f"thinking:        supported={model.thinking_supported} budget={model.thinking_budget}")
    ladder = next(
        (
            entry.get("reasoning_levels") or []
            for entry in list_llm_model_configs(work_root=args.work_root or None)
            if entry.get("id") == model.id
        ),
        [],
    )
    print(
        "thinking_levels: "
        + (", ".join(str(item.get("value") or "") for item in ladder) or "(product default)")
    )
    print(f"adapter_profile: {model.adapter_profile_id or '(none)'}")
    print(f"is_default:      {model.is_default}")
    print(f"source:          {model.source_path or '(none)'}")
    return 0


async def cmd_models_set(args: argparse.Namespace) -> int:

    from .config import _get_model_store
    store = _get_model_store()
    model = store.get_sync(args.model_id, work_root=args.work_root or None)
    if model is None:
        print(f"[models] not found: {args.model_id}", file=sys.stderr)
        return 1
    field = args.field
    value = args.value
    if field == "capability":
        if value not in ("text", "multimodal", ""):
            print(f"[models] capability must be 'text', 'multimodal', or ''", file=sys.stderr)
            return 1
        model = replace(model, capability=value)
    elif field == "is_default":
        model = replace(model, is_default=value.lower() in ("1", "true", "yes"))
    elif field == "adapter_profile_id":
        model = replace(model, adapter_profile_id=value)
    elif field == "context_window":
        model = replace(model, context_window=int(value))
    elif field == "max_output_tokens":
        model = replace(model, max_output_tokens=int(value))
    elif field == "temperature":
        model = replace(model, temperature=float(value))
    else:
        print(f"[models] unsupported field: {field}", file=sys.stderr)
        return 1
    path = store.write(model, scope=args.scope, work_root=args.work_root or None)
    print(f"[models] set {field}={value} for {model.model_id} -> {path}")
    return 0


async def cmd_models_default(args: argparse.Namespace) -> int:

    from .config import _get_model_store
    store = _get_model_store()
    model = store.get_sync(args.model_id, work_root=args.work_root or None)
    if model is None:
        print(f"[models] not found: {args.model_id}", file=sys.stderr)
        return 1
    # Clear other defaults first.
    for existing in store.list_sync(work_root=args.work_root or None):
        if existing.id != model.id and existing.is_default:
            store.write(replace(existing, is_default=False), scope=args.scope, work_root=args.work_root or None)
    path = store.write(replace(model, is_default=True), scope=args.scope, work_root=args.work_root or None)
    print(f"[models] default set to {model.model_id} -> {path}")
    return 0


def _loadtools_for_cli() -> tuple[LoadTools, Path, bool]:
    """Load the effective mode tool-sets: config file when present, else built-in."""
    from lamtools_core.config.root import core_config_file
    from lamtools_core.tool.loadtools import default_load_tools, load_loadtools

    path = core_config_file("loadtools.jsonc")
    if path.is_file():
        loaded = load_loadtools(path)
        if loaded:
            return loaded, path, True
    return default_load_tools(), path, False


def _imagegen_settings() -> dict[str, Any]:
    """Read imagegen settings from imagegen.jsonc."""
    from lamtools_core.config.imagegen_store import load_imagegen_config

    return load_imagegen_config()


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) > 8:
        return api_key[:4] + "****" + api_key[-4:]
    return "****"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def cmd_permissions_show(args: argparse.Namespace) -> int:
    del args
    raw = get_setting("core.runtimeControls")
    controls = read_global_runtime_controls(raw)
    print(f"capability:       {controls['base_tier']}")
    print(f"default_approval: {controls['permission_preset']}")
    print(
        "outside_workdir:  "
        f"{'yes' if controls['base_allow_access_outside_workdir'] else 'no'}"
    )
    print("说明:              这些值只作为新会话默认；当前任务可在输入框临时调整")
    return 0


async def _run_config_cli_operation(name: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from lamtools_core.config.operations import build_config_operation_catalog

    result = await build_config_operation_catalog().execute(name, payload)
    if result.status != "ok":
        print(str(result.payload.get("error") or "operation failed"), file=sys.stderr)
        return 1, result.payload
    print(json.dumps(result.payload, ensure_ascii=False, indent=2))
    return 0, result.payload


async def cmd_models_create(args: argparse.Namespace) -> int:
    api_key = str(args.api_key or os.environ.get("LAMTOOLS_LLM_API_KEY", "")).strip()
    existing = bool(args.provider_id)
    provider: dict[str, Any] = {
        "mode": "existing" if existing else "new",
        "base_url": args.base_url,
        "api_type": args.api_type,
        "api_key": api_key,
        "adapter_profile_id": args.adapter_profile_id,
    }
    if existing:
        provider["provider_id"] = args.provider_id
    else:
        provider["name"] = args.provider_name
        if not args.provider_name:
            print("--provider-name is required when --provider-id is omitted", file=sys.stderr)
            return 1
    code, _ = await _run_config_cli_operation(
        "config.model.create_with_provider",
        {
            "group_id": args.group_id,
            "model": {
                "model_id": args.model_id,
                "display_name": args.display_name or args.model_id,
                "context_window": args.context_window,
                "max_output_tokens": args.max_output_tokens,
                "temperature": args.temperature,
                "thinking_supported": args.thinking_supported,
                "thinking_budget": args.thinking_budget,
            },
            "provider": provider,
        },
    )
    return code


async def cmd_model_groups_list(args: argparse.Namespace) -> int:
    code, _ = await _run_config_cli_operation("config.model_groups.list", {})
    return code


async def cmd_model_groups_create(args: argparse.Namespace) -> int:
    code, _ = await _run_config_cli_operation(
        "config.model_group.create", {"name": args.name, "model_ids": list(args.model)}
    )
    return code


async def cmd_model_groups_rename(args: argparse.Namespace) -> int:
    code, _ = await _run_config_cli_operation(
        "config.model_group.update", {"group_id": args.group_id, "name": args.name}
    )
    return code


async def cmd_model_groups_delete(args: argparse.Namespace) -> int:
    code, _ = await _run_config_cli_operation("config.model_group.delete", {"group_id": args.group_id})
    return code


async def cmd_model_groups_reorder(args: argparse.Namespace) -> int:
    code, _ = await _run_config_cli_operation(
        "config.model_groups.reorder", {"group_ids": list(args.group_ids)}
    )
    return code


async def cmd_model_group_members_set(args: argparse.Namespace) -> int:
    code, _ = await _run_config_cli_operation(
        "config.model_group.members.set",
        {"group_id": args.group_id, "model_ids": list(args.model_ids)},
    )
    return code


async def cmd_permissions_config(args: argparse.Namespace) -> int:
    current = get_setting("core.runtimeControls")
    value = dict(current) if isinstance(current, dict) else {}
    changed = False
    if args.mode is not None:
        value["permission_mode"] = args.mode
        changed = True
    if args.approval is not None:
        value["permission_preset"] = args.approval
        changed = True
    if args.allow_outside_workdir is not None:
        value["allow_access_outside_workdir"] = args.allow_outside_workdir == "true"
        changed = True
    if not changed:
        print(
            "error: nothing to change (pass --mode / --approval / --allow-outside-workdir)",
            file=sys.stderr,
        )
        return 1
    set_setting("core.runtimeControls", value)
    controls = read_global_runtime_controls(value)
    print(
        "[permissions] saved: "
        f"capability={controls['base_tier']} "
        f"default_approval={controls['permission_preset']} "
        f"outside_workdir={'yes' if controls['base_allow_access_outside_workdir'] else 'no'}"
    )
    return 0


def _context_compaction_settings() -> dict[str, Any]:
    """Read the effective structural context-compaction settings."""
    value = get_setting(CONTEXT_COMPACTION_NAMESPACE)
    return dict(value) if isinstance(value, dict) else {}


async def cmd_context_compaction_show(args: argparse.Namespace) -> int:
    del args
    # Always print the resolved value so missing/invalid settings visibly use
    # the documented default.
    retained_steps = load_retained_steps()
    print(f"retained_steps: {retained_steps}")
    print("retained_user_messages: 20")
    print("说明:     默认完整汇总历史，再追加最近 20 条用户指令原文；预算不足时静默丢弃最旧条目")
    return 0


async def cmd_context_compaction_config(args: argparse.Namespace) -> int:
    retained_steps = args.retained_steps
    if retained_steps is None:
        print("error: nothing to change (pass --retained-steps)", file=sys.stderr)
        return 1
    if isinstance(retained_steps, bool) or not 0 <= retained_steps <= MAX_RETAINED_STEPS:
        print(
            f"error: --retained-steps must be an integer between 0 and {MAX_RETAINED_STEPS}",
            file=sys.stderr,
        )
        return 1
    value = _context_compaction_settings()
    value["retained_steps"] = retained_steps
    set_setting(CONTEXT_COMPACTION_NAMESPACE, value)
    print(f"[context compaction] saved: retained_steps={retained_steps}")
    return 0


async def cmd_imagegen_show(args: argparse.Namespace) -> int:
    del args
    value = _imagegen_settings()
    enabled = bool(value.get("enabled"))
    print(f"enabled:  {'yes' if enabled else 'no'}")
    print(f"api_url:  {value.get('api_url') or '(未配置)'}")
    print(f"api_key:  {_mask_api_key(str(value.get('api_key') or '')) or '(未配置)'}")
    print(f"model:    {value.get('model') or '(默认)'}")
    print("说明:     未启用时 generate_image 工具不会上传到工具集（execute 模式留空=全部工具），模型调用会被拦截")
    return 0


async def cmd_imagegen_config(args: argparse.Namespace) -> int:
    value = _imagegen_settings()
    changed = False
    if args.enabled is not None:
        value["enabled"] = args.enabled == "true"
        changed = True
    if args.api_url is not None:
        value["api_url"] = args.api_url.strip()
        changed = True
    if args.api_key is not None:
        value["api_key"] = args.api_key.strip()
        changed = True
    if args.model is not None:
        value["model"] = args.model.strip()
        changed = True
    if not changed:
        print("error: nothing to change (pass --enabled / --api-url / --api-key / --model)", file=sys.stderr)
        return 1
    from lamtools_core.config.imagegen_store import save_imagegen_config

    save_imagegen_config(value)
    print(f"[imagegen] saved: enabled={bool(value.get('enabled'))} api_url={value.get('api_url') or ''} "
          f"api_key={_mask_api_key(str(value.get('api_key') or ''))} model={value.get('model') or ''}")
    return 0
