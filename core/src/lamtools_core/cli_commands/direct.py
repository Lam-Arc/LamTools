"""``direct`` 命令组：调用台的命令行等价入口。

GUI 能做的直调（选模型、批量输入、看历史）在这里也能做，方便脚本与排障。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _data_dir(args: argparse.Namespace) -> Path:
    explicit = str(getattr(args, "data_dir", "") or "").strip()
    if explicit:
        return Path(explicit)
    env = os.environ.get("LAMTOOLS_CORE_DATA_DIR", "").strip()
    if env:
        return Path(env)
    from .config import _resolve_core_db

    return _resolve_core_db(None).parent / "core-agent"


def _service(args: argparse.Namespace):
    from lamtools_core.direct import DirectCallService

    return DirectCallService(
        data_dir=_data_dir(args),
        work_root=str(getattr(args, "work_root", "") or "") or None,
    )


def _params(raw: list[str] | None) -> dict:
    params: dict = {}
    for item in raw or []:
        if "=" not in item:
            raise ValueError(f"--param 需要 key=value：{item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--param 的 key 不能为空：{item}")
        text = value.strip()
        if text in ("true", "false"):
            params[key] = text == "true"
            continue
        try:
            params[key] = int(text)
            continue
        except ValueError:
            pass
        try:
            params[key] = float(text)
            continue
        except ValueError:
            params[key] = text
    return params


async def cmd_direct_catalog(args: argparse.Namespace) -> int:
    catalog = _service(args).catalog()
    if getattr(args, "json", False):
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
        return 0
    models = catalog.get("models") or []
    if not models:
        print("[direct] 还没有可用模型（设置 → 模型与供应商）")
        return 0
    for model in models:
        print(
            f"{model['display_name']}  [{model['output_type']}]  "
            f"model={model['model_id']}  provider={model['provider_name'] or '?'}"
        )
    return 0


async def cmd_direct_run(args: argparse.Namespace) -> int:
    service = _service(args)
    params = _params(args.param)
    references = [str(item).strip() for item in getattr(args, "reference", []) or [] if str(item).strip()]
    if references:
        params["reference_urls"] = references
    record = await service.submit(
        {
            "model_ref": args.model,
            "prompts": args.prompt,
            "system": args.system or "",
            "params": params,
            "project_id": args.project_id or "",
        },
        work_root=str(args.work_root or "") or None,
    )
    record = await service.wait(record.id)
    if record is None:
        print("error: 调用记录丢失")
        return 1
    if getattr(args, "json", False):
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[direct] {record.display_name}  {record.status}  {record.id}")
        for item in record.results:
            print(f"--- #{item.index + 1} {item.status}  {item.duration_ms}ms")
            if item.text:
                print(item.text)
            for file in item.files:
                print(f"[file] {file.get('path')}")
            if item.error:
                print(f"[error] {item.error}")
        if record.error:
            print(f"[error] {record.error}")
    return 0 if record.status == "completed" else 1


async def cmd_direct_list(args: argparse.Namespace) -> int:
    service = _service(args)
    calls = service.list_calls(
        limit=args.limit,
        offset=getattr(args, "offset", 0) or 0,
        output_type=args.output_type or "",
        status=args.status or "",
    )
    if getattr(args, "json", False):
        print(json.dumps({"calls": calls}, ensure_ascii=False, indent=2))
        return 0
    if not calls:
        print("[direct] 还没有调用记录")
        return 0
    for call in calls:
        print(
            f"{call['created_at']}  {call['display_name']}  [{call['output_type']}]  "
            f"{call['status']}  prompts={len(call['prompts'])}  id={call['id']}"
        )
    return 0


async def cmd_direct_retry(args: argparse.Namespace) -> int:
    """只重跑一次调用里的某一条。"""
    service = _service(args)
    record = await service.retry(args.call_id, args.index, work_root=str(args.work_root or "") or None)
    record = await service.wait(record.id)
    if record is None:
        print("error: 调用记录丢失")
        return 1
    if getattr(args, "json", False):
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[direct] {record.display_name}  {record.status}  {record.id}")
        for item in record.results:
            print(f"--- #{item.index + 1} {item.status}  {item.duration_ms}ms")
            if item.text:
                print(item.text)
            for file in item.files:
                print(f"[file] {file.get('path')}")
            if item.error:
                print(f"[error] {item.error}")
    return 0 if record.status == "completed" else 1


async def cmd_direct_import_imagegen(args: argparse.Namespace) -> int:
    """把生图工具的配置导入成一条图片模型。"""
    result = _service(args).import_imagegen()
    print(json.dumps(result, ensure_ascii=False))
    return 0


__all__ = [
    "cmd_direct_catalog",
    "cmd_direct_import_imagegen",
    "cmd_direct_list",
    "cmd_direct_retry",
    "cmd_direct_run",
]
