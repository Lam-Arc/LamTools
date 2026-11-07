"""外部副作用 outbox：至少一次投递 + 幂等键 + 先查后建。

user:“外部 PR、评论等副作用不得因超时重试而重复创建”
+(实现方式不是幻想 exactly-once，而是：数据库按幂等键原子去重、
失败后先向远端查询是否已存在、再决定是否真的创建)。
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from .models import Effect
from .store import RecordExists, SuperagentStore

_KIND = "effect"


@runtime_checkable
class EffectAdapter(Protocol):
    """远端适配器：lookup 必须幂等可查，perform 才是真正的写。"""

    async def lookup(self, effect: Effect) -> str | None: ...

    async def perform(self, effect: Effect) -> str: ...


class EffectOutbox:
    def __init__(self, store: SuperagentStore) -> None:
        self.store = store

    async def ensure(
        self,
        *,
        ticket_id: str,
        kind: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> Effect:
        """按幂等键创建（已存在则返回既有记录）。"""
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        record_id = f"{kind}:{idempotency_key}"
        existing = await self.store.get(_KIND, record_id)
        if existing is not None:
            return Effect.from_dict(existing)
        effect = Effect(
            effect_id=f"eff_{uuid.uuid4().hex}",
            ticket_id=ticket_id,
            kind=kind,
            idempotency_key=idempotency_key,
            payload=dict(payload or {}),
        )
        try:
            stored = await self.store.put(
                _KIND, record_id, effect.to_dict(), create_only=True
            )
        except RecordExists:
            stored = await self.store.get(_KIND, record_id) or {}
        return Effect.from_dict(stored)

    async def deliver(
        self,
        effect: Effect,
        adapter: EffectAdapter,
        *,
        max_attempts: int = 3,
    ) -> Effect:
        record_id = f"{effect.kind}:{effect.idempotency_key}"
        current = await self.store.get(_KIND, record_id)
        if current is None:
            raise LookupError(f"effect not found: {record_id}")
        working = Effect.from_dict(current)
        if working.status == "done":
            return working

        attempts = working.attempts
        last_error = ""
        while attempts < max_attempts:
            attempts += 1
            # 关键顺序：先查远端有没有，再决定要不要创建。
            # 客户端超时但服务端已成功的场景靠这一步收敛。
            remote_ref = await adapter.lookup(working)
            if remote_ref:
                return await self._finish(record_id, working, remote_ref, attempts)
            try:
                remote_ref = await adapter.perform(working)
            except Exception as exc:  # noqa: BLE001 — 记录后重试，次数固定
                last_error = f"{type(exc).__name__}: {exc}"
                working = await self._mark(record_id, working, attempts, last_error)
                continue
            return await self._finish(record_id, working, remote_ref, attempts)
        return await self._mark(record_id, working, attempts, last_error or "attempts-exhausted", failed=True)

    async def _finish(
        self, record_id: str, effect: Effect, remote_ref: str, attempts: int
    ) -> Effect:
        from dataclasses import replace

        updated = replace(
            effect,
            status="done",
            attempts=attempts,
            remote_ref=remote_ref,
            last_error="",
        )
        stored = await self.store.put(_KIND, record_id, updated.to_dict())
        return Effect.from_dict(stored)

    async def _mark(
        self,
        record_id: str,
        effect: Effect,
        attempts: int,
        error: str,
        *,
        failed: bool = False,
    ) -> Effect:
        from dataclasses import replace

        updated = replace(
            effect,
            status="failed" if failed else "pending",
            attempts=attempts,
            last_error=error,
        )
        stored = await self.store.put(_KIND, record_id, updated.to_dict())
        return Effect.from_dict(stored)

    async def list_pending(self) -> list[Effect]:
        items = await self.store.list(_KIND)
        return [
            Effect.from_dict(item)
            for item in items
            if str(item.get("status") or "pending") != "done"
        ]


__all__ = ["EffectAdapter", "EffectOutbox"]
