"""Library 本机文件的 live RPC 注册。

user:“搜索 → 预览 → 操作 → 收藏，这是完整闭环”+(界面和助手都通过同一组
操作访问：库侧只注册 libraryfs.*，不改动现有 artifact.*、项目文件与分屏的
任何约定)。
"""

from __future__ import annotations

import logging
from typing import Any

from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator

from .everything import EverythingProvider
from .service import LibraryFileService
from .store import FileAssetStore

_logger = logging.getLogger(__name__)

LIBRARY_OPERATION_NAMES: tuple[str, ...] = (
    "libraryfs.status",
    "libraryfs.setup",
    "libraryfs.roots",
    "libraryfs.search",
    "libraryfs.browse",
    "libraryfs.stat",
    "libraryfs.preview",
    "libraryfs.thumbs",
    "libraryfs.asset.get",
    "libraryfs.asset.update",
    "libraryfs.asset.list",
    "libraryfs.asset.forget",
    "libraryfs.asset.relink",
    "libraryfs.collection.list",
    "libraryfs.collection.create",
    "libraryfs.collection.update",
    "libraryfs.collection.delete",
    "libraryfs.collection.items",
    "libraryfs.collection.add",
    "libraryfs.collection.remove",
    "libraryfs.file.operate",
    "libraryfs.open",
    "libraryfs.reveal",
)


def build_library_service(
    *,
    session_factory: Any,
    write_coordinator: SQLiteWriteCoordinator | None = None,
    data_dir: str | None = None,
) -> LibraryFileService:
    store = FileAssetStore(session_factory, write_coordinator)
    provider = EverythingProvider(data_dir=data_dir)
    return LibraryFileService(store, provider)


def register_library_operations(
    catalog: OperationCatalog,
    *,
    service: LibraryFileService,
) -> LibraryFileService:
    """把服务挂进共享操作目录；重复注册时保持先注册的那一份。"""

    def register(name: str, handler: Any) -> None:
        if catalog.has(name):
            return

        async def wrapped(request: OperationRequest, _handler=handler) -> OperationResult:
            try:
                payload = await _handler(request.payload if isinstance(request.payload, dict) else {})
                return OperationResult(name=request.name, payload=payload)
            except FileNotFoundError as exc:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": f"文件不存在: {exc}", "code": "not_found"},
                )
            except PermissionError as exc:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": f"没有访问权限: {exc}", "code": "permission_denied"},
                )
            except (ValueError, OSError) as exc:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": str(exc), "code": type(exc).__name__},
                )
            except Exception as exc:  # noqa: BLE001 - RPC 不能因为一个坏文件整体 500
                _logger.warning("library operation %s failed: %s", request.name, exc, exc_info=True)
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": f"操作失败: {exc}", "code": "internal_error"},
                )

        catalog.register(name, wrapped, owner="library")

    register("libraryfs.status", lambda payload: service.status())
    register("libraryfs.setup", lambda payload: service.install_engine())
    register("libraryfs.roots", lambda payload: service.roots())
    register("libraryfs.search", lambda payload: service.search(payload))
    register("libraryfs.browse", lambda payload: service.browse(
        str(payload.get("path") or ""),
        limit=int(payload.get("limit") or 800),
        sort=str(payload.get("sort") or "name"),
        show_hidden=bool(payload.get("show_hidden")),
    ))
    register("libraryfs.stat", lambda payload: service.stat(str(payload.get("path") or "")))
    register("libraryfs.preview", lambda payload: service.preview(str(payload.get("path") or "")))
    register("libraryfs.thumbs", lambda payload: service.thumbs(
        payload.get("paths") or [],
        size=int(payload.get("size") or 320),
    ))
    register("libraryfs.asset.get", lambda payload: service.asset_get(str(payload.get("path") or "")))
    register("libraryfs.asset.update", lambda payload: service.asset_update(payload))
    register("libraryfs.asset.list", lambda payload: service.asset_list(payload))
    register("libraryfs.asset.forget", lambda payload: service.asset_forget(
        [str(item) for item in (payload.get("asset_ids") or [])]
    ))
    register("libraryfs.asset.relink", lambda payload: service.asset_relink(
        str(payload.get("asset_id") or ""),
        str(payload.get("path") or ""),
    ))
    register("libraryfs.collection.list", lambda payload: service.collections())
    register("libraryfs.collection.create", lambda payload: service.collection_create(payload))
    register("libraryfs.collection.update", lambda payload: service.collection_update(payload))
    register("libraryfs.collection.delete", lambda payload: service.collection_delete(
        str(payload.get("collection_id") or "")
    ))
    register("libraryfs.collection.items", lambda payload: service.collection_items(
        str(payload.get("collection_id") or ""),
        limit=int(payload.get("limit") or 300),
        offset=int(payload.get("offset") or 0),
    ))
    register("libraryfs.collection.add", lambda payload: service.collection_add(
        str(payload.get("collection_id") or ""),
        [str(item) for item in (payload.get("paths") or [])],
    ))
    register("libraryfs.collection.remove", lambda payload: service.collection_remove(
        str(payload.get("collection_id") or ""),
        [str(item) for item in (payload.get("asset_ids") or [])],
    ))
    register("libraryfs.file.operate", lambda payload: service.operate(payload))
    register("libraryfs.open", lambda payload: service.open_path(str(payload.get("path") or "")))
    register("libraryfs.reveal", lambda payload: service.reveal_path(str(payload.get("path") or "")))
    return service
