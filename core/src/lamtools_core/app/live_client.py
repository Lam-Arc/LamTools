from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any


WebSocketConnect = Callable[[str], Awaitable[Any]]

logger = logging.getLogger(__name__)


class CoreAppServerClient:
    def __init__(
        self,
        base_url: str = "http://localhost:6173",
        *,
        path: str = "/api/core/app-server",
        token: str | None = None,
        client_info: dict[str, Any] | None = None,
        websocket_connect: WebSocketConnect | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.path = path
        self.token = str(token or "").strip()
        self.client_info = client_info or {"name": "core_cli", "version": "0.1.0"}
        self.websocket_connect = websocket_connect
        self._session: Any | None = None
        self._ws: Any | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._seen_event_ids: set[str] = set()
        self._reader: asyncio.Task[None] | None = None

    async def connect(self, *, thread_id: str | None = None, last_seen_seq: int = 0) -> None:
        self._ws = await self._connect_websocket()
        self._reader = asyncio.create_task(self._read_loop())
        await self.request(
            "initialize",
            {
                "clientInfo": dict(self.client_info),
                "threadId": thread_id,
                "lastSeenSeq": last_seen_seq,
            },
        )
        await self.request("initialized", {})
        if thread_id:
            await self._resume_thread(thread_id=thread_id, last_seen_seq=last_seen_seq)

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self._request_result(method, params)
        command_result = result.get("result")
        return command_result if isinstance(command_result, dict) else result

    async def _request_result(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("App-server client is not connected")
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._ws.send_json({"id": request_id, "method": method, "params": params or {}})
        response = await future
        if "error" in response:
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(str(message or "app-server request failed"))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def start_turn(
        self,
        *,
        thread_id: str,
        input_items: list[dict[str, Any]],
        work_root: str = "",
        mode: str = "",
        model_id: str | None = None,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        context_window_tokens: int | None = None,
        approval_policy: str | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        import uuid

        params: dict[str, Any] = {
            "thread_id": thread_id,
            "client_message_id": client_message_id or str(uuid.uuid4()),
            "input": input_items,
            "work_root": work_root,
            "mode": mode,
        }
        if model_id:
            params["model_id"] = model_id
        if thinking_enabled is not None:
            params["thinking_enabled"] = thinking_enabled
        if thinking_budget is not None:
            params["thinking_budget"] = thinking_budget
        if shallow_thinking_enabled is not None:
            params["shallow_thinking_enabled"] = shallow_thinking_enabled
        if context_window_tokens is not None:
            params["context_window_tokens"] = context_window_tokens
        if approval_policy:
            params["approval_policy"] = approval_policy
        response = await self.request("turn.start", params)
        for event in response.get("events") or []:
            await self.put_app_server_event(event)
        return response

    async def steer_turn(self, *, thread_id: str, turn_id: str, input_items: list[dict[str, Any]]) -> dict[str, Any]:
        import uuid

        response = await self.request(
            "turn/steer",
            {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "client_message_id": str(uuid.uuid4()),
                "input": input_items,
            },
        )
        for event in response.get("events") or []:
            await self.put_app_server_event(event)
        return response

    async def guide_queue_input(
        self,
        *,
        thread_id: str,
        turn_id: str,
        queue_item_id: str,
        text: str | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            "queue/guide",
            {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "queue_item_id": queue_item_id,
                "client_message_id": f"queue-guide:{queue_item_id}",
                **({"text": text.strip()} if text and text.strip() else {}),
            },
        )
        for event in response.get("events") or []:
            await self.put_app_server_event(event)
        return {
            "applied": response.get("applied") is True,
            "reason": str(response.get("reason") or ""),
        }

    async def create_queue_input(
        self,
        *,
        thread_id: str,
        input_items: list[dict[str, Any]],
        queue_item_id: str | None = None,
        client_message_id: str | None = None,
        mode: str = "next_turn",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "thread_id": thread_id,
            "input": input_items,
            "mode": mode,
        }
        if queue_item_id:
            params["queue_item_id"] = queue_item_id
        if client_message_id:
            params["client_message_id"] = client_message_id
        return await self._request_with_events("queue/create", params)

    async def update_queue_input(
        self,
        *,
        thread_id: str,
        queue_item_id: str,
        text: str,
    ) -> dict[str, Any]:
        return await self._request_with_events(
            "queue/update",
            {"thread_id": thread_id, "queue_item_id": queue_item_id, "text": text},
        )

    async def delete_queue_input(self, *, thread_id: str, queue_item_id: str) -> dict[str, Any]:
        return await self._request_with_events(
            "queue/delete",
            {"thread_id": thread_id, "queue_item_id": queue_item_id},
        )

    async def respond_approval(self, *, request_id: str, decision: str, guidance: str = "") -> None:
        response = await self.request(
            "approval.respond",
            {
                "request_id": request_id,
                "decision": decision,
                "guidance": guidance,
            },
        )
        event = response.get("event")
        if isinstance(event, dict):
            await self.put_app_server_event(event)

    async def cancel_turn(self, *, thread_id: str, turn_id: str = "") -> dict[str, Any]:
        return await self.request("turn.cancel", {"thread_id": thread_id, "turn_id": turn_id})

    async def read_thread(self, *, thread_id: str) -> dict[str, Any]:
        return await self.request("thread.read", {"thread_id": thread_id})

    async def execute_command(self, *, thread_id: str, command: str, work_root: str = "") -> dict[str, Any]:
        response = await self._request_result(
            "command.execute",
            {
                "thread_id": thread_id,
                "command": command,
                "work_root": work_root,
                "include_snapshot": False,
            },
        )
        for event in response.get("events") or []:
            if isinstance(event, dict):
                await self.put_app_server_event(event)
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def _request_with_events(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.request(method, params)
        for event in response.get("events") or []:
            await self.put_app_server_event(event)
        return response

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            event = await self._events.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self._ws is not None and not bool(getattr(self._ws, "closed", False)):
            try:
                await self._ws.close()
            except Exception:
                logger.warning("Failed to close app-server websocket", exc_info=True)
        if self._session is not None and not bool(getattr(self._session, "closed", False)):
            try:
                await self._session.close()
            except Exception:
                logger.warning("Failed to close app-server HTTP session", exc_info=True)

    async def __aenter__(self) -> "CoreAppServerClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def put_app_server_event(self, event: dict[str, Any]) -> None:
        key = app_server_event_dedupe_key(event)
        if key:
            if key in self._seen_event_ids:
                return
            self._seen_event_ids.add(key)
        await self._events.put(app_server_event(event))

    async def _connect_websocket(self) -> Any:
        url = self._websocket_url()
        if self.websocket_connect is not None:
            if self.token and _accepts_headers(self.websocket_connect):
                return await self.websocket_connect(url, headers={"Authorization": f"Bearer {self.token}"})
            return await self.websocket_connect(url)
        import aiohttp

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=10))
        return await self._session.ws_connect(url, headers=self._headers() or None)

    async def _resume_thread(self, *, thread_id: str, last_seen_seq: int) -> None:
        after_seq = last_seen_seq
        while True:
            response = await self.request("thread/resume", {"thread_id": thread_id, "last_seen_seq": after_seq})
            events = [event for event in response.get("events") or [] if isinstance(event, dict)]
            for event in events:
                await self.put_app_server_event(event)
            event_seq = max((int(event.get("seq") or 0) for event in events), default=after_seq)
            next_after_seq = _int_value(response.get("next_after_seq"), default=event_seq)
            snapshot = response.get("snapshot")
            snapshot_seq = _int_value(snapshot.get("snapshot_seq") if isinstance(snapshot, dict) else None, default=event_seq)
            has_more = response.get("has_more") is True
            if not has_more and snapshot_seq <= event_seq:
                return
            if next_after_seq <= after_seq:
                return
            after_seq = next_after_seq

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for message in self._ws:
            raw = self._message_payload(message)
            if raw is None:
                break
            if "id" in raw and isinstance(raw["id"], int):
                future = self._pending.pop(raw["id"], None)
                if future and not future.done():
                    future.set_result(raw)
                continue
            if raw.get("method") and isinstance(raw.get("params"), dict):
                await self.put_app_server_event(raw["params"])
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("app-server connection closed"))
        await self._events.put(None)

    def _message_payload(self, message: Any) -> dict[str, Any] | None:
        if isinstance(message, dict):
            return message
        data = getattr(message, "data", None)
        if isinstance(data, str):
            return json.loads(data)
        return None

    def _websocket_url(self) -> str:
        return self.base_url.replace("http://", "ws://").replace("https://", "wss://") + self.path


def app_server_event(event: dict[str, Any]) -> dict[str, Any]:
    return {"event": "app_server_event", "data": event}


def app_server_event_dedupe_key(event: dict[str, Any]) -> str:
    event_id = str(event.get("event_id") or "").strip()
    if event_id:
        return f"event:{event_id}"
    thread_id = str(event.get("thread_id") or "").strip()
    seq = event.get("seq")
    if thread_id and seq is not None:
        return f"seq:{thread_id}:{seq}"
    return ""


def _accepts_headers(connect: WebSocketConnect) -> bool:
    try:
        signature = inspect.signature(connect)
    except (TypeError, ValueError):
        return False
    return "headers" in signature.parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = ["CoreAppServerClient", "app_server_event", "app_server_event_dedupe_key"]
