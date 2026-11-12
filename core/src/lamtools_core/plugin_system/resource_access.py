"""user:“复用原宿主权威”+(当前插件进程内资源读取沿用原显式路由与作用域)。"""
import asyncio
from urllib.parse import urlencode

from starlette.requests import Request
from .management_access import HostOperationError
from .plugin_http import plugin_http_token
from .remote_resource import HeadOnlyResponse, MAX_RESOURCE_BYTES, _path, dispatch_resource


class PluginResourceAccess:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._catalog = context.resolved_operation_catalog()
        self._host = getattr(self._catalog, 'plugin_system_host', None)

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or self._context.resolved_operation_catalog() is not self._catalog
                or getattr(self._catalog, 'plugin_system_host', None) is not self._host):
            raise HostOperationError('host/changed', 'Original resource host binding changed')
        if self._host is None or self._catalog is None or not self._host.available(self._scope.owner):
            raise HostOperationError('host/unavailable', 'Original resource host is unavailable')

    async def read(self, path, *, method='GET', query=None):
        if method not in ('GET', 'HEAD') or type(method) is not str:
            raise ValueError('Resource method must be GET or HEAD')
        path = _path(path)
        # user:“复用原宿主权威”+(查询参数走同一资源路由，编码后沿用原查询长度限制)。
        if query is None:
            query = {}
        if type(query) is not dict or any(type(k) is not str or type(v) is not str for k, v in query.items()):
            raise ValueError('Resource query must be a string map')
        if len(query) > 4096 or sum(len(k) + len(v) for k, v in query.items()) > 8192:
            raise ValueError('Resource query exceeds size limit')
        try:
            query_string = urlencode(query).encode('ascii')
        except UnicodeError:
            raise ValueError('Invalid resource query') from None
        if len(query_string) > 8192:
            raise ValueError('Resource query exceeds size limit')
        self._scope.acquire()
        try:
            self._check()
            # user:“复用原宿主权威”+(只读取现有插件令牌，不创建或向调用方返回密钥)。
            token = plugin_http_token(self._host, self._scope.owner, create=False)
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method,
                'scheme': 'http', 'path': '/plugin-resource/' + self._scope.owner + path, 'query_string': query_string,
                'headers': [(b'x-plugin-token', token.encode('ascii'))] if token and token.isascii() else [],
                'client': None, 'server': ('in-process', 80)}
            first = True
            async def receive():
                nonlocal first
                if first:
                    first = False
                    return {'type': 'http.request', 'body': b'', 'more_body': False}
                await asyncio.Event().wait()
            status, headers, parts, size = None, {}, [], 0
            async def send(message):
                nonlocal status, headers, size
                if message['type'] == 'http.response.start':
                    status = message['status']
                    allowed = {b'content-type', b'content-length', b'cache-control', b'x-content-type-options', b'content-security-policy'}
                    headers = {key.decode('latin1'): value.decode('latin1') for key, value in message.get('headers', []) if key.lower() in allowed}
                elif message['type'] == 'http.response.body':
                    chunk = message.get('body', b'')
                    size += len(chunk)
                    if size > MAX_RESOURCE_BYTES:
                        raise ValueError('Resource response exceeds size limit')
                    parts.append(chunk)
            def bound_host():
                try:
                    self._check()
                    return self._host
                except Exception:
                    return None
            def bound_catalog():
                try:
                    self._check()
                    return self._catalog
                except Exception:
                    return None
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(同一路由和受控响应先完整结算，再发布给当前插件)。
            response = await dispatch_resource(bound_host, bound_catalog, self._scope.owner, path[1:], Request(scope, receive))
            if method == 'HEAD':
                response = HeadOnlyResponse(response)
            await response(scope, receive, send)
            self._check()
            return {'status': status, 'headers': headers, 'body': b''.join(parts)}
        finally:
            self._scope.release()
