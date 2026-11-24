"""Library 文件服务：搜索、浏览、预览、资产与集合的统一入口。

user:“搜索结果、目录浏览和收藏集合调用同一套预览能力”“全盘文件与收藏资产
共用一套界面和文件身份关系”+(前端、助手、RPC 都走这里：一次搜索把 Everything
结果与资产账本按路径合并；一次资产操作只改账本，不动文件；一次文件操作
直接作用于原文件，并同步它对应的资产身份)。
"""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime
import io
import mimetypes
import os
from pathlib import Path
import threading
from typing import Any, Iterable

from .everything import (
    EverythingError,
    EverythingProvider,
    FileHit,
    KIND_EXTENSIONS,
    SearchSpec,
    compile_query,
    install_es,
)
from .file_ops import operate as operate_files
from .file_ops import open_with_system, reveal_in_explorer
from .identity import identity_for, normalize_path, path_key
from .store import FileAssetStore, asset_to_dict

_KIND_BY_EXT: dict[str, str] = {}
for _kind, _exts in KIND_EXTENSIONS.items():
    for _ext in _exts:
        _KIND_BY_EXT[_ext] = _kind

_TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "json", "jsonc", "yaml", "yml", "toml", "ini", "cfg", "conf",
    "log", "csv", "tsv", "xml", "html", "htm", "css", "scss", "less", "js", "jsx", "ts",
    "tsx", "vue", "py", "rs", "go", "java", "kt", "c", "h", "cpp", "hpp", "cs", "rb",
    "php", "sh", "ps1", "bat", "cmd", "sql", "lua", "r", "swift", "dart", "gradle",
}

_MAX_TEXT_BYTES = 500_000
_MAX_THUMBS = 48
_THUMB_CACHE_BYTES = 48 * 1024 * 1024


def kind_of(path: str, *, is_dir: bool = False) -> str:
    if is_dir:
        return "folder"
    suffix = Path(path).suffix.lstrip(".").lower()
    if suffix in _KIND_BY_EXT:
        return _KIND_BY_EXT[suffix]
    if suffix == "pdf":
        return "document"
    if suffix in _TEXT_EXTENSIONS:
        return "document"
    return "other"


def _parse_spec(payload: dict[str, Any]) -> SearchSpec:
    kinds = payload.get("kinds")
    if kinds is None:
        single = str(payload.get("kind") or "").strip()
        kinds = [single] if single and single != "all" else []
    if isinstance(kinds, str):
        kinds = [kinds]
    extensions = payload.get("extensions") or []
    if isinstance(extensions, str):
        extensions = [extensions]
    return SearchSpec(
        query=str(payload.get("query") or payload.get("q") or ""),
        kinds=[str(item) for item in kinds if str(item).strip()],
        extensions=[str(item) for item in extensions if str(item).strip()],
        scope=str(payload.get("scope") or ""),
        size_min=payload.get("size_min"),
        size_max=payload.get("size_max"),
        modified_within_days=payload.get("modified_within_days"),
        created_within_days=payload.get("created_within_days"),
        sort=str(payload.get("sort") or "relevance"),
        descending=bool(payload.get("descending")),
        offset=int(payload.get("offset") or 0),
        limit=int(payload.get("limit") or 60),
        match_path=bool(payload.get("match_path")),
        regex=bool(payload.get("regex")),
        case_sensitive=bool(payload.get("case_sensitive")),
    )


def _asset_summary(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = asset_to_dict(row) if not isinstance(row, dict) else row
    return {
        "asset_id": data.get("asset_id", ""),
        "display_name": data.get("display_name", ""),
        "favorite": bool(data.get("favorite")),
        "rating": int(data.get("rating") or 0),
        "tags": list(data.get("tags") or []),
        "note": data.get("note", ""),
        "missing": bool(data.get("missing")),
    }


def _fallback_hit(path: str) -> dict[str, Any]:
    try:
        stat = os.stat(path)
        is_dir = os.path.isdir(path)
    except OSError:
        return {
            "path": path,
            "name": Path(path).name,
            "directory": str(Path(path).parent),
            "extension": Path(path).suffix.lstrip(".").lower(),
            "size": 0,
            "modified_at": "",
            "created_at": "",
            "is_dir": False,
            "missing": True,
            "kind": kind_of(path),
        }
    return {
        "path": path,
        "name": Path(path).name,
        "directory": str(Path(path).parent),
        "extension": "" if is_dir else Path(path).suffix.lstrip(".").lower(),
        "size": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
        "is_dir": is_dir,
        "missing": False,
        "kind": kind_of(path, is_dir=is_dir),
    }


class LibraryFileService:
    """Everything + 文件系统 + 资产账本的组合服务（本机全局）。"""

    def __init__(self, store: FileAssetStore, provider: EverythingProvider) -> None:
        self.store = store
        self.provider = provider
        self._thumb_cache: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()
        self._thumb_bytes = 0
        self._thumb_lock = threading.Lock()
        self._engine_install: asyncio.Task[dict[str, Any]] | None = None
        self._siblings_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # -- engine --------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        payload = await asyncio.to_thread(self.provider.status)
        payload["asset_count"] = await self.store.count()
        payload["collections"] = len(await self.store.list_collections())
        return payload

    async def install_engine(self) -> dict[str, Any]:
        """用户点「下载查询工具」时安装官方 ES；不静默、不装服务。"""
        # user:“修”+(多个请求共享一次安装，等待方断线也不会取消后台安装)。
        task = self._engine_install
        if task is None or task.done():
            task = asyncio.create_task(self._install_engine(), name="library-everything-install")
            self._engine_install = task
            task.add_done_callback(self._finish_engine_install)
        return await asyncio.shield(task)

    def _finish_engine_install(self, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._engine_install is task:
            self._engine_install = None
        if not task.cancelled():
            task.exception()  # The last waiter may have disconnected.

    async def _install_engine(self) -> dict[str, Any]:
        installation = await asyncio.to_thread(install_es, self.provider.es_install_dir())
        self.provider.refresh()
        status = await self.status()
        return {"installation": installation, "status": status}

    # -- search --------------------------------------------------------
    async def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = _parse_spec(payload)
        only_assets = bool(payload.get("only_assets")) or spec.scope == "assets"
        tags = [str(item) for item in (payload.get("tags") or []) if str(item).strip()]
        rating_min = int(payload.get("rating_min") or 0)
        favorite_only = bool(payload.get("favorite_only"))
        asset_filters = bool(tags or rating_min or favorite_only)

        if only_assets or (asset_filters and not spec.query.strip()):
            assets = await self._filter_assets(
                query=spec.query,
                kinds=spec.kinds,
                tags=tags,
                rating_min=rating_min,
                favorite_only=favorite_only,
                sort=spec.sort,
                descending=spec.descending,
                offset=spec.offset,
                limit=spec.limit,
                refresh=bool(payload.get("refresh")),
            )
            return {
                "items": [_asset_as_item(item) for item in assets["items"]],
                "total": assets["total"],
                "offset": spec.offset,
                "limit": spec.limit,
                "elapsed_ms": assets["elapsed_ms"],
                "query": "",
                "source": "assets",
                "total_exact": True,
            }

        if not spec.query.strip() and not spec.kinds and not spec.extensions:
            # 空搜索首页展示最近变更，而不是把整盘按名字倒出来。
            spec = replace(
                spec,
                modified_within_days=7,
                sort="date_modified",
                descending=True,
                limit=spec.limit,
            )
        try:
            page = await asyncio.to_thread(self.provider.search, spec)
        except EverythingError as exc:
            return {
                "items": [],
                "total": None,
                "offset": spec.offset,
                "limit": spec.limit,
                "elapsed_ms": 0,
                "query": compile_query(spec),
                "source": "everything",
                "error": exc.to_dict(),
            }

        hits = page.items
        assets = await self.store.by_path_keys([path_key(hit.path) for hit in hits])
        items: list[dict[str, Any]] = []
        for hit in hits:
            item = hit.to_dict()
            asset = assets.get(path_key(hit.path))
            item["kind"] = kind_of(hit.path, is_dir=hit.is_dir)
            item["asset"] = _asset_summary(asset)
            item["missing"] = False
            if asset_filters and not _matches_asset_filters(asset, tags, rating_min, favorite_only):
                continue
            items.append(item)
        total = len(items) if asset_filters else page.total
        return {
            "items": items,
            "total": total,
            "offset": page.offset,
            "limit": page.limit,
            "elapsed_ms": page.elapsed_ms,
            "query": page.query,
            "source": "everything",
            "total_exact": not asset_filters,
            "count_error": page.count_error,
        }

    async def _filter_assets(
        self,
        *,
        query: str,
        kinds: list[str],
        tags: list[str],
        rating_min: int,
        favorite_only: bool,
        sort: str,
        descending: bool,
        offset: int,
        limit: int,
        refresh: bool = False,
    ) -> dict[str, Any]:
        started = datetime.now()
        rows = await self.store.list_all()
        needle = query.strip().lower()
        filtered = []
        for row in rows:
            if needle and needle not in (row.path or "").lower() and needle not in (row.name or "").lower():
                continue
            if kinds and kind_of(row.path, is_dir=bool(row.is_dir)) not in kinds:
                continue
            if tags:
                owned = set(row.tags_json or [])
                if not all(tag.lower() in owned for tag in tags):
                    continue
            if rating_min and int(row.rating or 0) < rating_min:
                continue
            if favorite_only and not row.favorite:
                continue
            filtered.append(row)
        if refresh:
            await self._refresh_missing(filtered[:limit + offset])
        if sort == "size":
            filtered.sort(key=lambda row: int(row.size or 0), reverse=descending)
        elif sort in {"date_modified", "modified"}:
            filtered.sort(key=lambda row: int(row.mtime_ns or 0), reverse=not descending)
        elif sort == "rating":
            filtered.sort(key=lambda row: int(row.rating or 0), reverse=not descending)
        elif sort == "name":
            filtered.sort(key=lambda row: (row.name or "").lower(), reverse=descending)
        else:
            filtered.sort(key=lambda row: row.updated_at or datetime.min, reverse=not descending)
        slice_ = filtered[offset:offset + limit]
        elapsed = int((datetime.now() - started).total_seconds() * 1000)
        return {
            "items": [asset_to_dict(row) for row in slice_],
            "total": len(filtered),
            "elapsed_ms": elapsed,
        }

    async def _refresh_missing(self, rows: Iterable[Any]) -> int:
        """检查路径还在不在；离线只标记，不删记录。"""
        changed = 0
        for row in rows:
            exists = await asyncio.to_thread(os.path.exists, row.path)
            if exists == bool(row.missing) and exists:
                continue
            if not exists:
                await self.store.mark_missing([row.asset_id], missing=True)
                changed += 1
            elif bool(row.missing):
                await self.store.mark_missing([row.asset_id], missing=False)
                changed += 1
        return changed

    # -- browse --------------------------------------------------------
    async def roots(self) -> dict[str, Any]:
        return {"roots": await asyncio.to_thread(self._list_roots)}

    def _list_roots(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                entries.append({"path": drive, "name": f"{letter}:", "kind": "drive"})
        home = Path.home()
        known = [
            ("桌面", home / "Desktop"),
            ("下载", home / "Downloads"),
            ("文档", home / "Documents"),
            ("图片", home / "Pictures"),
            ("视频", home / "Videos"),
            ("音乐", home / "Music"),
        ]
        for label, path in known:
            if path.is_dir():
                entries.append({"path": str(path), "name": label, "kind": "place"})
        entries.append({"path": str(home), "name": "用户目录", "kind": "place"})
        return entries

    async def browse(self, path: str, *, limit: int = 800, sort: str = "name", show_hidden: bool = False) -> dict[str, Any]:
        target = normalize_path(path) if str(path or "").strip() else ""
        if not target:
            return {"path": "", "entries": [], "roots": self._list_roots(), "parent": ""}
        if not os.path.isdir(target):
            return {"path": target, "entries": [], "parent": str(Path(target).parent), "error": "目录不存在"}
        entries = await asyncio.to_thread(self._scan_dir, target, max(1, min(3000, int(limit))), sort, show_hidden)
        keys = [path_key(item["path"]) for item in entries]
        assets = await self.store.by_path_keys(keys)
        for item in entries:
            item["asset"] = _asset_summary(assets.get(path_key(item["path"])))
        parent = str(Path(target).parent)
        if parent == target:
            parent = ""
        return {
            "path": target,
            "parent": parent,
            "entries": entries,
            "truncated": len(entries) >= limit,
        }

    def _scan_dir(self, target: str, limit: int, sort: str, show_hidden: bool) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            iterator = os.scandir(target)
        except OSError as exc:
            return [{"path": target, "name": "", "error": str(exc)}]
        with iterator:
            for entry in iterator:
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if not show_hidden:
                    attrs = getattr(stat, "st_file_attributes", 0)
                    if attrs & 0x2:  # FILE_ATTRIBUTE_HIDDEN
                        continue
                    if attrs & 0x4:  # FILE_ATTRIBUTE_SYSTEM
                        continue
                entries.append({
                    "path": str(Path(target) / entry.name),
                    "name": entry.name,
                    "size": 0 if is_dir else int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "is_dir": is_dir,
                    "kind": kind_of(entry.name, is_dir=is_dir),
                })
        if sort == "size":
            entries.sort(key=lambda item: (not item["is_dir"], -int(item.get("size") or 0)))
        elif sort in {"date_modified", "modified"}:
            entries.sort(key=lambda item: (not item["is_dir"], -int(item.get("mtime_ns") or 0)))
        else:
            entries.sort(key=lambda item: (not item["is_dir"], str(item["name"]).lower()))
        return entries[:limit]

    # -- preview -------------------------------------------------------
    async def stat(self, path: str) -> dict[str, Any]:
        """轻量属性：不读文件内容，给助手和结果栏用。"""
        target = normalize_path(path)
        if not os.path.exists(target):
            return {"path": target, "item": {}, "error": "文件不存在"}
        item = _fallback_hit(target)
        record = await self.store.touch_path(target, create=False)
        item["asset"] = _asset_summary(record)
        return {"path": target, "item": item}

    async def preview(self, path: str, *, max_chars: int = 200_000) -> dict[str, Any]:
        target = normalize_path(path)
        if not os.path.exists(target):
            return {"path": target, "kind": "missing", "error": "文件不存在"}
        is_dir = os.path.isdir(target)
        stat = await asyncio.to_thread(os.stat, target)
        extension = "" if is_dir else Path(target).suffix.lstrip(".").lower()
        kind = kind_of(target, is_dir=is_dir)
        mime = "inode/directory" if is_dir else (mimetypes.guess_type(target)[0] or "application/octet-stream")
        asset = await self.store.touch_path(target, create=False)
        payload: dict[str, Any] = {
            "path": target,
            "name": Path(target).name,
            "kind": kind,
            "extension": extension,
            "mime": mime,
            "size": int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds"),
            "is_dir": is_dir,
            "asset": asset,
            "text": "",
            "previewable": True,
            "siblings": [],
        }
        if is_dir:
            payload["previewable"] = False
            payload["entry_count"] = await asyncio.to_thread(self._count_dir, target)
            return payload
        if kind == "image":
            payload["siblings"] = await self._siblings(target, "image")
            return payload
        if kind in {"video", "audio"}:
            payload["siblings"] = await self._siblings(target, kind)
            return payload
        if extension == "pdf":
            payload["previewable"] = True
            return payload
        if extension in _TEXT_EXTENSIONS:
            payload["text"] = await asyncio.to_thread(self._read_text, target, max_chars)
            return payload
        if extension in {"docx", "xlsx", "pptx"}:
            payload["text"] = await asyncio.to_thread(self._read_office_text, target)
            return payload
        payload["previewable"] = False
        return payload

    def _count_dir(self, target: str) -> int:
        try:
            with os.scandir(target) as iterator:
                return sum(1 for _ in iterator)
        except OSError:
            return 0

    def _read_text(self, path: str, max_chars: int) -> str:
        raw = Path(path).read_bytes()[:_MAX_TEXT_BYTES]
        for encoding in ("utf-8-sig", "utf-16", "gb18030", "latin-1"):
            try:
                return raw.decode(encoding)[:max_chars]
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", "replace")[:max_chars]

    def _read_office_text(self, path: str) -> str:
        """常用文档的纯文本预览；失败就返回空，交给系统程序打开。"""
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".docx":
                import docx

                document = docx.Document(path)
                return "\n".join(para.text for para in document.paragraphs)[:200_000]
            if suffix == ".xlsx":
                import openpyxl

                workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
                lines: list[str] = []
                for sheet in workbook.worksheets[:3]:
                    lines.append(f"# {sheet.title}")
                    for row in sheet.iter_rows(max_row=200, values_only=True):
                        values = ["" if value is None else str(value) for value in row]
                        if any(values):
                            lines.append("\t".join(values))
                workbook.close()
                return "\n".join(lines)[:200_000]
            if suffix == ".pptx":
                from pptx import Presentation

                deck = Presentation(path)
                lines = []
                for index, slide in enumerate(deck.slides, start=1):
                    lines.append(f"# 第 {index} 页")
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            lines.append(shape.text.strip())
                return "\n".join(lines)[:200_000]
        except Exception as exc:  # noqa: BLE001 - 预览失败不能拖垮整个文件
            return f"（无法预览这个文档：{exc}）"
        return ""

    async def _siblings(self, path: str, kind: str, limit: int = 400) -> list[dict[str, Any]]:
        directory = str(Path(path).parent)
        cache_key = f"{directory}\x00{kind}"
        cached = self._siblings_cache.get(cache_key)
        now = datetime.now().timestamp()
        if cached and now - cached[0] < 20:
            items = cached[1]
        else:
            items = await asyncio.to_thread(self._scan_siblings, directory, kind, limit)
            self._siblings_cache[cache_key] = (now, items)
            if len(self._siblings_cache) > 40:
                self._siblings_cache.clear()
        # 当前文件排在第一，预览器左右键从它开始。
        current = os.path.normcase(path)
        items = sorted(items, key=lambda item: 0 if os.path.normcase(item["path"]) == current else 1)
        return items

    def _scan_siblings(self, directory: str, kind: str, limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    if kind_of(entry.name) != kind:
                        continue
                    items.append({"path": str(Path(directory) / entry.name), "name": entry.name})
                    if len(items) >= limit:
                        break
        except OSError:
            return []
        return items

    async def thumbs(self, paths: Iterable[str], *, size: int = 320) -> dict[str, Any]:
        size = max(64, min(512, int(size)))
        wanted = [normalize_path(path) for path in list(paths)[:_MAX_THUMBS] if str(path).strip()]
        return await asyncio.to_thread(self._build_thumbs, wanted, size)

    def _build_thumbs(self, paths: list[str], size: int) -> dict[str, Any]:
        from PIL import Image, ImageOps

        results: list[dict[str, Any]] = []
        for path in paths:
            try:
                stamp = os.stat(path).st_mtime_ns
            except OSError:
                stamp = 0
            cache_key = f"{path_key(path)}\x00{size}\x00{stamp}"
            with self._thumb_lock:
                cached = self._thumb_cache.get(cache_key)
                if cached is not None:
                    self._thumb_cache.move_to_end(cache_key)
                    results.append({"path": path, "mime": cached[1], "data": base64.b64encode(cached[2]).decode("ascii")})
                    continue
            if kind_of(path) != "image" or not os.path.isfile(path):
                results.append({"path": path, "mime": "", "data": ""})
                continue
            try:
                with Image.open(path) as image:
                    image = ImageOps.exif_transpose(image)
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA")
                    image.thumbnail((size, size))
                    buffer = io.BytesIO()
                    if image.mode == "RGBA":
                        canvas = Image.new("RGB", image.size, (255, 255, 255))
                        canvas.paste(image, mask=image.split()[-1])
                        canvas.save(buffer, format="JPEG", quality=82)
                    else:
                        image.save(buffer, format="JPEG", quality=82)
                    payload = buffer.getvalue()
            except Exception:  # noqa: BLE001 - 个别图片解不开不影响整批
                results.append({"path": path, "mime": "", "data": ""})
                continue
            with self._thumb_lock:
                self._thumb_cache[cache_key] = (datetime.now().timestamp(), "image/jpeg", payload)
                self._thumb_bytes += len(payload)
                while self._thumb_bytes > _THUMB_CACHE_BYTES and len(self._thumb_cache) > 1:
                    _, (_, _, dropped) = self._thumb_cache.popitem(last=False)
                    self._thumb_bytes -= len(dropped)
            results.append({"path": path, "mime": "image/jpeg", "data": base64.b64encode(payload).decode("ascii")})
        return {"items": results}

    # -- assets --------------------------------------------------------
    async def asset_get(self, path: str) -> dict[str, Any]:
        target = normalize_path(path)
        record = await self.store.touch_path(target, create=False)
        return {"path": target, "asset": record}

    async def asset_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = str(payload.get("path") or "").strip()
        if not path:
            raise ValueError("缺少文件路径")
        record = await self.store.update_path(
            path,
            favorite=payload.get("favorite") if "favorite" in payload else None,
            rating=payload.get("rating") if "rating" in payload else None,
            tags=payload.get("tags") if "tags" in payload else None,
            add_tags=payload.get("add_tags"),
            remove_tags=payload.get("remove_tags"),
            display_name=payload.get("display_name") if "display_name" in payload else None,
            note=payload.get("note") if "note" in payload else None,
        )
        return {"asset": record}

    async def asset_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._filter_assets(
            query=str(payload.get("query") or ""),
            kinds=[str(item) for item in (payload.get("kinds") or []) if str(item).strip()],
            tags=[str(item) for item in (payload.get("tags") or []) if str(item).strip()],
            rating_min=int(payload.get("rating_min") or 0),
            favorite_only=bool(payload.get("favorite_only")),
            sort=str(payload.get("sort") or "recent"),
            descending=bool(payload.get("descending")),
            offset=int(payload.get("offset") or 0),
            limit=min(500, int(payload.get("limit") or 100)),
            refresh=bool(payload.get("refresh")),
        )
        return {
            "assets": result["items"],
            "total": result["total"],
            "elapsed_ms": result["elapsed_ms"],
        }

    async def asset_forget(self, asset_ids: list[str]) -> dict[str, Any]:
        """只移除管理记录，磁盘文件原样保留。"""
        deleted = await self.store.forget(asset_ids)
        return {"deleted": deleted}

    async def asset_relink(self, asset_id: str, path: str) -> dict[str, Any]:
        target = normalize_path(path)
        try:
            identity = await asyncio.to_thread(identity_for, target)
        except OSError as exc:
            raise ValueError(f"无法确认这个文件: {exc}") from exc
        existing = await self.store.get(asset_id)
        if existing is None:
            raise ValueError("资产记录不存在")
        if existing.identity_kind == "fileid" and identity.identity_key != existing.identity_key:
            raise ValueError("这个文件与原来的资产不是同一份文件，不能直接关联")
        record = await self.store.relink(asset_id, target)
        if record is None:
            raise ValueError("重新关联失败")
        return {"asset": record}

    # -- collections ---------------------------------------------------
    async def collections(self) -> dict[str, Any]:
        return {"collections": await self.store.list_collections()}

    async def collection_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = await self.store.create_collection(
            str(payload.get("name") or ""),
            kind=str(payload.get("kind") or "manual"),
            query=payload.get("query") if isinstance(payload.get("query"), dict) else {},
        )
        return {"collection": record}

    async def collection_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = await self.store.update_collection(
            str(payload.get("collection_id") or ""),
            name=payload.get("name"),
            query=payload.get("query") if isinstance(payload.get("query"), dict) else None,
        )
        if record is None:
            raise ValueError("集合不存在")
        return {"collection": record}

    async def collection_delete(self, collection_id: str) -> dict[str, Any]:
        return {"deleted": await self.store.delete_collection(collection_id)}

    async def collection_items(self, collection_id: str, *, limit: int = 300, offset: int = 0) -> dict[str, Any]:
        async with self.store.session_factory() as db:
            from lamtools_core.app.core_db import CoreFileCollection

            collection = await db.get(CoreFileCollection, collection_id)
            if collection is None:
                raise ValueError("集合不存在")
            kind = collection.kind
            query = dict(collection.query_json or {})
            name = collection.name
        if kind != "smart":
            rows = await self.store.collection_assets(collection_id)
            items = [_asset_as_item(asset_to_dict(row)) for row in rows[offset:offset + limit]]
            return {"collection_id": collection_id, "name": name, "kind": kind, "query": query, "items": items, "total": len(rows)}
        items = await self._evaluate_smart(query, limit=limit, offset=offset)
        return {
            "collection_id": collection_id,
            "name": name,
            "kind": kind,
            "query": query,
            "items": items["items"],
            "total": items["total"],
        }

    async def _evaluate_smart(self, query: dict[str, Any], *, limit: int, offset: int) -> dict[str, Any]:
        spec = _parse_spec(query)
        tags = [str(item) for item in (query.get("tags") or []) if str(item).strip()]
        rating_min = int(query.get("rating_min") or 0)
        favorite_only = bool(query.get("favorite_only"))
        has_fs_conditions = bool(spec.query.strip() or spec.kinds or spec.scope or spec.extensions
                                 or spec.size_min is not None or spec.size_max is not None
                                 or spec.modified_within_days or spec.created_within_days)
        if not has_fs_conditions:
            rows = await self._filter_assets(
                query="", kinds=spec.kinds, tags=tags, rating_min=rating_min,
                favorite_only=favorite_only, sort=query.get("sort") or "recent",
                descending=bool(query.get("descending")), offset=offset, limit=limit,
            )
            return {"items": [_asset_as_item(item) for item in rows["items"]], "total": rows["total"]}
        page = await asyncio.to_thread(self.provider.search, spec)
        assets = await self.store.by_path_keys([path_key(hit.path) for hit in page.items])
        items: list[dict[str, Any]] = []
        for hit in page.items:
            asset = assets.get(path_key(hit.path))
            if (tags or rating_min or favorite_only) and not _matches_asset_filters(asset, tags, rating_min, favorite_only):
                continue
            item = hit.to_dict()
            item["kind"] = kind_of(hit.path, is_dir=hit.is_dir)
            item["asset"] = _asset_summary(asset)
            items.append(item)
        return {"items": items[offset:offset + limit], "total": len(items)}

    async def collection_add(self, collection_id: str, paths: list[str]) -> dict[str, Any]:
        asset_ids: list[str] = []
        for path in paths[:500]:
            try:
                asset_ids.append(await self.store.asset_id_for_path(str(path)))
            except (OSError, ValueError):
                continue
        added = await self.store.add_to_collection(collection_id, asset_ids)
        return {"added": added, "assets": len(asset_ids)}

    async def collection_remove(self, collection_id: str, asset_ids: list[str]) -> dict[str, Any]:
        return {"removed": await self.store.remove_from_collection(collection_id, asset_ids)}

    # -- file actions --------------------------------------------------
    async def operate(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(
            operate_files,
            str(payload.get("op") or ""),
            paths=[str(item) for item in (payload.get("paths") or [])],
            target_dir=str(payload.get("target_dir") or ""),
            new_name=str(payload.get("new_name") or ""),
            conflict=str(payload.get("conflict") or "rename"),
            confirm=bool(payload.get("confirm")),
        )
        await self._sync_assets_after_ops(str(payload.get("op") or ""), result)
        return result

    async def _sync_assets_after_ops(self, op: str, result: dict[str, Any]) -> None:
        """Library 自己移动/改名后，资产记录立刻跟过去，不等下一次搜索。"""
        action = op.lower()
        for item in result.get("items", []):
            if item.get("status") != "ok":
                continue
            source = str(item.get("path") or "")
            target = str(item.get("target") or "")
            if not source:
                continue
            record = await self.store.get_by_path(source)
            if record is None:
                continue
            if action in {"move", "rename"} and target:
                await self.store.relink(record.asset_id, target)
            elif action in {"trash", "delete"}:
                await self.store.mark_missing([record.asset_id], missing=True)

    async def open_path(self, path: str) -> dict[str, Any]:
        await asyncio.to_thread(open_with_system, path)
        return {"opened": normalize_path(path)}

    async def reveal_path(self, path: str) -> dict[str, Any]:
        await asyncio.to_thread(reveal_in_explorer, path)
        return {"revealed": normalize_path(path)}

    async def raw_path(self, path: str) -> Path:
        target = Path(normalize_path(path))
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target


def _matches_asset_filters(row: Any, tags: list[str], rating_min: int, favorite_only: bool) -> bool:
    if row is None:
        return not (tags or rating_min or favorite_only)
    owned = set(getattr(row, "tags_json", None) or (row.get("tags") if isinstance(row, dict) else []) or [])
    if tags and not all(tag.lower() in owned for tag in tags):
        return False
    if rating_min and int(getattr(row, "rating", 0) or 0) < rating_min:
        return False
    if favorite_only and not getattr(row, "favorite", False):
        return False
    return True


def _asset_as_item(record: dict[str, Any]) -> dict[str, Any]:
    path = str(record.get("path") or "")
    return {
        "path": path,
        "name": record.get("name") or Path(path).name,
        "directory": str(Path(path).parent),
        "extension": record.get("extension") or Path(path).suffix.lstrip(".").lower(),
        "size": int(record.get("size") or 0),
        "modified_at": datetime.fromtimestamp(int(record.get("mtime_ns") or 0) / 1e9).isoformat(timespec="seconds")
        if record.get("mtime_ns") else "",
        "created_at": "",
        "is_dir": bool(record.get("is_dir")),
        "missing": bool(record.get("missing")),
        "kind": kind_of(path, is_dir=bool(record.get("is_dir"))),
        "asset": {
            "asset_id": record.get("asset_id", ""),
            "display_name": record.get("display_name", ""),
            "favorite": bool(record.get("favorite")),
            "rating": int(record.get("rating") or 0),
            "tags": list(record.get("tags") or []),
            "note": record.get("note", ""),
            "missing": bool(record.get("missing")),
        },
    }


def hit_to_item(hit: FileHit, asset: Any = None) -> dict[str, Any]:
    item = hit.to_dict()
    item["kind"] = kind_of(hit.path, is_dir=hit.is_dir)
    item["asset"] = _asset_summary(asset)
    return item
