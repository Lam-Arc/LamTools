"""user:“第二阶段结束后 就继续开展第三阶段”+(明确声明的插件资源沿用原认证及操作归属)。"""
import asyncio
import re

from fastapi.responses import Response
from lamtools_core.async_tasks import finish_on_cancel
from .capabilities import CapabilityError
from .plugin_http import MAX_REQUEST_BODY_BYTES, _normalize_path, dispatch_http_request, read_http_routes
from .remote_binary import RemotePayload
from .remote_gateway import authenticate_remote, remote_response
from .remote_stream import binding_check, reserve

MAX_RESOURCE_BYTES = 8 * 1024 * 1024
MAX_RESOURCE_CHUNK = 256 * 1024
MAX_RESOURCE_CHUNKS = 4096
_MEDIA = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")


class HeadOnlyResponse(Response):
    def __init__(self, response):
        super().__init__()
        self._response = response

    async def __call__(self, scope, receive, send):
        async def without_body(message):
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(HEAD包括认证错误都不发送实体内容)。
            if message['type'] == 'http.response.body':
                message = {**message, 'body': b''}
            await send(message)
        return await self._response(scope, receive, without_body)


class BoundResourceResponse(Response):
    def __init__(self, *args, valid, **kwargs):
        super().__init__(*args, **kwargs)
        self._valid = valid

    async def __call__(self, scope, receive, send):
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(响应实际发送前再次检查原资源授权)。
        if not self._valid():
            return await remote_response(409, {'error': 'Resource binding changed', 'may_have_changed': True})(scope, receive, send)
        return await super().__call__(scope, receive, send)


class BinaryResourceResponse(Response):
    def __init__(self, source, mime, valid, release):
        super().__init__(content=b'', media_type=mime, headers={'cache-control': 'no-store',
            'x-content-type-options': 'nosniff', 'content-security-policy': "sandbox; default-src 'none'"})
        self.raw_headers = [(key, value) for key, value in self.raw_headers if key != b'content-length']
        self.source, self.valid, self.release = source, valid, release

    async def __call__(self, scope, receive, send):
        tasks = []
        revoked = False
        async def produce():
            await send({'type': 'http.response.start', 'status': 200, 'headers': self.raw_headers})
            total = count = 0
            async for chunk in self.source:
                # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(逐块复核授权并限制原始资源流大小)。
                if not self.valid() or type(chunk) is not bytes or len(chunk) > MAX_RESOURCE_CHUNK:
                    raise ValueError('Resource stream failed')
                count += 1
                total += len(chunk)
                if count > MAX_RESOURCE_CHUNKS or total > MAX_RESOURCE_BYTES:
                    raise ValueError('Resource stream exceeds limit')
                await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
            if not self.valid():
                raise ValueError('Resource stream binding changed')
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})

        async def disconnected():
            while (await receive())['type'] != 'http.disconnect':
                pass

        async def withdrawn():
            while self.valid():
                await asyncio.sleep(0.2)

        async def close():
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self.source.aclose()
            finally:
                self.release()

        try:
            if not self.valid():
                return await remote_response(409, {'error': 'Resource binding changed', 'may_have_changed': True})(scope, receive, send)
            tasks = [asyncio.create_task(fn(), name='plugin-resource-stream-' + fn.__name__)
                     for fn in (produce, disconnected, withdrawn)]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            revoked = tasks[2] in done and tasks[0] not in done and tasks[1] not in done
            for task in done:
                task.result()
        finally:
            await finish_on_cancel(close(), name='plugin-resource-stream-close')
        if revoked:
            raise RuntimeError('Resource stream binding changed')


def _path(value, *, declaration=False):
    if type(value) is not str or not value.startswith('/') or len(value) > 2048:
        raise ValueError('Invalid resource path')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or any(x in value for x in ('\\', '?', '#', '..', '//')):
        raise ValueError('Invalid resource path')
    value.encode('utf8')
    if declaration and value != '/' and value.endswith('/'):
        raise ValueError('Invalid resource path')
    return value


def read_resources(manifest):
    raw = manifest.raw.get('http')
    entries = raw.get('resources', []) if type(raw) is dict else []
    if type(entries) is not list or len(entries) > 16:
        raise ValueError('Declare at most 16 resource routes')
    routes = {(route.method, route.path): route for route in read_http_routes(manifest)}
    result, seen = [], set()
    for entry in entries:
        if type(entry) is not dict or entry.get('kind') not in ('exact', 'prefix', 'fallback'):
            raise ValueError('Invalid resource declaration')
        kind = entry['kind']
        required = {'kind', 'route'} if kind == 'fallback' else {'kind', 'path', 'route'}
        if set(entry) not in (required, required | {'encoding'}):
            raise ValueError('Invalid resource declaration')
        encoding = entry.get('encoding', 'buffered')
        if type(encoding) is not str or encoding not in ('buffered', 'stream'):
            raise ValueError('Invalid resource encoding')
        path = '' if kind == 'fallback' else _path(entry['path'], declaration=True)
        if (kind, path) in seen or type(entry['route']) is not str:
            raise ValueError('Duplicate resource route')
        route = routes.get(('POST', _normalize_path(entry['route'])))
        if route is None or route.auth != 'token':
            raise ValueError('Resource requires an existing token POST route')
        seen.add((kind, path)); result.append((kind, path, route.path, encoding))
    return result


def match_resource(rows, path):
    exact = next((row for row in rows if row[0] == 'exact' and row[1] == path), None)
    if exact is not None:
        return exact
    candidates = [row for row in rows if row[0] == 'prefix' and
                  (path == row[1] or (path.startswith(row[1] + '/') if row[1] != '/' else path.startswith('/')))]
    if candidates:
        return max(candidates, key=lambda row: len(row[1]))
    return next((row for row in rows if row[0] == 'fallback'), None)


async def dispatch_resource(host_provider, catalog_provider, plugin, path, request):
    host, catalog = host_provider(), catalog_provider()
    if catalog is None:
        return remote_response(503, {'error': 'plugin system is not ready'})
    headers = dict(request.headers)
    rejection = authenticate_remote(host, plugin, headers)
    if rejection is not None:
        return remote_response(*rejection)
    manifest = host.get(plugin)
    if manifest is None:
        return remote_response(409, {'error': 'Resource binding changed'})
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(传给处理器的查询串有界，认证之前不读取请求体)。
    if len(request.scope.get('query_string', b'')) > 8192:
        return remote_response(400, {'error': 'Resource query exceeds size limit'})
    try:
        resource_path = _path('/' + path)
        rows = read_resources(manifest)
        selected = match_resource(rows, resource_path)
        from .process_runtime import process_runtime_spec
        if process_runtime_spec(manifest) is not None:
            return remote_response(400, {'error': 'Resource requires an in-process handler'})
    except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
        return remote_response(400, {'error': 'Invalid resource declaration or path'})
    if selected is None:
        return remote_response(404, {'error': 'Resource route is not declared'})
    try:
        native_valid = binding_check(host, catalog, plugin, manifest, selected[2])
    except Exception:
        return remote_response(409, {'error': 'Resource binding changed'})
    def valid():
        try:
            return (host_provider() is host and catalog_provider() is catalog and native_valid()
                    and match_resource(read_resources(host.get(plugin)), resource_path) == selected)
        except Exception:
            return False
    if not valid():
        return remote_response(409, {'error': 'Resource binding changed'})
    def pre_dispatch(current, route, spec):
        if not valid():
            return 409, {'error': 'Resource binding changed'}
        return authenticate_remote(host, plugin, headers)
    async def invoke():
        return await dispatch_http_request(host=host, catalog=catalog, plugin=plugin, method='POST', path=selected[2],
            query=dict(request.query_params), body={'path': resource_path, 'method': request.method}, headers=headers,
            remote=str(request.client.host if request.client else ''), create_token=False, pre_dispatch=pre_dispatch)
    async def close_unexpected(payload, preserve=None):
        value = payload.get('payload') if type(payload) is dict else None
        source = value.get('content') if type(value) is dict else value
        if source is not preserve and callable(getattr(source, '__anext__', None)) and callable(getattr(source, 'aclose', None)):
            await source.aclose()
            return True
        return False
    async def monitor_disconnect():
        size = 0
        while True:
            try:
                message = await request.receive()
            except Exception:
                return 499
            if message['type'] == 'http.disconnect':
                return 499
            if message['type'] == 'http.request':
                size += len(message.get('body', b''))
                if size > MAX_REQUEST_BODY_BYTES:
                    return 413
    async def monitor_binding():
        while valid():
            await asyncio.sleep(0.2)
    release = reserve(host, plugin)
    if release is None:
        return remote_response(429, {'error': 'Resource capacity exceeded'})
    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(断连或取消时回收原操作，重复取消也等待清理)。
    task = asyncio.create_task(invoke(), name='plugin-resource-dispatch')
    monitor = asyncio.create_task(monitor_disconnect(), name='plugin-resource-disconnect')
    withdrawn = asyncio.create_task(monitor_binding(), name='plugin-resource-binding')
    consumed = handed_off = source_closed = False
    source = None
    try:
        try:
            await asyncio.wait((task, monitor, withdrawn), return_when=asyncio.FIRST_COMPLETED)
            if monitor.done():
                return Response(status_code=monitor.result())
            if withdrawn.done():
                return remote_response(409, {'error': 'Resource binding changed', 'may_have_changed': True})
            status, payload = task.result()
            consumed = True
            value = payload.get('payload') if type(payload) is dict else None
            mime = value.get('mime_type') if type(value) is dict else None
            candidate = value.get('content') if type(value) is dict else None
            try:
                owned = (callable(getattr(candidate, '__anext__', None)) and callable(getattr(candidate, '__aiter__', None))
                         and callable(getattr(candidate, 'aclose', None)) and candidate.__aiter__() is candidate)
            except Exception:
                owned = False
            if (selected[3] == 'stream' and status == 200 and type(value) is dict
                    and set(value) == {'content', 'mime_type'} and type(mime) is str and len(mime) <= 127
                    and _MEDIA.fullmatch(mime) and owned):
                source = candidate
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(未声明的响应流必须先关闭，再拒绝或报告撤回)。
            unexpected = await finish_on_cancel(close_unexpected(payload, preserve=source), name='plugin-resource-unexpected-close')
        finally:
            async def join():
                for pending in (task, monitor, withdrawn):
                    if not pending.done():
                        pending.cancel()
                results = await asyncio.gather(task, monitor, withdrawn, return_exceptions=True)
                result = results[0]
                if not consumed and isinstance(result, tuple) and len(result) == 2:
                    await close_unexpected(result[1])
            await finish_on_cancel(join(), name='plugin-resource-dispatch-cleanup')
        if not valid():
            return remote_response(409, {'error': 'Resource binding changed', 'may_have_changed': True})
        if unexpected:
            return remote_response(502, {'error': 'Resource streams are not supported'})
        if status != 200:
            return remote_response(status, RemotePayload(payload, allow_binary=False))
        if source is not None:
            if request.method == 'HEAD':
                source_closed = True
                await finish_on_cancel(source.aclose(), name='plugin-resource-head-source-close')
                response = BoundResourceResponse(b'', media_type=mime, valid=valid, headers={
                    'cache-control': 'no-store', 'x-content-type-options': 'nosniff',
                    'content-security-policy': "sandbox; default-src 'none'"})
                response.raw_headers = [(key, value) for key, value in response.raw_headers if key != b'content-length']
                return response
            response = BinaryResourceResponse(source, mime, valid, release)
            handed_off = True
            return response
        if type(value) is not dict or set(value) != {'content', 'mime_type'}:
            return remote_response(502, {'error': 'Invalid resource result'})
        content, mime = value['content'], value['mime_type']
        if selected[3] != 'buffered' or type(content) is not bytes or len(content) > MAX_RESOURCE_BYTES or type(mime) is not str or len(mime) > 127 or not _MEDIA.fullmatch(mime):
            return remote_response(502, {'error': 'Invalid resource result'})
        return BoundResourceResponse(content if request.method == 'GET' else b'', media_type=mime, valid=valid, headers={
            'content-length': str(len(content)), 'cache-control': 'no-store', 'x-content-type-options': 'nosniff',
            'content-security-policy': "sandbox; default-src 'none'"})
    finally:
        if not handed_off:
            async def finalize():
                nonlocal source_closed
                try:
                    if source is not None and not source_closed:
                        source_closed = True
                        await source.aclose()
                finally:
                    release()
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(响应流未移交时关闭来源并保留容量直到清理结束)。
            await finish_on_cancel(finalize(), name='plugin-resource-finalize')
