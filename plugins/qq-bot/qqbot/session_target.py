"""Send QQ messages into a selected Sunday session.

Private and group messages use the same path: an idle target receives a normal
user turn, a running target receives immediate guidance.  Queued messages are
deliberately not used here; they wait for the next turn, while QQ messages are
expected to take effect as soon as they arrive.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

ApprovalWaiter = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
ReplyCallback = Callable[[str], Awaitable[None]]


class SessionTargetClient:
    def __init__(self, context: Any, *, timeout_ms: int = 30 * 60 * 1000) -> None:
        self.context = context
        self.timeout_ms = max(10_000, int(timeout_ms or 30 * 60 * 1000))

    def _service(self, name: str) -> Any | None:
        getter = getattr(self.context, "service", None)
        return getter(name) if callable(getter) else None

    def _live_service(self) -> Any | None:
        return self._service("live_turn_service")

    def _event_bus(self) -> Any | None:
        return getattr(self.context, "event_bus", None)

    def _executor(self) -> Any | None:
        builder = getattr(self.context, "operation_executor", None)
        if callable(builder):
            try:
                return builder()
            except Exception:
                return None
        catalog = getattr(self.context, "resolved_operation_catalog", None)
        if not callable(catalog):
            return None
        catalog = catalog()
        if catalog is None:
            return None

        async def execute(name: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> Any:
            return await catalog.execute(name, payload, metadata=metadata or {})

        return execute

    def _registry(self) -> Any | None:
        registry = getattr(self.context, "runtime_task_registry", None)
        if registry is not None:
            return registry
        return self._service("runtime_task_registry")

    def _active_run_id(self, session_id: str) -> str:
        registry = self._registry()
        getter = getattr(registry, "active_run_id", None)
        if not callable(getter):
            return ""
        try:
            return str(getter(session_id) or "")
        except Exception:
            return ""

    async def _active_turn(self, session_id: str) -> str:
        # user:“现在怎么无论回合是否开启，都作为引导信息发出去了？”+(先以桌面
        # 快照为准；登记表可能残留已结束的执行，不能拿它判断空闲/运行)。
        """The turn the desktop actually shows as running.

        Prefer the durable live snapshot over the in-memory registry: the
        registry can still hold a finished run (so an idle QQ message becomes
        guidance) or can lag a freshly accepted turn (so turn.start reports
        SESSION_BUSY).  Fall back to the registry only for hosts/tests that do
        not expose the live service.
        """
        live = self._live_service()
        getter = getattr(live, "active_turn", None) if live is not None else None
        if callable(getter):
            try:
                state = await getter(thread_id=session_id)
            except Exception:
                state = None
            if isinstance(state, dict):
                return str(state.get("active_turn_id") or "")
        # Older hosts do not expose the snapshot probe.  Their session record
        # still carries the rendered status, which is enough to ignore a stale
        # registry entry when the session is visibly idle.
        status = await self._session_status(session_id)
        if status and status != "running":
            return ""
        return self._active_run_id(session_id)

    @staticmethod
    def _message_key(message: Any) -> str:
        content = str(getattr(message, "content", "") or "")
        return f"{getattr(message, 'id', '')}:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"

    async def _message_keys(self, session_id: str) -> set[str]:
        store = self._service("session_store")
        if store is None or not callable(getattr(store, "list_messages", None)):
            return set()
        try:
            messages = await store.list_messages(session_id)
        except Exception:
            return set()
        return {self._message_key(item) for item in messages}

    async def _session_status(self, session_id: str) -> str:
        store = self._service("session_store")
        getter = getattr(store, "get", None) if store is not None else None
        if not callable(getter):
            return ""
        try:
            record = await getter(session_id)
        except Exception:
            return ""
        return str(getattr(record, "status", "") or "")

    @staticmethod
    def _input(text: str) -> list[dict[str, Any]]:
        return [{"type": "text", "text": text}]

    async def _send_operation(
        self,
        *,
        session_id: str,
        text: str,
        client_message_id: str,
        active_run_id: str,
    ) -> tuple[str, str, dict[str, Any]]:
        # user:“该修修，相关插件也要修”+(兼容投递也先走宿主的持久化引导，不能只注入内存后宣称接收成功)。
        live = self._live_service()
        steer = getattr(live, "steer_turn", None) if live is not None else None
        if active_run_id and callable(steer):
            try:
                result = await steer(
                    thread_id=session_id, turn_id=active_run_id,
                    text=text, client_message_id=client_message_id,
                )
            except Exception as exc:
                return "error", f"引导消息发送失败：{exc}", {}
            payload = result.get("result") if isinstance(result.get("result"), dict) else {}
            if not result.get("ok"):
                return "error", str(result.get("error") or "引导消息未被目标会话接受"), result
            if payload.get("applied"):
                return "steered", "", {**result, "turn_id": active_run_id}
            if payload.get("queued"):
                return "queued", "", result
            return "error", "目标回合已结束，请重试消息", result
        if active_run_id:
            # Immediate steering, not a queued message.  The runtime registry is
            # the same in-memory mailbox the host's live steering path uses.
            registry = self._registry()
            inject = getattr(registry, "inject_guidance", None)
            if callable(inject):
                try:
                    accepted = bool(
                        inject(
                            session_id,
                            text,
                            run_id=active_run_id,
                            guidance_id=client_message_id,
                            metadata={"source": "qqbot"},
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    return "error", f"引导消息发送失败：{exc}", {}
                if accepted:
                    return "steered", "", {"active_run_id": active_run_id}
                # The run ended between the check and the injection: fall back
                # to a normal user turn instead of dropping the message.
                active_run_id = ""
            else:
                return "error", "宿主没有提供运行中引导接口", {}
        if live is not None:
            try:
                result = await live.start_turn(
                    thread_id=session_id,
                    text=text,
                    client_message_id=client_message_id,
                )
            except Exception as exc:  # noqa: BLE001
                return "error", f"消息发送失败：{exc}", {}
            if result.get("ok"):
                return "started", "", result
            error = str(result.get("error") or "")
            if "active turn" in error.lower():
                # user:“⚠️ 目标会话处理失败：session has an active turn”+(turn.start
                # 已经知道确切的活动 run，就直接用它返回的 active_run_id 注入，
                # 不要只重读可能还没登记的登记表)。
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                active = (
                    str(result.get("active_run_id") or "")
                    or str(data.get("active_run_id") or "")
                    or self._active_run_id(session_id)
                )
                if active:
                    return await self._send_operation(
                        session_id=session_id,
                        text=text,
                        client_message_id=client_message_id,
                        active_run_id=active,
                    )
            return "error", error or "消息未被目标会话接受", result
        executor = self._executor()
        if executor is None:
            return "error", "宿主没有提供操作目录，无法发送到目标会话", {}
        payload = {
            "thread_id": session_id,
            "client_message_id": client_message_id,
            # The live turn.start accepts input items; the operation catalog's
            # turn.start accepts message.  Send both so either host path works.
            "message": text,
            "input": self._input(text),
        }
        try:
            result = await executor("turn.start", payload)
        except Exception as exc:  # noqa: BLE001
            return "error", f"消息发送失败：{exc}", {}
        status = str(getattr(result, "status", "ok") or "ok")
        result_payload = dict(getattr(result, "payload", {}) or {})
        if status == "ok":
            return "started", "", result_payload
        error = str(result_payload.get("error") or "")
        # A race between our active-run check and turn.start: the session became
        # busy. Re-read the active run and send guidance instead of dropping it.
        if "active turn" in error.lower():
            active = self._active_run_id(session_id)
            if active:
                return await self._send_operation(
                    session_id=session_id,
                    text=text,
                    client_message_id=client_message_id,
                    active_run_id=active,
                )
        return "error", error or "消息未被目标会话接受", result_payload

    @staticmethod
    def _approval_request(payload: dict[str, Any]) -> dict[str, Any] | None:
        # Events can contain both the request and its response after a
        # continuation.  Track them in order so a resolved request is not
        # answered a second time.
        pending: dict[str, dict[str, Any]] = {}
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            name = str(event.get("name") or event.get("kind") or "")
            data = event.get("payload")
            if not isinstance(data, dict):
                continue
            request_id = str(data.get("request_id") or data.get("tool_call_id") or "")
            if name in {"runtime.approval_request", "approval_request"}:
                if request_id:
                    pending[request_id] = data
            elif name in {"runtime.approval_response", "approval_response"}:
                if request_id:
                    pending.pop(request_id, None)
        return list(pending.values())[-1] if pending else None

    async def _respond_approval(
        self,
        *,
        session_id: str,
        request: dict[str, Any],
        answer: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        decision = str(answer.get("decision") or "").strip()
        guidance = str(answer.get("guidance") or "")
        if decision not in {"approve", "deny", "guide", "skip", "trust"}:
            return {}, f"无效的审批决定：{decision or '空'}"
        request_id = str(
            request.get("request_id") or request.get("tool_call_id") or ""
        ).strip()
        if not request_id:
            return {}, "审批请求缺少 request_id"
        live = self._live_service()
        if live is not None:
            try:
                result = await live.respond_approval(
                    thread_id=session_id,
                    request_id=request_id,
                    decision=decision,
                    guidance=guidance,
                )
            except Exception as exc:  # noqa: BLE001
                return {}, f"审批提交失败：{exc}"
            if result.get("ok"):
                payload = result.get("result")
                return payload if isinstance(payload, dict) else {}, ""
            return {}, str(result.get("error") or "审批未被接受")
        executor = self._executor()
        if executor is None:
            return {}, "宿主没有提供操作目录，无法提交审批"
        try:
            result = await executor(
                "approval.respond",
                {
                    "thread_id": session_id,
                    "request_id": request_id,
                    "decision": decision,
                    "guidance": guidance,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return {}, f"审批提交失败：{exc}"
        status = str(getattr(result, "status", "ok") or "ok")
        payload = dict(getattr(result, "payload", {}) or {})
        if status != "ok":
            return payload, str(payload.get("error") or "审批未被接受")
        return payload, ""

    async def _wait_live_reply(
        self,
        *,
        session_id: str,
        queue: Any,
        started: dict[str, Any],
        on_wait: ApprovalWaiter | None,
        on_reply: ReplyCallback | None,
        guidance_id: str = "",
    ) -> dict[str, Any]:
        expected_turn = str(started.get("turn_id") or "")
        expected_run = str(started.get("active_run_id") or started.get("run_id") or "")
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        latest = ""
        pending_guidance = bool(guidance_id)
        sent_items: set[str] = set()
        sent_texts: set[str] = set()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"ok": False, "error": "等待目标会话回复超时", "mode": "live"}
            try:
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "等待目标会话回复超时", "mode": "live"}
            if event is None:
                continue
            if str(getattr(event, "reason", "") or "") == "subscriber_overflow":
                return {"ok": False, "error": "目标会话事件流中断，请重试", "mode": "live"}
            data = getattr(event, "payload", None)
            if not isinstance(data, dict):
                continue
            kind = str(data.get("kind") or "")
            body = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            event_turn = str(data.get("turn_id") or getattr(event, "turn_id", "") or "")
            event_run = str(data.get("run_id") or "")
            if expected_turn and event_turn and event_turn != expected_turn:
                continue
            if not expected_turn and expected_run and event_run and event_run != expected_run:
                continue
            if kind == "approval_request":
                if on_wait is None:
                    return {
                        "ok": False,
                        "error": "目标会话需要审批或提问，但 QQ 通道没有交互处理器",
                        "mode": "live",
                    }
                answer = await on_wait(body)
                if not isinstance(answer, dict) or not answer:
                    return {"ok": False, "error": "审批或提问等待超时/已取消", "mode": "live"}
                _, error = await self._respond_approval(
                    session_id=session_id,
                    request=body,
                    answer=answer,
                )
                if error:
                    return {"ok": False, "error": error, "mode": "live"}
                continue
            if kind == "message":
                if str(body.get("type") or "") == "userMessage" and ":user:guide:" in str(
                    data.get("item_id") or body.get("item_id") or ""
                ):
                    pending_guidance = False
                    continue
                if str(body.get("type") or "") != "agentMessage":
                    continue
                content = str(body.get("content") or "").strip()
                if not content:
                    continue
                item_id = str(data.get("item_id") or body.get("item_id") or "")
                status = str(data.get("status") or "")
                if status == "completed" and item_id not in sent_items:
                    sent_items.add(item_id)
                    sent_texts.add(content)
                    if on_reply is not None:
                        await on_reply(content)
                    else:
                        latest = content
                    # A final response can still be followed by another model
                    # call if guidance queued while the first call was blocked.
                    # Only treat it as final once this QQ guidance was consumed.
                    if bool(body.get("final_response")) and not pending_guidance:
                        return {"ok": True, "reply": content, "mode": "live"}
                continue
            if kind != "status":
                continue
            status = str(body.get("status") or "")
            message = str(body.get("message") or latest or "").strip()
            if status == "completed":
                if message and message not in sent_texts:
                    return {"ok": True, "reply": message, "mode": "live"}
                return {"ok": True, "reply": "", "mode": "live"}
            if status in {"failed", "cancelled", "interrupted"}:
                return {
                    "ok": False,
                    "error": message or f"目标会话状态：{status}",
                    "mode": "live",
                }
        return {"ok": False, "error": "等待目标会话回复超时", "mode": "live"}

    async def send(
        self,
        *,
        session_id: str,
        text: str,
        client_message_id: str,
        on_wait: ApprovalWaiter | None = None,
        on_reply: ReplyCallback | None = None,
        forward_replies: bool = False,
    ) -> dict[str, Any]:
        session_id = str(session_id or "").strip()
        text = str(text or "").strip()
        if not session_id:
            return {"ok": False, "error": "未配置目标会话"}
        if not text:
            return {"ok": False, "error": "消息为空"}
        live = self._live_service()
        bus = self._event_bus() if live is not None else None
        queue = None
        if bus is not None and callable(getattr(bus, "subscribe", None)):
            try:
                queue = bus.subscribe(session_id)
            except Exception:
                queue = None
        try:
            before = await self._message_keys(session_id)
            message_id = client_message_id or f"qqbot:{time.time_ns()}"
            delivered_by_host = False
            live = self._live_service()
            deliver = getattr(live, "deliver_message", None) if live is not None else None
            if callable(deliver):
                delivered_by_host = True
                # One host call owns the idle/running/paused decision and the
                # durable turn/steered write. The plugin must not infer state.
                delivery = await deliver(
                    thread_id=session_id,
                    text=text,
                    client_message_id=message_id,
                )
                if not delivery.get("ok"):
                    return {"ok": False, "error": str(delivery.get("error") or "消息未被目标会话接受")}
                mode = str(delivery.get("mode") or "started")
                payload = delivery
                if mode == "queued" and not delivery.get("turn_id"):
                    # The host filed it as the next user turn but has not
                    # dispatched it yet; the target watcher will deliver the
                    # reply when that turn runs.
                    return {"ok": True, "reply": "", "mode": mode}
            else:
                active = await self._active_turn(session_id)
                mode, error, payload = await self._send_operation(
                    session_id=session_id,
                    text=text,
                    client_message_id=message_id,
                    active_run_id=active,
                )
                if mode == "error" and ("run_not_active" in error.lower() or "not active" in error.lower()):
                    # The running turn ended between the active check and the steer.
                    # Fall through to a normal user message instead of dropping it.
                    mode, error, payload = await self._send_operation(
                        session_id=session_id,
                        text=text,
                        client_message_id=message_id,
                        active_run_id="",
                    )
                if mode == "error":
                    return {"ok": False, "error": error}

            if queue is not None and mode in {"started", "steered", "queued"}:
                result = await self._wait_live_reply(
                    session_id=session_id,
                    queue=queue,
                    started=payload,
                    on_wait=on_wait,
                    on_reply=None if forward_replies else on_reply,
                    guidance_id=message_id,
                )
                if forward_replies and result.get("ok"):
                    # The persistent target watcher already delivered every
                    # assistant segment to QQ; do not send the final twice.
                    result["reply"] = ""
                return result

            # Fallback for hosts without the live service: the agent operation
            # path returns approval events in its payload.
            for _ in range(9):
                request = self._approval_request(payload)
                if request is None:
                    if str(payload.get("decision") or "") == "wait":
                        return {
                            "ok": False,
                            "error": "目标会话在等待审批或提问，但宿主没有返回请求内容",
                            "mode": mode,
                        }
                    break
                if on_wait is None:
                    return {
                        "ok": False,
                        "error": "目标会话需要审批或提问，但 QQ 通道没有交互处理器",
                        "mode": mode,
                    }
                answer = await on_wait(request)
                if not isinstance(answer, dict) or not answer:
                    return {"ok": False, "error": "审批或提问等待超时/已取消", "mode": mode}
                payload, error = await self._respond_approval(
                    session_id=session_id,
                    request=request,
                    answer=answer,
                )
                if error:
                    return {"ok": False, "error": error, "mode": mode}
            if self._approval_request(payload) is not None:
                return {"ok": False, "error": "审批或提问次数过多，已停止等待", "mode": mode}

            deadline = time.monotonic() + self.timeout_ms / 1000.0
            latest_reply = ""
            while time.monotonic() < deadline:
                await asyncio.sleep(0.25)
                store = self._service("session_store")
                if store is None or not callable(getattr(store, "list_messages", None)):
                    return {"ok": False, "error": "宿主没有提供会话消息读取接口"}
                try:
                    messages = await store.list_messages(session_id)
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": f"读取目标会话失败：{exc}"}
                for message in messages:
                    if self._message_key(message) in before:
                        continue
                    if str(getattr(message, "role", "")) != "assistant":
                        continue
                    content = str(getattr(message, "content", "") or "").strip()
                    if content:
                        latest_reply = content
                status = await self._session_status(session_id)
                # deliver_message already proved the host accepted the message;
                # a stale registry entry must not keep this waiter alive.
                active = "" if delivered_by_host else self._active_run_id(session_id)
                # A terminal status can be the previous turn's status for a moment;
                # only trust it once no run is active.  This also prevents returning
                # an intermediate assistant message while tools are still running.
                if status in {"completed", "failed", "cancelled"} and not active:
                    if latest_reply:
                        return {"ok": True, "reply": latest_reply, "mode": mode}
                    return {"ok": False, "error": f"目标会话当前状态：{status}", "mode": mode}
                if status in {"waiting", "paused"}:
                    return {"ok": False, "error": f"目标会话当前状态：{status}", "mode": mode}
                if not status and latest_reply and not active:
                    return {"ok": True, "reply": latest_reply, "mode": mode}
            return {"ok": False, "error": "等待目标会话回复超时", "mode": mode}
        finally:
            if queue is not None and bus is not None and callable(getattr(bus, "unsubscribe", None)):
                try:
                    bus.unsubscribe(session_id, queue)
                except Exception:
                    pass


__all__ = ["SessionTargetClient"]
