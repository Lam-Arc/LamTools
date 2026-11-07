"""Server startup, maintenance, setup and update commands."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import httpx
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.config.root import ensure_projects_root


async def cmd_serve(args: argparse.Namespace) -> int:
    from .connection import _print_live_result
    from lamtools_core.logging_setup import LOG_DATEFMT, LOG_FORMAT

    # Millisecond timestamps: the step lines emitted by the kernel are compared
    # against each other to split a step into model time and local time.
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
        force=True,
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("serve requires uvicorn; install the Core HTTP server dependencies") from exc
    from lamtools_core.app.api_access import CoreApiAccessPolicy

    access_policy = CoreApiAccessPolicy.from_env(allow_lan=getattr(args, "allow_lan", None))
    bind_host = access_policy.validate_bind_host(args.host)
    certfile = getattr(args, "ssl_certfile", "")
    keyfile = getattr(args, "ssl_keyfile", "")
    if bool(certfile) != bool(keyfile):
        raise ValueError("--ssl-certfile and --ssl-keyfile must be supplied together")
    # Seed the unified config directory with built-in defaults on first run
    # (idempotent; user edits are never overwritten).
    from lamtools_core.config.defaults import ensure_default_config_files

    ensure_default_config_files()
    from lamtools_core.app.http_agent_app import create_core_agent_http_app

    app_kwargs = {
        "access_policy": access_policy,
        "model_id": args.model_id,
        "core_db": args.core_db or None,
        "data_dir": args.data_dir or None,
        "work_root": args.work_root or None,
        "frontend_dir": args.frontend_dir or None,
        "thinking_enabled": args.thinking == "enabled",
        "thinking_budget": args.thinking_budget,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    reasoning_level = getattr(args, "reasoning_level", "")
    if reasoning_level:
        app_kwargs["reasoning_level"] = reasoning_level
    # user:“给我把 2 阶段做完，前端除外”+(已有HTTP前端启动者提供真实配置地址；端口0尚未知，不生成虚假广告地址)。
    if args.frontend_dir and 0 < args.port <= 65535:
        public_host = "127.0.0.1" if bind_host == "0.0.0.0" else "::1" if bind_host == "::" else bind_host
        public_host = f"[{public_host}]" if ":" in public_host else public_host
        app_kwargs["advertised_url"] = f"{'https' if certfile else 'http'}://{public_host}:{args.port}/"
    app = create_core_agent_http_app(**app_kwargs)
    url_host = f"[{bind_host}]" if ":" in bind_host else bind_host
    url = f"{'https' if certfile else 'http'}://{url_host}:{args.port}"
    _print_live_result(args, {"url": url}, f"serving {url}")
    server_kwargs = {"host": bind_host, "port": args.port, "reload": bool(args.reload), "proxy_headers": False}
    if certfile:
        server_kwargs.update(ssl_certfile=certfile, ssl_keyfile=keyfile)
    server = uvicorn.Server(uvicorn.Config(app, **server_kwargs))
    await server.serve()
    return 0


async def cmd_setup(args: argparse.Namespace) -> int:
    del args
    from lamtools_core.config.root import default_projects_root

    # created 报告根目录是否刚建立（此前恒为 True，audit 08 S4）
    root = default_projects_root()
    created = not root.exists()
    root = ensure_projects_root()
    # Seed the unified config directory with built-in defaults (idempotent).
    from lamtools_core.config.defaults import ensure_default_config_files

    ensure_default_config_files()
    print(json.dumps({"lam_projects": str(root), "created": created}, ensure_ascii=False), flush=True)
    return 0


async def cmd_migrate_projects(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    from lamtools_core.config.migrate_projects import migrate_projects

    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        report = await migrate_projects(db, apply=bool(args.apply))
    finally:
        await db.close()
    label = "migrated" if report.applied else "dry-run"
    print(json.dumps({"status": label, **report.to_dict()}, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


async def cmd_maintenance_strip_snapshot_images(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    from lamtools_core.maintenance import (
        ConcurrentModificationError,
        MaintenanceScopeError,
        strip_snapshot_registry_images,
    )

    db_path = _resolve_core_db(args.core_db or None)
    try:
        report = await strip_snapshot_registry_images(db_path, apply=bool(args.apply))
    except MaintenanceScopeError as exc:
        print(
            json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return 2
    except ConcurrentModificationError as exc:
        print(
            json.dumps(
                {"status": "aborted", "error": str(exc)}, ensure_ascii=False, sort_keys=True
            ),
            flush=True,
        )
        return 1
    label = "applied" if args.apply else "dry-run"
    print(json.dumps({"status": label, **report.to_dict()}, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report.ok else 1


async def cmd_maintenance_checkpoint_baseline(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    from lamtools_core.checkpoint_maintenance import (
        capture_checkpoint_baseline,
        compare_checkpoint_baseline,
    )
    from lamtools_core.maintenance import MaintenanceScopeError

    db_path = _resolve_core_db(args.core_db or None)
    try:
        baseline = await capture_checkpoint_baseline(db_path)
    except MaintenanceScopeError as exc:
        print(
            json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return 2
    payload: dict[str, Any] = {"captured": baseline.to_dict()}
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        payload["out"] = str(out_path)
    if args.compare:
        prior = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        payload["compare"] = compare_checkpoint_baseline(prior, baseline)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)
    return 0


async def cmd_maintenance_prune_checkpoints(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    from lamtools_core.checkpoint_maintenance import prune_superseded_checkpoints
    from lamtools_core.maintenance import MaintenanceScopeError

    db_path = _resolve_core_db(args.core_db or None)
    try:
        report = await prune_superseded_checkpoints(
            db_path,
            apply=bool(args.apply),
            keep_recent=int(args.keep_recent or 1),
        )
    except MaintenanceScopeError as exc:
        print(
            json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return 2
    label = "applied" if args.apply else "dry-run"
    print(json.dumps({"status": label, **report.to_dict()}, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report.ok else 1


async def cmd_maintenance_dialogue_records(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    from lamtools_core.checkpoint_maintenance import verify_dialogue_records
    from lamtools_core.maintenance import MaintenanceScopeError

    db_path = _resolve_core_db(args.core_db or None)
    try:
        report = await verify_dialogue_records(db_path, thread_id=str(args.thread_id or ""))
    except MaintenanceScopeError as exc:
        print(
            json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str), flush=True)
    return 0 if report.get("ok") else 1


def normalize_remote_server_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Relay 服务器地址格式无效")
    if parsed.username is not None or parsed.password is not None or not parsed.hostname:
        raise RuntimeError("Relay 地址不得包含凭据")
    if parsed.scheme == "http":
        from ipaddress import ip_address

        try:
            local = ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname.lower() == "localhost"
        if not local:
            raise RuntimeError("非回环 Relay 控制面必须使用 HTTPS，不能通过明文发送账号凭据")
    path = parsed.path
    marker = path.find("/v1/")
    if marker >= 0:
        path = path[:marker]
    elif path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))


async def cmd_update_check(args: argparse.Namespace) -> int:
    """Check the official-site manifest and GitHub Releases (--json for scripting)."""
    from lamtools_core.update.checker import check_update, source_label

    result = check_update()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") != "check_failed" else 1
    status = result.get("status")
    print(f"current:   {result.get('current_version') or '?'}")
    if status == "update_available":
        print(f"latest:    {result.get('latest_version')}（有更新可用）")
        print(f"source:    {source_label(result.get('source')) or '?'}")
        if result.get("release_notes"):
            print(f"notes:     {result.get('release_notes')}")
        print(f"download:  {result.get('download_url')}")
        print(f"release:   {result.get('release_url')}")
        print("提示: 下载安装包后关闭 Sunday 再运行安装。")
        return 0
    if status == "up_to_date":
        if result.get("reason") == "no_installer_for_platform":
            print(f"latest:    {result.get('latest_version')}（已发布，但没有适用于本平台的安装包）")
        else:
            print(f"latest:    {result.get('latest_version')}（已是最新）")
        label = source_label(result.get("source"))
        if label:
            print(f"source:    {label}")
        return 0
    print(f"error:     检查失败 — {result.get('error') or 'unknown error'}", file=sys.stderr)
    return 1
