"""资产层存储：只记录用户真正管理过的文件，不预写全盘结果。

user:“搜索到的文件不代表已被 Library 收藏或管理”“不需要复制原文件，也不需要
改变原文件的位置”+(命中结果只做展示；收藏、标签、评分、备注、集合这些动作
发生时，才为文件建立一行管理记录。原文件不搬家)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import uuid
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from lamtools_core.app.core_db import CoreFileAsset, CoreFileCollection, CoreFileCollectionItem
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator

from .identity import FileIdentity, identity_for, normalize_path, path_key

MAX_TAGS = 24
MAX_TAG_LENGTH = 32


def normalize_tags(tags: Iterable[Any]) -> list[str]:
    """标签是检索键：全小写、去空白、去重，限制长度与数量。"""
    cleaned: list[str] = []
    for raw in tags:
        value = " ".join(str(raw or "").strip().lower().split())
        if not value:
            continue
        value = value[:MAX_TAG_LENGTH]
        if value not in cleaned:
            cleaned.append(value)
        if len(cleaned) >= MAX_TAGS:
            break
    return cleaned


def clamp_rating(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, number))


def asset_to_dict(row: CoreFileAsset) -> dict[str, Any]:
    return {
        "asset_id": row.asset_id,
        "identity_key": row.identity_key,
        "identity_kind": row.identity_kind,
        "path": row.path,
        "name": row.name,
        "display_name": row.display_name or row.name,
        "extension": row.extension,
        "size": int(row.size or 0),
        "mtime_ns": int(row.mtime_ns or 0),
        "is_dir": bool(row.is_dir),
        "favorite": bool(row.favorite),
        "rating": int(row.rating or 0),
        "tags": list(row.tags_json or []),
        "note": row.note or "",
        "missing": bool(row.missing),
        "missing_since": row.missing_since.isoformat(timespec="seconds") if row.missing_since else "",
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
        "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else "",
        "last_seen_at": row.last_seen_at.isoformat(timespec="seconds") if row.last_seen_at else "",
    }


class FileAssetStore:
    """SQLite 资产账本，与项目资料库(artifacts)分表、互不干扰。"""

    def __init__(self, session_factory: Any, write_coordinator: SQLiteWriteCoordinator | None = None) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator or SQLiteWriteCoordinator(session_factory)

    # -- read ----------------------------------------------------------
    async def list_all(self, *, limit: int = 20000) -> list[CoreFileAsset]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreFileAsset)
                    .order_by(CoreFileAsset.updated_at.desc())
                    .limit(max(1, int(limit)))
                )
            ).scalars().all()
            return list(rows)

    async def get_by_path(self, path: str) -> CoreFileAsset | None:
        key = path_key(path)
        async with self.session_factory() as db:
            return (
                await db.execute(select(CoreFileAsset).where(CoreFileAsset.path_key == key))
            ).scalar_one_or_none()

    async def get_by_identity(self, identity_key: str) -> CoreFileAsset | None:
        async with self.session_factory() as db:
            return (
                await db.execute(
                    select(CoreFileAsset).where(CoreFileAsset.identity_key == identity_key)
                )
            ).scalar_one_or_none()

    async def get(self, asset_id: str) -> CoreFileAsset | None:
        async with self.session_factory() as db:
            return await db.get(CoreFileAsset, asset_id)

    async def count(self) -> int:
        async with self.session_factory() as db:
            return int(
                (await db.execute(select(func.count()).select_from(CoreFileAsset))).scalar_one()
            )

    async def by_path_keys(self, keys: Sequence[str]) -> dict[str, CoreFileAsset]:
        """一次取出当前页涉及的资产，避免每个结果单独查库。"""
        cleaned = [key for key in keys if key]
        if not cleaned:
            return {}
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreFileAsset).where(CoreFileAsset.path_key.in_(cleaned))
                )
            ).scalars().all()
            return {row.path_key: row for row in rows}

    async def assets_by_ids(self, asset_ids: Sequence[str]) -> list[CoreFileAsset]:
        if not asset_ids:
            return []
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreFileAsset).where(CoreFileAsset.asset_id.in_(list(asset_ids)))
                )
            ).scalars().all()
            return list(rows)

    # -- write ---------------------------------------------------------
    async def touch_path(self, path: str, *, create: bool = True) -> dict[str, Any] | None:
        """按当前路径确认/建立资产记录；移动后同一身份自动更新路径。"""
        try:
            identity = identity_for(normalize_path(path))
        except OSError:
            row = await self.get_by_path(path)
            if row is None:
                return None
            if create:
                await self.mark_missing([row.asset_id], missing=True)
            return asset_to_dict(row)
        row = await self.get_by_identity(identity.identity_key)
        if row is None and not create:
            return None

        async def write(db: Any) -> CoreFileAsset:
            existing = row
            if existing is None:
                existing = (
                    await db.execute(
                        select(CoreFileAsset).where(CoreFileAsset.identity_key == identity.identity_key)
                    )
                ).scalar_one_or_none()
            if existing is None:
                existing = CoreFileAsset(
                    asset_id=f"file-{uuid.uuid4().hex[:16]}",
                    identity_key=identity.identity_key,
                    identity_kind=identity.identity_kind,
                    volume_serial=identity.volume_serial,
                    file_id=identity.file_id,
                    path=identity.path,
                    path_key=identity.path_key,
                    name=identity.name,
                    extension=identity.extension,
                    size=identity.size,
                    mtime_ns=identity.mtime_ns,
                    is_dir=identity.is_dir,
                    tags_json=[],
                    display_name="",
                    favorite=False,
                    rating=0,
                    note="",
                    missing=False,
                    missing_since=None,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    last_seen_at=datetime.now(),
                )
                db.add(existing)
            else:
                if existing.path != identity.path or existing.missing:
                    existing.path = identity.path
                    existing.path_key = identity.path_key
                    existing.missing = False
                    existing.missing_since = None
                existing.name = identity.name
                existing.extension = identity.extension
                existing.size = identity.size
                existing.mtime_ns = identity.mtime_ns
                existing.is_dir = identity.is_dir
                existing.last_seen_at = datetime.now()
                existing.updated_at = datetime.now()
            await db.flush()
            # 提交后 ORM 属性会过期；在会话仍然打开时把纯数据取出来。
            return asset_to_dict(existing)

        try:
            saved = await self.write_coordinator.run(write)
        except IntegrityError:
            # 并发下两个请求同时首次登记：后到的一方改为读取已有行。
            row = await self.get_by_identity(identity.identity_key)
            if row is None:
                raise
            saved = asset_to_dict(row)
        return saved

    async def update_path(
        self,
        path: str,
        *,
        favorite: bool | None = None,
        rating: int | None = None,
        tags: list[str] | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        display_name: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        created = await self.touch_path(path, create=True)
        if created is None:
            raise FileNotFoundError(path)
        asset_id = str(created["asset_id"])

        async def write(db: Any) -> CoreFileAsset | None:
            row = await db.get(CoreFileAsset, asset_id)
            if row is None:
                return None
            if favorite is not None:
                row.favorite = bool(favorite)
            if rating is not None:
                row.rating = clamp_rating(rating)
            if tags is not None:
                row.tags_json = normalize_tags(tags)
            if add_tags:
                row.tags_json = normalize_tags([*(row.tags_json or []), *add_tags])
            if remove_tags:
                drop = set(normalize_tags(remove_tags))
                row.tags_json = [tag for tag in (row.tags_json or []) if tag not in drop]
            if display_name is not None:
                row.display_name = str(display_name).strip()[:512]
            if note is not None:
                row.note = str(note).strip()[:4096]
            row.updated_at = datetime.now()
            await db.flush()
            return asset_to_dict(row)

        return await self.write_coordinator.run(write)

    async def mark_missing(self, asset_ids: Sequence[str], *, missing: bool) -> int:
        ids = [str(item) for item in asset_ids if str(item).strip()]
        if not ids:
            return 0

        async def write(db: Any) -> int:
            changed = 0
            for asset_id in ids:
                row = await db.get(CoreFileAsset, asset_id)
                if row is None:
                    continue
                row.missing = bool(missing)
                row.missing_since = datetime.now() if missing else None
                row.updated_at = datetime.now()
                changed += 1
            return changed

        return int(await self.write_coordinator.run(write))

    async def forget(self, asset_ids: Sequence[str]) -> int:
        """只删资产记录，不碰磁盘文件。"""
        ids = [str(item) for item in asset_ids if str(item).strip()]
        if not ids:
            return 0

        async def write(db: Any) -> int:
            result = await db.execute(delete(CoreFileAsset).where(CoreFileAsset.asset_id.in_(ids)))
            await db.execute(
                delete(CoreFileCollectionItem).where(CoreFileCollectionItem.asset_id.in_(ids))
            )
            return int(result.rowcount or 0)

        return int(await self.write_coordinator.run(write))

    async def relink(self, asset_id: str, new_path: str) -> dict[str, Any] | None:
        try:
            identity = await asyncio.to_thread(identity_for, normalize_path(new_path))
        except OSError:
            return None
        async with self.session_factory() as db:
            row = await db.get(CoreFileAsset, asset_id)
            if row is None:
                return None
            other = (
                await db.execute(
                    select(CoreFileAsset).where(CoreFileAsset.identity_key == identity.identity_key)
                )
            ).scalar_one_or_none()
            if other is not None and other.asset_id != asset_id:
                # 同一个文件已经有另一条记录：保留更早的用户状态，把两条并成一条。
                row.favorite = bool(row.favorite or other.favorite)
                row.rating = max(int(row.rating or 0), int(other.rating or 0))
                row.tags_json = normalize_tags([*(row.tags_json or []), *(other.tags_json or [])])
                if not row.note:
                    row.note = other.note
                if not row.display_name:
                    row.display_name = other.display_name
                await db.delete(other)
            row.identity_key = identity.identity_key
            row.identity_kind = identity.identity_kind
            row.volume_serial = identity.volume_serial
            row.file_id = identity.file_id
            row.path = identity.path
            row.path_key = identity.path_key
            row.name = identity.name
            row.extension = identity.extension
            row.size = identity.size
            row.mtime_ns = identity.mtime_ns
            row.is_dir = identity.is_dir
            row.missing = False
            row.missing_since = None
            row.last_seen_at = datetime.now()
            row.updated_at = datetime.now()
            payload = asset_to_dict(row)
            await db.commit()
            return payload

    # -- collections ---------------------------------------------------
    async def list_collections(self) -> list[dict[str, Any]]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(select(CoreFileCollection).order_by(CoreFileCollection.updated_at.desc()))
            ).scalars().all()
            counts = dict(
                (
                    await db.execute(
                        select(CoreFileCollectionItem.collection_id, func.count())
                        .group_by(CoreFileCollectionItem.collection_id)
                    )
                ).all()
            )
            return [
                {
                    "collection_id": row.collection_id,
                    "name": row.name,
                    "kind": row.kind,
                    "query": dict(row.query_json or {}),
                    "count": int(counts.get(row.collection_id, 0)),
                    "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else "",
                }
                for row in rows
            ]

    async def create_collection(
        self, name: str, *, kind: str = "manual", query: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        cleaned = str(name or "").strip()[:256]
        if not cleaned:
            raise ValueError("集合名称不能为空")

        async def write(db: Any) -> dict[str, Any]:
            row = CoreFileCollection(
                collection_id=f"col-{uuid.uuid4().hex[:16]}",
                name=cleaned,
                kind="smart" if kind == "smart" else "manual",
                query_json=dict(query or {}),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(row)
            await db.flush()
            return {
                "collection_id": row.collection_id,
                "name": row.name,
                "kind": row.kind,
                "query": dict(row.query_json or {}),
                "count": 0,
            }

        return await self.write_coordinator.run(write)

    async def update_collection(
        self,
        collection_id: str,
        *,
        name: str | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        async def write(db: Any) -> dict[str, Any] | None:
            row = await db.get(CoreFileCollection, collection_id)
            if row is None:
                return None
            if name is not None and str(name).strip():
                row.name = str(name).strip()[:256]
            if query is not None:
                row.query_json = dict(query)
                row.kind = "smart"
            row.updated_at = datetime.now()
            await db.flush()
            return {
                "collection_id": row.collection_id,
                "name": row.name,
                "kind": row.kind,
                "query": dict(row.query_json or {}),
            }

        return await self.write_coordinator.run(write)

    async def delete_collection(self, collection_id: str) -> bool:
        async def write(db: Any) -> bool:
            row = await db.get(CoreFileCollection, collection_id)
            if row is None:
                return False
            await db.execute(
                delete(CoreFileCollectionItem).where(CoreFileCollectionItem.collection_id == collection_id)
            )
            await db.delete(row)
            return True

        return bool(await self.write_coordinator.run(write))

    async def add_to_collection(self, collection_id: str, asset_ids: Sequence[str]) -> int:
        ids = [str(item) for item in asset_ids if str(item).strip()]
        if not ids:
            return 0

        async def write(db: Any) -> int:
            collection = await db.get(CoreFileCollection, collection_id)
            if collection is None:
                raise ValueError("集合不存在")
            existing = set(
                (
                    await db.execute(
                        select(CoreFileCollectionItem.asset_id).where(
                            CoreFileCollectionItem.collection_id == collection_id
                        )
                    )
                ).scalars().all()
            )
            added = 0
            for asset_id in ids:
                if asset_id in existing:
                    continue
                db.add(CoreFileCollectionItem(
                    collection_id=collection_id,
                    asset_id=asset_id,
                    added_at=datetime.now(),
                ))
                added += 1
            collection.updated_at = datetime.now()
            return added

        return int(await self.write_coordinator.run(write))

    async def remove_from_collection(self, collection_id: str, asset_ids: Sequence[str]) -> int:
        ids = [str(item) for item in asset_ids if str(item).strip()]
        if not ids:
            return 0

        async def write(db: Any) -> int:
            result = await db.execute(
                delete(CoreFileCollectionItem).where(
                    CoreFileCollectionItem.collection_id == collection_id,
                    CoreFileCollectionItem.asset_id.in_(ids),
                )
            )
            return int(result.rowcount or 0)

        return int(await self.write_coordinator.run(write))

    async def collection_assets(self, collection_id: str) -> list[CoreFileAsset]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreFileAsset)
                    .join(
                        CoreFileCollectionItem,
                        CoreFileCollectionItem.asset_id == CoreFileAsset.asset_id,
                    )
                    .where(CoreFileCollectionItem.collection_id == collection_id)
                    .order_by(CoreFileCollectionItem.added_at.desc())
                )
            ).scalars().all()
            return list(rows)

    async def asset_id_for_path(self, path: str) -> str:
        """给集合添加成员时用：先确认/建立资产，再返回 id。"""
        record = await self.touch_path(path, create=True)
        if record is None:
            raise FileNotFoundError(path)
        return str(record["asset_id"])
