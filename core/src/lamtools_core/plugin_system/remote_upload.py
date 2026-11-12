"""user:“继续”+(显式声明的原始上传沿用原插件认证和操作归属)。"""
import asyncio
import re

from lamtools_core.async_tasks import finish_on_cancel
from .capabilities import CapabilityError
from .file_uploads import MAX_CHUNK_UPLOAD_BYTES, MAX_UPLOAD_CHUNK_BYTES
from .plugin_http import _normalize_path, dispatch_http_request, read_http_routes
from .remote_gateway import authenticate_remote, remote_response, resource_admission
from .remote_binary import RemotePayload
from .remote_stream import binding_check, reserve

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")


def read_uploads(manifest):
    raw = manifest.raw.get("http")
    entries = raw.get("uploads", []) if type(raw) is dict else []
    if type(entries) is not list or len(entries) > 16:
        raise ValueError("Declare at most 16 upload methods")
    routes = {(route.method, route.path): route for route in read_http_routes(manifest)}
    result = {}
    for entry in entries:
        if (type(entry) is not dict or set(entry) not in ({"name", "route"}, {"name", "route", "resource"})
                or type(entry["name"]) is not str or not _NAME.fullmatch(entry["name"])
                or type(entry["route"]) is not str or entry["name"] in result):
            raise ValueError("Invalid upload declaration")
        if "resource" in entry and entry["resource"] not in ("session", "workspace"):
            raise ValueError("Invalid upload resource")
        route = routes.get(("POST", _normalize_path(entry["route"])))
        if route is None or route.auth != "token":
            raise ValueError("Upload requires an existing token POST route")
        result[entry["name"]] = route.path
    return result


class VerifiedUpload:
    def __init__(self, request, valid, size, resource_check=None):
        self._source = aiter(request.stream())
        self._valid, self._size, self._resource_check = valid, size, resource_check
        self._total, self._buffer, self._active = 0, b"", None
        self.complete, self._closed, self._close_task = False, False, None

    def __aiter__(self):
        return self

    async def _check(self):
        if not self._valid():
            raise RuntimeError("Upload binding changed")
        if self._resource_check is not None:
            await self._resource_check()
        if not self._valid():
            raise RuntimeError("Upload binding changed")

    async def __anext__(self):
        if self._closed or self.complete:
            raise StopAsyncIteration
        if self._active is not None:
            raise RuntimeError("Upload source already has a reader")
        self._active = asyncio.current_task()
        try:
            while not self._buffer:
                await self._check()
                pull = asyncio.ensure_future(anext(self._source))
                async def cleanup():
                    if not pull.done():
                        pull.cancel()
                    await asyncio.gather(pull, return_exceptions=True)
                try:
                    while not pull.done():
                        await asyncio.wait((pull,), timeout=0.2)
                        # user:“继续”+(空闲请求也检查原令牌和操作声明，撤回后停止读取)。
                        await self._check()
                    try:
                        chunk = pull.result()
                    except StopAsyncIteration:
                        if self._total != self._size:
                            raise ValueError("Upload size mismatch") from None
                        self.complete = True
                        raise
                finally:
                    await finish_on_cancel(cleanup(), name="plugin-upload-receive-cleanup")
                if type(chunk) is not bytes or self._total + len(chunk) > self._size:
                    raise ValueError("Upload size mismatch")
                self._total += len(chunk)
                self._buffer = chunk
            await self._check()
            result, self._buffer = self._buffer[:MAX_UPLOAD_CHUNK_BYTES], self._buffer[MAX_UPLOAD_CHUNK_BYTES:]
            return result
        finally:
            self._active = None

    async def aclose(self):
        if self._close_task is None:
            active = self._active
            if active is asyncio.current_task():
                raise RuntimeError("Cannot close upload from its active read")
            self._closed = True
            async def close_owned():
                if active is not None:
                    active.cancel()
                    await asyncio.gather(active, return_exceptions=True)
                try:
                    await self._source.aclose()
                finally:
                    self._buffer = b""
            # user:“继续”+(并发关闭共用同一回收任务，容量等待实际接收清理后释放)。
            self._close_task = asyncio.create_task(close_owned(), name="plugin-upload-source-close")
        async def join_close():
            await asyncio.shield(self._close_task)
        await finish_on_cancel(join_close(), name="plugin-upload-source-join")


async def dispatch_upload(host_provider, catalog_provider, plugin, name, request):
    host, catalog = host_provider(), catalog_provider()
    if catalog is None:
        return remote_response(503, {"error": "plugin system is not ready"})
    headers = dict(request.headers)
    rejected = authenticate_remote(host, plugin, headers)
    if rejected is not None:
        return remote_response(*rejected)
    manifest = host.get(plugin)
    if manifest is None:
        return remote_response(409, {"error": "Upload binding changed"})
    try:
        path = read_uploads(manifest).get(name)
        from .process_runtime import process_runtime_spec
        if process_runtime_spec(manifest) is not None:
            return remote_response(400, {"error": "Streaming upload requires an in-process handler"})
    except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
        return remote_response(400, {"error": "Invalid upload declaration"})
    if path is None:
        return remote_response(404, {"error": "Upload method is not declared"})
    entry = next(item for item in manifest.raw["http"]["uploads"] if item["name"] == name)
    kind = entry.get("resource")
    resource_id = None
    resource_check = None
    if kind is not None:
        values = request.headers.getlist("x-resource-id")
        if (len(values) != 1 or not values[0] or not values[0].isascii()
                or len(values[0]) > (128 if kind == "workspace" else 256) or values[0].strip() != values[0]
                or any(ord(char) < 32 or ord(char) == 127 for char in values[0])):
            return remote_response(400, {"error": "Invalid upload resource"})
        resource_id = values[0]
        try:
            resource_check = resource_admission(host, plugin, kind, resource_id)
            # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(授权先于读取上传内容，复用同一原资源权威)。
            await resource_check()
        except Exception:
            return remote_response(403, {"error": "Upload resource unavailable"})
    raw_size = request.headers.get("x-upload-size", "")
    if not raw_size.isascii() or not raw_size.isdigit() or len(raw_size) > 8:
        return remote_response(400, {"error": "Invalid upload size"})
    size = int(raw_size)
    if size > MAX_CHUNK_UPLOAD_BYTES:
        return remote_response(413, {"error": "Upload exceeds size limit"})
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length != str(size):
        return remote_response(400, {"error": "Upload size mismatch"})
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
        return remote_response(415, {"error": "Upload requires application/octet-stream"})
    try:
        native_valid = binding_check(host, catalog, plugin, manifest, path)
    except Exception:
        return remote_response(409, {"error": "Upload binding changed"})
    def valid():
        try:
            # user:“继续”+(在途上传也要确认应用仍使用同一宿主和操作目录)。
            return host_provider() is host and catalog_provider() is catalog and native_valid()
        except Exception:
            return False
    if not valid():
        return remote_response(409, {"error": "Upload binding changed"})
    release = reserve(host, plugin)
    if release is None:
        return remote_response(429, {"error": "Upload capacity exceeded"})
    stream = VerifiedUpload(request, valid, size, resource_check)
    def pre_dispatch(current, route, spec):
        try:
            if not valid() or read_uploads(current).get(name) != path:
                return 409, {"error": "Upload binding changed"}
            return authenticate_remote(host, plugin, headers)
        except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
            return 409, {"error": "Upload binding changed"}
    try:
        # user:“继续”+(仍经原插件路由、所有权和审批门禁分发，不接受任意操作名)。
        upload_body = {"stream": stream, "size": size}
        if resource_check is not None:
            upload_body["resource_id"] = resource_id
        dispatch = asyncio.create_task(dispatch_http_request(host=host, catalog=catalog, plugin=plugin, method="POST", path=path,
            query=dict(request.query_params), body=upload_body, headers=headers,
            remote=str(request.client.host if request.client else ""), create_token=False, pre_dispatch=pre_dispatch))
        consumed = False
        try:
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(处理器空闲未读取时仍检查撤回，等待其真实清理)。
            while not dispatch.done():
                await asyncio.wait((dispatch,), timeout=0.2)
                if not valid() and not dispatch.done():
                    return remote_response(409, {"error": "Upload binding changed", "may_have_changed": True})
                if resource_check is not None and not dispatch.done():
                    try:
                        await resource_check()
                    except Exception:
                        return remote_response(409, {"error": "Upload resource changed", "may_have_changed": True})
            status, payload = dispatch.result()
            consumed = True
        finally:
            if not consumed:
                async def stop_dispatch():
                    if not dispatch.done():
                        dispatch.cancel()
                    results = await asyncio.gather(dispatch, return_exceptions=True)
                    result = results[0]
                    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
                        source = result[1].get("payload")
                        if callable(getattr(source, "__anext__", None)) and callable(getattr(source, "aclose", None)):
                            await source.aclose()
                await finish_on_cancel(stop_dispatch(), name="plugin-upload-dispatch-cleanup")
        source = payload.get("payload")
        rejected_stream = callable(getattr(source, "__anext__", None)) and callable(getattr(source, "aclose", None))
        if rejected_stream:
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(任何提前拒绝之前都回收未声明的响应流)。
            await finish_on_cancel(source.aclose(), name="plugin-upload-rejected-stream-close")
        if not valid():
            return remote_response(409, {"error": "Upload binding changed", "may_have_changed": True})
        if resource_check is not None:
            try:
                await resource_check()
            except Exception:
                return remote_response(409, {"error": "Upload resource changed", "may_have_changed": True})
        if status == 200 and not stream.complete:
            return remote_response(400, {"error": "Upload input was not fully consumed", "may_have_changed": True})
        if rejected_stream:
            return remote_response(502, {"code": "gateway/invalid-stream", "error": "Upload does not support response streams"})
        return remote_response(status, RemotePayload(payload, allow_binary=False))
    finally:
        async def close():
            try:
                await stream.aclose()
            finally:
                release()
        await finish_on_cancel(close(), name="plugin-upload-close")
