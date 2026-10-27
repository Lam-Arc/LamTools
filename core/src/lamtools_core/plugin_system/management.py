"""user:“该重建就重建”+(安装、启停、更新和卸载共用同一事务与调用排空流程)。"""
from __future__ import annotations

import asyncio
import shutil
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .backend_runtime import register_manager
from .context import PluginContext
from .manifest import load_manifest
from .safety import safe_mode


@contextmanager
def source_directory(payload):
    from .installer import download_archive
    downloaded = None
    work = None
    try:
        source = payload.get("source", "local")
        path = Path(str(payload.get("path") or "")).expanduser()
        if source == "url":
            url = str(payload.get("url") or "")
            if not url:
                raise ValueError("url is required")
            downloaded = download_archive(url, str(payload.get("sha256") or ""))
            path = downloaded
        elif source not in {"local", "zip"}:
            raise ValueError("source must be local, zip or url")
        if source == "local":
            if not payload.get("path") or not path.is_dir():
                raise ValueError("a plugin directory is required")
            yield path.resolve()
            return
        work = Path(tempfile.mkdtemp(prefix="lam-plugin-source-")).resolve()
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    name = info.filename.replace("\\", "/")
                    candidate = (work / name).resolve()
                    if not candidate.is_relative_to(work) or name.startswith("/") or ":" in name:
                        raise ValueError("archive contains an unsafe path")
                archive.extractall(work)
        else:
            with tarfile.open(path) as archive:
                archive.extractall(work, filter="data")
        manifests = sorted(work.rglob("plugin.json"), key=lambda item: len(item.parts))
        if not manifests:
            raise ValueError("archive contains no plugin.json")
        shallow = [item for item in manifests if len(item.parts) == len(manifests[0].parts)]
        if len(shallow) != 1:
            raise ValueError("archive contains multiple plugin roots")
        yield shallow[0].parent
    finally:
        if downloaded:
            downloaded.unlink(missing_ok=True)
        if work:
            shutil.rmtree(work)


def supervisor(host):
    manager = getattr(host, "backend_manager", None)
    if manager is None:
        manager = register_manager(host, [], PluginContext(work_root=Path.cwd(), data_dir=host.state.path.parent))
    return manager


def refresh_catalogs(host):
    from .operation_bridge import register_plugin_operations
    for catalog in list(getattr(host, "operation_catalogs", ())):
        register_plugin_operations(catalog, host, refresh=True)


def validate_conflicts(host, incoming):
    # user:“该重建就重建”+(冲突必须在导入插件代码之前拒绝，不能安装成功后才静默丢入口)。
    from .capabilities import assemble_capabilities
    from .operation_bridge import assemble_operations, read_operations
    manifests = [item for item in host.discover() if item.name != incoming.name]
    manifests.append(incoming)
    errors = [*assemble_capabilities(manifests).errors,
              *assemble_operations(manifests, include_disabled=True).errors]
    # user:“该重建就重建”+(仅拒绝涉及本次插件的错误，允许修复无关坏插件)。
    errors = [item for item in errors if item.get("plugin") == incoming.name]
    for spec in read_operations(incoming):
        for catalog in list(getattr(host, "operation_catalogs", ())):
            if spec.name in catalog.registered() and catalog.owner_of(spec.name) != f"plugin:{incoming.name}":
                errors.append({"error": f"operation '{spec.name}' is already registered"})
    if errors:
        raise ValueError("; ".join(str(item["error"]) for item in errors))


async def set_enabled(host, name, enabled):
    manager = supervisor(host)
    async with manager.mutation(name):
        if host.get(name) is None:
            raise ValueError(f"plugin '{name}' is not installed")
        if safe_mode() and enabled:
            raise ValueError("安全模式下不能启动插件，请正常重启后再试")
        if enabled:
            validate_conflicts(host, host.get(name))
        await manager.drain(name)
        if enabled:
            host.enable(name)
            if not await manager.start(name):
                raise RuntimeError("plugin did not start")
        else:
            # Stop failure retains intent but availability is revoked by
            # the failed handle; no files or old runtime are discarded.
            host.disable(name)
            await manager.stop(name)
        refresh_catalogs(host)
    return {"name": name, "enabled": enabled, "available": host.available(name), "backend": manager.status(name),
            "restart_required": bool(host.get(name).raw.get("overrides") or host.get(name).raw.get("ui"))}


async def uninstall(host, name, keep_data=True):
    manager = supervisor(host)
    async with manager.mutation(name):
        manifest = host.get(name)
        if manifest is None:
            raise ValueError(f"plugin '{name}' is not installed")
        host._assert_mutable(manifest)
        await manager.drain(name)
        await manager.stop(name)
        manager.forget(name)
        host.uninstall(name, keep_data=keep_data)
        refresh_catalogs(host)
        return {"name": name, "uninstalled": True, "data_path": str(host.data_path(name)), "kept_data": keep_data}


async def reload(host, name):
    # user:“该修修 如果是架构问题就重构”+(重载也使用同一变更边界，先拒绝新调用再排空旧调用)。
    manager = supervisor(host)
    async with manager.mutation(name):
        manifest = host.get(name)
        if manifest is None or not manifest.enabled:
            raise ValueError(f"plugin '{name}' is not installed or is disabled")
        if safe_mode():
            raise ValueError("安全模式下不能启动插件，请正常重启后再试")
        validate_conflicts(host, manifest)
        try:
            await manager.drain(name)
            await manager.stop(name)
            manager.forget(name)
            if not await manager.start(name):
                raise RuntimeError("plugin did not start")
        finally:
            refresh_catalogs(host)
    return {"name": name, "reloaded": True, "started": True,
            "generation": manager.generation.get(name, 0), "backend": manager.status(name)}


def replacement_recovery(host, manager, name, transaction, was_enabled):
    # user:“该修修 如果是架构问题就重构”+(恢复按阶段重试；清理未成功时保留事务和备份，不能误报回滚完成)。
    restored = False

    async def recover():
        nonlocal restored
        if not restored:
            await manager.stop(name)
            manager.forget(name)
            if transaction:
                transaction.rollback()
            else:
                host.uninstall(name, keep_data=True)
            host._invalidate()
            restored = True
        if was_enabled and not safe_mode():
            if not await manager.start(name):
                raise RuntimeError("original backend did not restart")
        refresh_catalogs(host)

    return recover


async def install_or_update(host, payload, *, update=False):
    # Download and unpack outside the mutation lock; they cannot change the
    # installed plugin. The source is validated before touching a live runtime.
    from .capabilities import read_capabilities
    from .operation_bridge import read_operations
    from .ui import read_ui
    from .agent import read_agent
    from .engine import check_engine, read_engine
    from .installer import dependency_report
    source = source_directory(payload)
    entering = asyncio.create_task(asyncio.to_thread(source.__enter__))
    try:
        directory = await asyncio.shield(entering)
    except asyncio.CancelledError:
        await entering
        source.__exit__(None, None, None)
        raise
    try:
        incoming = load_manifest(directory / "plugin.json")
        # user:“安装的时候直接从 GitHub 上”+(市场包的清单身份必须与所选发布项完全一致，验证在停止旧插件之前)。
        if payload.get("expected_name") and incoming.name != payload["expected_name"]:
            raise ValueError("安装包插件名称与市场条目不一致")
        if payload.get("expected_version") and incoming.version != payload["expected_version"]:
            raise ValueError("安装包版本与市场条目不一致")
        for read in (read_capabilities, read_operations, read_ui, read_agent):
            read(incoming)
        errors = check_engine(read_engine(incoming))
        if errors:
            raise ValueError("; ".join(errors))
        manager = supervisor(host)
        async with manager.mutation(incoming.name):
            existing = host.get(incoming.name)
            if update and existing is None:
                raise ValueError("plugin is not installed")
            if not update and existing is not None:
                raise ValueError("plugin already exists; use update")
            name = incoming.name
            if existing:
                host._assert_mutable(existing)
            validate_conflicts(host, incoming)
            transaction = None
            target = None
            was_enabled = bool(existing and existing.enabled)
            stopped = False
            try:
                await manager.drain(name)
                await manager.stop(name)
                stopped = True
                manager.forget(name)
                # user:“修完打包发布新版本”+(首次安装和更新共用持久事务，后端就绪后才提交)。
                io = asyncio.create_task(asyncio.to_thread(host.begin_update if update else host.begin_install, directory))
                try:
                    transaction = await asyncio.shield(io)
                except asyncio.CancelledError:
                    transaction = await io
                    target = transaction.target
                    raise
                target = transaction.target
                host._invalidate()
                if host.get(name).enabled and not safe_mode():
                    if not await manager.start(name):
                        raise RuntimeError("replacement backend did not start")
                refresh_catalogs(host)
                if transaction:
                    transaction.commit()
            except BaseException:
                if target is not None:
                    manager.recoveries[name] = replacement_recovery(host, manager, name, transaction, was_enabled)
                    await manager.recover_pending(name)
                elif stopped and was_enabled and not safe_mode():
                    # A file-lock/copy error occurred before the swap. The old
                    # code is still intact and must regain its backend.
                    await manager.start(name)
                    refresh_catalogs(host)
                raise
        report = dependency_report(host, name)
        return {"name": name, "updated" if update else "installed": True,
                "root": str(target), "data_path": str(host.data_path(name)),
                "available": host.available(name), "backend": manager.status(name),
                "dependencies": report["dependencies"], "missing_dependencies": report["missing"],
                "restart_required": bool(incoming.raw.get("overrides") or incoming.raw.get("ui"))}
    finally:
        source.__exit__(None, None, None)
