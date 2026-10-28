"""Host service that lets plugins drive a live Sunday session.

Plugins must not call the agent-operation ``turn.start`` for a session the
desktop is already rendering: that path runs the kernel but does not create
the live acceptance/user-message projection.  This service calls the same
handlers the desktop's live RPC uses, so the message appears in the session
and its events reach the live hub.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class LiveTurnService:
    def __init__(self, context_factory: Callable[[], Any]) -> None:
        self._context_factory = context_factory

    async def _execute(self, name: str, params: dict[str, Any]) -> tuple[Any, Any]:
        # user:“该修修，相关插件也要修”+(插件与桌面共用会话串行入口，不能绕过启动和恢复的所有权保护)。
        context = self._context_factory()
        outcome = await context.host.execute(name, request_id=None, params=params, context=context)
        return context, outcome

    @staticmethod
    def _result(outcome: Any) -> dict[str, Any]:
        response = getattr(outcome, "response", None)
        response = response if isinstance(response, dict) else {}
        error = response.get("error")
        if isinstance(error, dict):
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            return {
                "ok": False,
                "error": str(error.get("message") or "live operation failed"),
                "code": str(data.get("code") or ""),
                "paused_turn_id": str(data.get("paused_turn_id") or ""),
                "active_run_id": str(data.get("active_run_id") or ""),
                "data": data,
            }
        result = response.get("result")
        return {"ok": True, "result": result if isinstance(result, dict) else {}}

    @staticmethod
    def _turn_ids(result: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
        runtime_start = payload.get("runtime_start")
        runtime_start = runtime_start if isinstance(runtime_start, dict) else {}
        # user:“该修修，相关插件也要修”+(重复投递返回原回合身份，插件不能把已接收消息误判为无目标)。
        events = payload.get("events") or []
        receipt = next((item for item in events if isinstance(item, dict) and item.get("turn_id")), {})
        turn_id = str(
            runtime_start.get("turn_id")
            or result.get("turn_id")
            or payload.get("turn_id")
            or receipt.get("turn_id")
            or ""
        )
        run_id = str(
            runtime_start.get("run_id")
            or result.get("run_id")
            or payload.get("run_id")
            or ""
        )
        return turn_id, run_id

    async def steer_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        text: str,
        client_message_id: str,
    ) -> dict[str, Any]:
        """Submit guidance through the same operation the desktop uses."""
        _, outcome = await self._execute("turn.steer", {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "client_message_id": client_message_id,
            "input": [{"type": "text", "text": str(text or "")}],
        })
        return self._result(outcome)

    async def _wait_for_new_turn(self, thread_id: str, previous_turn_id: str) -> str:
        import asyncio

        for _ in range(50):
            state = await self.active_turn(thread_id=thread_id)
            active = str(state.get("active_turn_id") or "")
            if active and active != previous_turn_id:
                return active
            await asyncio.sleep(0.02)
        return ""

    async def deliver_message(
        self,
        *,
        thread_id: str,
        text: str,
        client_message_id: str,
        work_root: str = "",
    ) -> dict[str, Any]:
        """Deliver once, preserving the original receipt across routing changes."""
        from lamtools_core.async_tasks import finish_on_cancel

        context = self._context_factory()

        async def deliver_once():
            # user:“该修修，相关插件也要修”+(插件断线重投仍返回原接收记录，不能把同一消息再次当作运行中引导)。
            persistence = getattr(context, "persistence", None)
            factory = getattr(context, "session_factory", None)
            if persistence is not None and factory is not None:
                async with factory() as db:
                    receipt = await persistence.find_client_event(
                        db, thread_id=thread_id, client_message_id=client_message_id,
                        methods={"turn/accepted", "turn/started", "turn/steered", "queue/itemAccepted"},
                    )
                    if receipt is not None:
                        turn_id = str(receipt.turn_id or "")
                        mode = "steered" if receipt.method == "turn/steered" else "started"
                        if receipt.method == "queue/itemAccepted":
                            mode = "queued"
                            dispatched = await persistence.find_client_event(
                                db, thread_id=thread_id,
                                client_message_id=f"dispatch:{receipt.item_id}", methods={"turn/accepted"},
                            )
                            turn_id = str(dispatched.turn_id or "") if dispatched else ""
                        return {
                            "ok": True, "mode": mode, "turn_id": turn_id,
                            "run_id": str(receipt.payload.get("run_id") or ""),
                            "result": {"events": [receipt.to_dict()]},
                        }
            return await self._deliver_message(
                thread_id=thread_id, text=text, client_message_id=client_message_id, work_root=work_root,
            )

        async def serialized_delivery():
            actors = getattr(getattr(context, "host", None), "session_actors", None)
            if actors is None:
                return await deliver_once()
            # Separate from the desktop's thread actor: start/steer/resume
            # acquire that actor themselves. Serialize plugin routing so two
            # copies cannot choose different operations for one message.
            return await actors.run(f"plugin-delivery:{thread_id}", deliver_once)

        return await finish_on_cancel(serialized_delivery(), name=f"plugin-delivery:{thread_id}")

    async def _deliver_message(
        self,
        *,
        thread_id: str,
        text: str,
        client_message_id: str,
        work_root: str = "",
    ) -> dict[str, Any]:
        """Deliver one message to a live session without the caller guessing state.

        The live session owns the idle/running/paused decision:
        - idle: start a normal turn;
        - running: submit the same ``turn.steer`` operation the desktop uses,
          which persists ``turn/steered`` and the user-guide projection;
        - paused: resume the paused turn (``start_turn`` already does this);
        - the turn ends between the busy check and steering: the host queues
          the text as the next user turn instead of dropping it.

        Callers get one stable result and never need to inspect the runtime
        registry, snapshots, or an ``active_run_id``.
        """
        import asyncio

        last: dict[str, Any] = {}
        for _ in range(4):
            # Read the rendered active turn first.  Calling turn.start while a
            # turn is running can block behind the session actor until that
            # turn ends, which turns a mid-turn message into a queued next turn.
            state = await self.active_turn(thread_id=thread_id)
            active = str(state.get("active_turn_id") or "")
            if active:
                steered = await self.steer_turn(
                    thread_id=thread_id,
                    turn_id=active,
                    text=text,
                    client_message_id=client_message_id,
                )
                if steered.get("ok"):
                    payload = steered.get("result") if isinstance(steered.get("result"), dict) else {}
                    if payload.get("applied"):
                        return {
                            "ok": True,
                            "mode": "steered",
                            "turn_id": active,
                            "run_id": "",
                            "result": payload,
                        }
                    if payload.get("queued"):
                        new_turn = await self._wait_for_new_turn(thread_id, active)
                        return {
                            "ok": True,
                            "mode": "queued",
                            "turn_id": new_turn,
                            "run_id": "",
                            "result": payload,
                        }
                last = steered
                # The turn ended or the id moved between the snapshot read and
                # the steer; fall through to a normal start.

            started = await self.start_turn(
                thread_id=thread_id,
                text=text,
                client_message_id=client_message_id,
                work_root=work_root,
            )
            if started.get("ok"):
                started["mode"] = "started"
                return started
            if started.get("code") == "SESSION_PAUSED":
                return started
            if started.get("code") != "SESSION_BUSY":
                return started

            data = started.get("data") if isinstance(started.get("data"), dict) else {}
            active = str(started.get("active_run_id") or data.get("active_run_id") or "")
            if not active:
                state = await self.active_turn(thread_id=thread_id)
                active = str(state.get("active_turn_id") or "")
            if not active:
                last = started
                await asyncio.sleep(0.02)
                continue

            steered = await self.steer_turn(
                thread_id=thread_id,
                turn_id=active,
                text=text,
                client_message_id=client_message_id,
            )
            if steered.get("ok"):
                payload = steered.get("result") if isinstance(steered.get("result"), dict) else {}
                if payload.get("applied"):
                    return {
                        "ok": True,
                        "mode": "steered",
                        "turn_id": active,
                        "run_id": "",
                        "result": payload,
                    }
                if payload.get("queued"):
                    new_turn = await self._wait_for_new_turn(thread_id, active)
                    return {
                        "ok": True,
                        "mode": "queued",
                        "turn_id": new_turn,
                        "run_id": "",
                        "result": payload,
                    }
            last = steered if not steered.get("ok") else started
            await asyncio.sleep(0.02)
        return last or {"ok": False, "error": "目标会话没有接受消息"}

    async def active_turn(self, *, thread_id: str) -> dict[str, Any]:
        # user:“现在怎么无论回合是否开启，都作为引导信息发出去了？”+(以桌面
        # 实际渲染的快照为准，避免登记表残留把空闲消息误判成引导)。
        """Return the turn the Sunday UI would consider active right now.

        The runtime registry can lag behind the durable snapshot: a turn is
        accepted in the snapshot before its task is registered, and a finished
        task can leave an entry behind for a moment.  QQ routing must follow
        the same state the desktop renders, otherwise an idle message becomes
        guidance or a running message is rejected as busy.
        """
        from .queue_state import effective_thread_status, latest_active_turn_id

        context = self._context_factory()
        session_factory = getattr(context, "session_factory", None)
        persistence = getattr(context, "persistence", None)
        if session_factory is None or persistence is None:
            return {"status": "", "active_turn_id": ""}
        async with session_factory() as db:
            snapshot = await persistence.load_metadata(db, thread_id)
        return {
            "status": effective_thread_status(snapshot),
            "active_turn_id": str(latest_active_turn_id(snapshot) or ""),
        }

    async def start_turn(
        self,
        *,
        thread_id: str,
        text: str,
        client_message_id: str,
        work_root: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "thread_id": thread_id,
            "client_message_id": client_message_id,
            "input": [{"type": "text", "text": str(text or "")}],
        }
        if work_root:
            params["work_root"] = work_root
        _, outcome = await self._execute("turn.start", params)
        result = self._result(outcome)
        if not result.get("ok"):
            # A paused turn owns the session.  Sending a message to it means
            # "continue this turn with my message", not "start a second turn".
            if result.get("code") == "SESSION_PAUSED" and result.get("paused_turn_id"):
                return await self.resume_turn(
                    thread_id=thread_id,
                    turn_id=str(result["paused_turn_id"]),
                    text=text,
                    client_message_id=client_message_id,
                )
            return result
        payload = result.get("result") or {}
        turn_id, run_id = self._turn_ids(result, payload)
        return {
            "ok": True,
            "turn_id": turn_id,
            "run_id": run_id,
            "result": payload,
        }

    async def resume_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        text: str,
        client_message_id: str,
    ) -> dict[str, Any]:
        requested_turn_id = str(turn_id or "")
        _, outcome = await self._execute("turn.resume", {
            "thread_id": thread_id,
            "turn_id": requested_turn_id,
            "client_message_id": client_message_id,
            "input": [{"type": "text", "text": str(text or "")}],
        })
        result = self._result(outcome)
        if not result.get("ok"):
            return result
        payload = result.get("result") or {}
        resolved_turn_id, run_id = self._turn_ids(result, payload)
        return {
            "ok": True,
            "turn_id": resolved_turn_id or requested_turn_id,
            "run_id": run_id,
            "result": payload,
        }

    async def respond_approval(
        self,
        *,
        thread_id: str,
        request_id: str,
        decision: str,
        guidance: str = "",
    ) -> dict[str, Any]:
        context, outcome = await self._execute("approval.respond", {
            "thread_id": thread_id,
            "request_id": request_id,
            "decision": decision,
            "guidance": guidance,
        })
        for event in list(getattr(outcome, "notify_events", []) or []):
            await context.hub.publish(event)
        for event in list(getattr(outcome, "publish_events", []) or []):
            await context.hub.publish(event)
        result = self._result(outcome)
        if not result.get("ok"):
            return result
        payload = result.get("result") or {}
        return {"ok": True, "result": payload}


__all__ = ["LiveTurnService"]
