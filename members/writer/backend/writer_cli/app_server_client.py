from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import aiohttp


class AppServerClient:
    def __init__(self, base_url: str = "http://localhost:6173") -> None:
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None

    async def connect(self, *, thread_id: str | None = None, last_seen_seq: int = 0) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=10))
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/app-server"
        self._ws = await self._session.ws_connect(ws_url)
        self._reader = asyncio.create_task(self._read_loop())
        await self.request("initialize", {
            "clientInfo": {"name": "lamwriter_cli", "version": "0.1.0"},
            "threadId": thread_id,
            "lastSeenSeq": last_seen_seq,
        })
        await self.request("initialized", {})
        if thread_id:
            response = await self.request("thread/resume", {"thread_id": thread_id, "last_seen_seq": last_seen_seq})
            for event in response.get("events") or []:
                await self._events.put(_app_server_event(event))

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if isinstance(result, dict):
            command_result = result.get("result")
            return command_result if isinstance(command_result, dict) else result
        return {}

    async def start_turn(
        self,
        *,
        thread_id: str,
        message: str,
        work_root: str = "",
        mode: str = "",
        model_id: str | None = None,
        shallow_thinking_enabled: bool | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "thread_id": thread_id,
            "client_message_id": str(uuid.uuid4()),
            "input": [{"type": "text", "text": message}],
            "work_root": work_root,
            "mode": mode,
        }
        if model_id:
            params["model_id"] = model_id
        if shallow_thinking_enabled is not None:
            params["shallow_thinking_enabled"] = shallow_thinking_enabled
        response = await self.request("turn.start", params)
        for event in response.get("events") or []:
            await self._events.put(_app_server_event(event))

    async def steer_turn(self, *, thread_id: str, turn_id: str, message: str) -> None:
        response = await self.request("turn/steer", {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "client_message_id": str(uuid.uuid4()),
            "input": [{"type": "text", "text": message}],
        })
        for event in response.get("events") or []:
            await self._events.put(_app_server_event(event))

    async def respond_approval(self, *, request_id: str, decision: str, guidance: str = "") -> None:
        response = await self.request("approval.respond", {
            "request_id": request_id,
            "decision": decision,
            "guidance": guidance,
        })
        event = response.get("event")
        if isinstance(event, dict):
            await self._events.put(_app_server_event(event))

    async def cancel_turn(self, *, thread_id: str, turn_id: str = "") -> dict[str, Any]:
        return await self.request("turn.cancel", {"thread_id": thread_id, "turn_id": turn_id})

    async def list_sessions(self, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        response = await self.request("session.list", {"limit": limit, "offset": offset})
        sessions = response.get("sessions")
        return sessions if isinstance(sessions, list) else []

    async def create_session(
        self,
        *,
        title: str,
        work_root: str = "",
        mode: str = "EXECUTE",
    ) -> dict[str, Any]:
        response = await self.request(
            "session.create",
            {"title": title, "work_root": work_root, "mode": mode},
        )
        session = response.get("session")
        return session if isinstance(session, dict) else {}

    async def get_session(self, *, session_id: str) -> dict[str, Any]:
        response = await self.request("session.get", {"session_id": session_id})
        session = response.get("session")
        return session if isinstance(session, dict) else {}

    async def update_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        response = await self.request("session.update", {"session_id": session_id, "title": title})
        session = response.get("session")
        return session if isinstance(session, dict) else {}

    async def delete_session(self, *, session_id: str) -> None:
        await self.request("session.delete", {"session_id": session_id})

    async def read_thread(self, *, thread_id: str) -> dict[str, Any]:
        return await self.request("thread.read", {"thread_id": thread_id})

    async def execute_command(
        self,
        *,
        thread_id: str,
        command: str,
        work_root: str = "",
    ) -> dict[str, Any]:
        response = await self.request(
            "command.execute",
            {
                "thread_id": thread_id,
                "command": command,
                "work_root": work_root,
            },
        )
        for event in response.get("events") or []:
            await self._events.put(_app_server_event(event))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            event = await self._events.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "AppServerClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for message in self._ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                raw = json.loads(message.data)
                if "id" in raw and isinstance(raw["id"], int):
                    future = self._pending.pop(raw["id"], None)
                    if future and not future.done():
                        future.set_result(raw)
                    continue
                if raw.get("method") and isinstance(raw.get("params"), dict):
                    await self._events.put(_app_server_event(raw["params"]))
            elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                break
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("app-server connection closed"))
        await self._events.put(None)


def _app_server_event(event: dict[str, Any]) -> dict[str, Any]:
    return {"event": "app_server_event", "data": event}


__all__ = ["AppServerClient"]
