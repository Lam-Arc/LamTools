"""Super-agent 的持久化。

user:“保持旧会话、Checkpoint、配置及任务数据兼容。新增数据库字段必须使用安全、可重复的迁移”
+(只新增一张按 kind 分区的记录表：新能力全部落在里面，不动任何既有表结构；
去重与幂等直接用 (kind, id) 主键表达，不需要给每类对象单独改 schema)。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol, runtime_checkable

import asyncio


class RecordExists(RuntimeError):
    """create_only 冲突：同名记录已存在（用于事件与幂等键去重）。"""


class ConcurrentUpdate(RuntimeError):
    """revision CAS 冲突。"""


@runtime_checkable
class SuperagentStore(Protocol):
    async def get(self, kind: str, record_id: str) -> dict[str, Any] | None: ...

    async def put(
        self,
        kind: str,
        record_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: int | None = None,
        create_only: bool = False,
    ) -> dict[str, Any]: ...

    async def delete(self, kind: str, record_id: str) -> bool: ...

    async def list(self, kind: str) -> list[dict[str, Any]]: ...


class InMemorySuperagentStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        async with self._lock:
            item = self._items.get((kind, record_id))
            return deepcopy(item) if item is not None else None

    async def put(
        self,
        kind: str,
        record_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: int | None = None,
        create_only: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            key = (kind, record_id)
            current = self._items.get(key)
            if create_only and current is not None:
                raise RecordExists(f"{kind}:{record_id}")
            if expected_revision is not None:
                actual = int((current or {}).get("revision") or 0)
                if actual != expected_revision:
                    raise ConcurrentUpdate(
                        f"{kind}:{record_id} revision {actual} != {expected_revision}"
                    )
            revision = int((current or {}).get("revision") or 0) + 1
            stored = deepcopy(payload)
            stored["id"] = record_id
            stored["revision"] = revision
            self._items[key] = stored
            return deepcopy(stored)

    async def delete(self, kind: str, record_id: str) -> bool:
        async with self._lock:
            return self._items.pop((kind, record_id), None) is not None

    async def list(self, kind: str) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                deepcopy(value)
                for (item_kind, _), value in sorted(self._items.items())
                if item_kind == kind
            ]


class SqlAlchemySuperagentStore:
    """core_superagent_records 上的读写实现（写路径走统一写协调器）。"""

    def __init__(self, session_factory: Any, write_coordinator: Any, model: Any) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator
        self.model = model

    async def get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as db:
            row = await db.get(self.model, (kind, record_id))
        return self._payload(row) if row is not None else None

    async def put(
        self,
        kind: str,
        record_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: int | None = None,
        create_only: bool = False,
    ) -> dict[str, Any]:
        async def _write(db):
            from datetime import datetime, timezone

            row = await db.get(self.model, (kind, record_id))
            if create_only and row is not None:
                raise RecordExists(f"{kind}:{record_id}")
            if expected_revision is not None and int((row.revision if row else 0)) != expected_revision:
                raise ConcurrentUpdate(
                    f"{kind}:{record_id} revision mismatch (expected {expected_revision})"
                )
            when = datetime.now(timezone.utc)
            if row is None:
                row = self.model(kind=kind, id=record_id, payload_json={}, revision=0, created_at=when)
                db.add(row)
            stored = deepcopy(payload)
            stored.pop("revision", None)
            row.payload_json = stored
            row.revision = int(row.revision or 0) + 1
            row.updated_at = when
            await db.flush()
            return self._payload(row)

        return await self.write_coordinator.run(_write)

    async def delete(self, kind: str, record_id: str) -> bool:
        async def _write(db):
            row = await db.get(self.model, (kind, record_id))
            if row is None:
                return False
            await db.delete(row)
            return True

        return bool(await self.write_coordinator.run(_write))

    async def list(self, kind: str) -> list[dict[str, Any]]:
        from sqlalchemy import select

        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(self.model)
                    .where(self.model.kind == kind)
                    .order_by(self.model.id)
                )
            ).scalars().all()
        return [self._payload(row) for row in rows]

    def _payload(self, row: Any) -> dict[str, Any]:
        payload = dict(row.payload_json or {})
        payload["id"] = row.id
        payload["revision"] = int(row.revision or 0)
        return payload


__all__ = [
    "ConcurrentUpdate",
    "InMemorySuperagentStore",
    "RecordExists",
    "SqlAlchemySuperagentStore",
    "SuperagentStore",
]
