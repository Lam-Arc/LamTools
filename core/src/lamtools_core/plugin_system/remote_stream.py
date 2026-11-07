"""user:“第二阶段结束后 就继续开展第三阶段”+(明确JSON服务端流复用原认证/代际，背压、撤回和断连均回收提供方)。"""
import asyncio
import copy

from fastapi.responses import Response

from lamtools_core.async_tasks import finish_on_cancel
from .remote_binary import RemotePayload, encode_remote_response
from .remote_binary import MAX_BINARY_BYTES, MAX_RESULT_JSON_BYTES, MAX_ATTACHMENTS, MAX_RESULT_DEPTH, MAX_RESULT_NODES

POLL_INTERVAL = 0.5
MAX_STREAMS = 32


def reserve(host, plugin):
    slots = getattr(host, "_remote_stream_slots", None)
    if slots is None:
        slots = host._remote_stream_slots = {}
    if slots.get(plugin, 0) >= MAX_STREAMS:
        return None
    slots[plugin] = slots.get(plugin, 0) + 1
    released = False
    def release():
        nonlocal released
        if not released:
            released = True
            count = slots.get(plugin, 1) - 1
            if count:
                slots[plugin] = count
            else:
                slots.pop(plugin, None)
    return release


def binding_check(host, catalog, plugin, manifest, path):
    from .plugin_http import read_http_routes, plugin_http_token
    manager = getattr(host, "backend_manager", None)
    generation = manager.generation.get(plugin) if manager is not None else None
    declaration = copy.deepcopy(manifest.raw)
    operation = next(route.operation for route in read_http_routes(manifest) if route.method == "POST" and route.path == path)
    token = plugin_http_token(host, plugin, create=False)
    def valid():
        current = host.get(plugin)
        return (host.available(plugin) and current is not None and current.raw == declaration
            and getattr(host, "backend_manager", None) is manager
            and (manager is None or manager.generation.get(plugin) == generation)
            and catalog.has(operation) and catalog.owner_of(operation) == "plugin:" + plugin
            and bool(token) and plugin_http_token(host, plugin, create=False) == token)
    return valid


def encode_frame(value):
    result = encode_remote_response(200, RemotePayload(value, allow_binary=False),
        limits=(MAX_BINARY_BYTES, MAX_RESULT_JSON_BYTES, MAX_ATTACHMENTS, MAX_RESULT_DEPTH, MAX_RESULT_NODES))
    if result.status_code != 200:
        raise ValueError("invalid JSON stream frame")
    return result.body + b"\n"


class RemoteStreamResponse(Response):
    media_type = "application/x-ndjson"

    def __init__(self, source, valid, release):
        super().__init__(status_code=200, media_type=self.media_type,
            headers={"cache-control": "no-store", "x-content-type-options": "nosniff"})
        self.raw_headers = [(key, value) for key, value in self.raw_headers if key != b"content-length"]
        self.source, self.valid, self.release = source, valid, release

    async def __call__(self, scope, receive, send):
        tasks = []
        revoked = False
        async def produce():
            await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
            try:
                async for value in self.source:
                    if not self.valid():
                        raise ValueError("stream binding changed")
                    frame = encode_frame({"kind": "item", "payload": value})
                    await send({"type": "http.response.body", "body": frame, "more_body": True})
                frame = encode_frame({"kind": "end"})
            except (asyncio.CancelledError, OSError):
                raise
            except Exception:
                frame = b'{"kind":"error","code":"gateway/stream-failed"}\n'
            await send({"type": "http.response.body", "body": frame, "more_body": False})

        async def disconnected():
            while (await receive())["type"] != "http.disconnect":
                pass

        async def withdrawn():
            while self.valid():
                await asyncio.sleep(POLL_INTERVAL)

        async def close():
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self.source.aclose()
            finally:
                self.release()

        try:
            if not self.valid():
                await send({"type": "http.response.start", "status": 409, "headers": []})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            tasks = [asyncio.create_task(work(), name="plugin-remote-stream-" + work.__name__)
                for work in (produce, disconnected, withdrawn)]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            revoked = tasks[2] in done and tasks[0] not in done and tasks[1] not in done
            for task in done:
                task.result()
        finally:
            # user:“第二阶段结束后 就继续开展第三阶段”+(回收等待真实pull/send退出，再关闭原迭代器；重复取消不能遗留监听或容量)。
            await finish_on_cancel(close(), name="plugin-remote-stream-close")
        if revoked:
            # user:“第二阶段结束后 就继续开展第三阶段”+(授权撤回不能伪装正常end；先回收提供方，再有界发送终止错误，坏连接不会拖住资源)。
            try:
                async with asyncio.timeout(0.5):
                    await send({"type": "http.response.body", "body": b'{"kind":"error","code":"gateway/stream-closed"}\n',
                        "more_body": False})
            except (OSError, TimeoutError):
                pass
