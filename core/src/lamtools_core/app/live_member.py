from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PreparedLiveInput:
    visible_input: list[dict[str, Any]]
    runtime_input: list[dict[str, Any]]
    visible_text: str
    runtime_text: str
    work_root: str = ""
    runtime_extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnMaterialization:
    turn_id: str
    user_item_id: str
    turn_payload_extra: dict[str, Any] = field(default_factory=dict)
    user_payload_extra: dict[str, Any] = field(default_factory=dict)
    include_turn_status: bool = True
    runtime_extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueueMaterialization:
    payload_extra: dict[str, Any] = field(default_factory=dict)


class CoreLiveMemberHooks(Protocol):
    def attachment_repository(self, db: Any) -> Any: ...

    def command_member_roots(self) -> list[Any]: ...

    def command_skill_registry(self) -> Any: ...

    def command_action_handlers(self) -> dict[str, Any]: ...

    async def materialize_thread(
        self, *, db: AsyncSession, thread_id: str, params: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def augment_thread_read(
        self, *, db: AsyncSession, thread_id: str, result: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def prepare_turn_input(
        self, *, thread_id: str, params: dict[str, Any], input_items: list[dict[str, Any]]
    ) -> PreparedLiveInput: ...

    async def materialize_turn(
        self, *, db: AsyncSession, thread_id: str, turn_id: str, user_item_id: str,
        client_message_id: str, prepared: PreparedLiveInput, params: dict[str, Any]
    ) -> TurnMaterialization: ...

    async def start_runtime(self, *, runtime_start: dict[str, Any]) -> Any: ...

    async def prepare_queue_input(
        self, *, thread_id: str, params: dict[str, Any], input_items: list[dict[str, Any]]
    ) -> PreparedLiveInput: ...

    async def materialize_queue(
        self, *, db: AsyncSession, thread_id: str, queue_item_id: str,
        client_message_id: str, prepared: PreparedLiveInput, params: dict[str, Any]
    ) -> QueueMaterialization: ...

class DefaultCoreLiveMemberHooks:
    def attachment_repository(self, db):
        del db
        return None

    def command_member_roots(self):
        return []

    def command_skill_registry(self):
        from lamtools_core.skills import SkillRegistry

        return SkillRegistry()

    def command_action_handlers(self):
        return {}

    async def materialize_thread(self, *, db, thread_id, params):
        del db, thread_id, params
        return {}

    async def augment_thread_read(self, *, db, thread_id, result):
        del db, thread_id, result
        return {}

    async def prepare_turn_input(self, *, thread_id, params, input_items):
        del thread_id
        from .queue_state import input_item_attachment_ids, input_items_text

        text = input_items_text(input_items)
        attachment_ids = input_item_attachment_ids(input_items)
        runtime_extras: dict[str, Any] = {}
        if attachment_ids:
            # Attachment content-block building (capability-aware) happens later
            # in turn_start where the attachment_service is available. Here we
            # just forward the IDs so the main agent can see them and (if the
            # model cannot process them) delegate to a sub_agent.
            runtime_extras["attachment_ids"] = attachment_ids
        return PreparedLiveInput(
            visible_input=input_items,
            runtime_input=input_items,
            visible_text=text,
            runtime_text=text,
            work_root=str(params.get("work_root") or params.get("workRoot") or ""),
            runtime_extras=runtime_extras,
        )

    async def materialize_turn(
        self, *, db, thread_id, turn_id, user_item_id, client_message_id, prepared, params
    ):
        del db, thread_id, client_message_id, prepared, params
        return TurnMaterialization(turn_id=turn_id, user_item_id=user_item_id)

    async def start_runtime(self, *, runtime_start):
        operation = runtime_start.pop("_core_operation", None)
        if operation is None:
            raise RuntimeError("turn.start operation is unavailable")
        return await operation(runtime_start)

    async def prepare_queue_input(self, *, thread_id, params, input_items):
        return await self.prepare_turn_input(thread_id=thread_id, params=params, input_items=input_items)

    async def materialize_queue(
        self, *, db, thread_id, queue_item_id, client_message_id, prepared, params
    ):
        del db, thread_id, queue_item_id, client_message_id, prepared, params
        return QueueMaterialization()

__all__ = [
    "CoreLiveMemberHooks", "DefaultCoreLiveMemberHooks",
    "PreparedLiveInput", "QueueMaterialization", "TurnMaterialization",
]
