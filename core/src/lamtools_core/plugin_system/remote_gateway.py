"""user:“第二阶段结束后 就继续开展第三阶段”+(明确的一元Remote映射复用原HTTP路由与认证，不开放任意操作目录或推断服务方法)。"""
import asyncio
import copy
import hmac
import json
import re

from .capabilities import CapabilityError
from .operation_bridge import read_operations
from .plugin_http import _normalize_path, _provided_token, dispatch_http_request, plugin_http_token, read_http_routes
from .tool_schema import check_arguments, check_schema
from .remote_binary import (RemotePayload, encode_remote_response, MAX_BINARY_BYTES, MAX_RESULT_JSON_BYTES,
                            MAX_ATTACHMENTS, MAX_RESULT_DEPTH, MAX_RESULT_NODES)

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")


def authenticate_remote(host, plugin, headers):
    if host is None:
        return 503, {"error": "plugin system is not ready"}
    if not host.available(plugin):
        return 409, {"error": "plugin is not available"}
    if host.get(plugin) is None:
        return 404, {"error": "plugin is not installed"}
    # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(先验证已有令牌，再披露方法/参数；未认证请求不创建令牌)。
    expected = plugin_http_token(host, plugin, create=False)
    supplied = _provided_token({str(k).lower(): str(v) for k, v in (headers or {}).items()})
    if not expected or not supplied or not expected.isascii() or not supplied.isascii() or not hmac.compare_digest(expected, supplied):
        return 401, {"error": "invalid plugin token"}
    return None


def read_remote_methods(manifest):
    raw = manifest.raw.get("http")
    rows = raw.get("remote", []) if type(raw) is dict else []
    if type(rows) is not list or len(rows) > 64:
        raise ValueError("Declare at most 64 explicit Remote methods")
    routes = {(route.method, route.path): route for route in read_http_routes(manifest)}
    methods = {}
    for row in rows:
        if (type(row) is not dict or set(row) - {"namespace", "method", "route", "argsSchema", "resultEncoding", "resource"}
                or not {"namespace", "method", "route", "argsSchema"} <= set(row)):
            raise ValueError("Remote method needs namespace, method, route and argsSchema")
        if any(type(row[key]) is not str or not _NAME.fullmatch(row[key]) for key in ("namespace", "method")):
            raise ValueError("Remote namespace and method must be bounded names")
        key = (row["namespace"], row["method"])
        encoding = row.get("resultEncoding", "json")
        if type(encoding) is not str or encoding not in {"json", "multipart", "ndjson"}:
            raise ValueError("Remote resultEncoding must be json, multipart or ndjson")
        if key in methods or type(row["route"]) is not str:
            raise ValueError("Remote method must have a unique name and explicit route")
        route = routes.get(("POST", _normalize_path(row["route"])))
        if route is None or route.auth != "token":
            raise ValueError("Remote method must map to an existing token-authenticated POST route")
        schema = row["argsSchema"]
        if len(json.dumps(schema, ensure_ascii=False, allow_nan=False).encode("utf8")) > 32768:
            raise ValueError("Remote schema exceeds 32 KiB")
        check_schema(schema)
        properties, required = schema.get("properties", {}), schema.get("required", [])
        if (schema.get("type") != "object" or schema.get("additionalProperties") is not False
                or len(properties) > 32 or len(required) != len(properties) or set(required) != set(properties)
                or any(not _NAME.fullmatch(name) for name in properties)):
            raise ValueError("Remote v1 requires at most 32 exact required primitive fields")
        resource = row.get("resource")
        if "resource" in row:
            if (type(resource) is not dict or set(resource) != {"kind", "argument"}
                    or resource.get("kind") not in {"session", "workspace"} or type(resource.get("argument")) is not str
                    or resource["argument"] not in properties
                    or type(properties[resource["argument"]]) is not dict
                    or properties[resource["argument"]].get("type") != "string"):
                raise ValueError("Resource requires one explicit string resource argument")
        methods[key] = (route.path, copy.deepcopy(schema), encoding)
    return methods


def resource_admission(host, plugin, kind, resource_id):
    from .backend_runtime import context_for
    guard_context = context_for(plugin, host)
    guard_scope = getattr(guard_context, "_registration_scope", None)
    if guard_scope is None or guard_scope.owner != plugin:
        raise RuntimeError("Resource context unavailable")
    controller = None
    if kind == "session":
        cached = getattr(guard_scope, "_remote_session_guard", None)
        if cached is None:
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(同一启动代复用会话门面，避免每帧累积服务依赖)。
            cached = (guard_context, guard_context.session_controller)
            guard_scope._remote_session_guard = cached
        if cached[0] is not guard_context:
            raise RuntimeError("Resource context changed")
        controller = cached[1]
    async def admit():
        from .session_controller import _cancel_owned_read
        if context_for(plugin, host) is not guard_context or guard_context._registration_scope is not guard_scope:
            raise RuntimeError("Resource context changed")
        # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(准入复用原会话可见性和当前项目，不接受调用方指定的授权根)。
        if kind == "session":
            await _cancel_owned_read(controller._admit(resource_id), name="remote-session-admission")
        elif kind == "workspace":
            if await _cancel_owned_read(guard_context.workspace_registry.get(resource_id), name="remote-workspace-admission") is None:
                raise RuntimeError("Workspace is unavailable")
        else:
            raise RuntimeError("Unknown resource kind")
        if context_for(plugin, host) is not guard_context or guard_context._registration_scope is not guard_scope:
            raise RuntimeError("Resource context changed")
    return admit


async def dispatch_remote_request(*, host, catalog, plugin, namespace, method, body, headers=None, remote="", binding_valid=None):
    if host is None or catalog is None:
        return 503, {"error": "plugin system is not ready"}
    rejection = authenticate_remote(host, plugin, headers)
    if rejection is not None:
        return rejection
    manifest = host.get(plugin)
    if manifest is None:
        return 404, {"error": "plugin is not installed"}
    declaration = copy.deepcopy(manifest.raw)
    manager = getattr(host, "backend_manager", None)
    generation = manager.generation.get(plugin) if manager is not None else None
    try:
        methods = read_remote_methods(manifest)
    except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
        return 400, {"error": "invalid plugin Remote declaration"}
    descriptor = methods.get((namespace, method))
    if descriptor is None:
        return 404, {"error": "Remote method is not declared"}
    path, schema, encoding = descriptor
    operation = next(route.operation for route in read_http_routes(manifest) if route.method == "POST" and route.path == path)
    operation_token = catalog.binding_token(operation)
    try:
        if type(body) is not dict or set(body) != {"args"}:
            raise ValueError("Use one exact args object")
        check_arguments(schema, body["args"])
        # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(无效Unicode参数在原操作执行前拒绝)。
        json.dumps(body["args"], ensure_ascii=False, allow_nan=False).encode("utf-8")
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(准入与派发必须使用同一份已校验参数)。
        arguments = copy.deepcopy(body["args"])
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return 400, {"error": "invalid Remote arguments"}
    row = next(item for item in manifest.raw["http"]["remote"]
               if item["namespace"] == namespace and item["method"] == method)
    resource = row.get("resource")
    if resource is not None:
        try:
            admit_resource = resource_admission(host, plugin, resource["kind"], arguments[resource["argument"]])
            await admit_resource()
        except Exception:
            return 403, {"error": "Remote resource unavailable"}
    def pre_dispatch(_manifest, route, spec):
        # user:“复用原宿主权威”+(最后派发前复核实际声明、路由、操作、启动代和既有令牌；未引入新授权体系)。
        try:
            current = host.get(plugin)
            if ((binding_valid is not None and not binding_valid()) or current is None or current.raw != declaration or getattr(host, "backend_manager", None) is not manager
                    or (manager is not None and manager.generation.get(plugin) != generation)
                    or read_remote_methods(current).get((namespace, method)) != descriptor):
                return 409, {"error": "Remote binding changed"}
            current_routes = read_http_routes(current)
            if route not in current_routes or spec not in read_operations(current):
                return 409, {"error": "Remote binding changed"}
            # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(声明解析后同名操作重新注册不能进入新处理器)。
            if (route.operation != operation or operation_token is None
                    or catalog.binding_token(operation) is not operation_token):
                return 409, {"error": "Remote binding changed"}
            return authenticate_remote(host, plugin, headers)
        except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
            return 409, {"error": "Remote binding changed"}
    # user:“复用原宿主权威”+(原路由再次检查可用性、令牌、操作归属和审批；不直连catalog.execute，不回退到未声明方法)。
    from .remote_stream import reserve, binding_check, RemoteStreamResponse
    native_valid = binding_check(host, catalog, plugin, manifest, path)
    def valid():
        try:
            return (binding_valid is None or binding_valid()) and native_valid()
        except Exception:
            return False
    release = None
    if encoding == "ndjson":
        release = reserve(host, plugin)
        if release is None:
            return 429, {"error": "Remote stream capacity exceeded"}
    try:
        status, result = await dispatch_http_request(host=host, catalog=catalog, plugin=plugin, method="POST", path=path,
            # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(业务处理器的可变参数副本不能改变后续资源准入依据)。
            body=dict(arguments), headers=headers, remote=remote, create_token=False, pre_dispatch=pre_dispatch)
        if resource is not None and "status" in result:
            try:
                await admit_resource()
            except BaseException as error:
                source = result.get("payload")
                if callable(getattr(source, "__anext__", None)) and callable(getattr(source, "aclose", None)):
                    from lamtools_core.async_tasks import finish_on_cancel
                    await finish_on_cancel(source.aclose(), name="plugin-remote-resource-close")
                if isinstance(error, asyncio.CancelledError):
                    raise
                if not isinstance(error, Exception):
                    raise
                return 409, {"error": "Remote resource changed", "may_have_changed": True}
        if "status" in result and not valid():
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(处理器结算后失效时不发布旧结果，可能已有写入)。
            source = result.get("payload")
            if callable(getattr(source, "__anext__", None)) and callable(getattr(source, "aclose", None)):
                from lamtools_core.async_tasks import finish_on_cancel
                await finish_on_cancel(source.aclose(), name="plugin-remote-withdrawn-stream-close")
            return 409, {"error": "Remote binding changed", "may_have_changed": True}
        if encoding == "ndjson" and status == 200:
            source = result["payload"]
            try:
                owned = (callable(getattr(source, "__anext__", None)) and callable(getattr(source, "__aiter__", None))
                    and callable(getattr(source, "aclose", None)) and source.__aiter__() is source)
            except Exception:
                owned = False
            if not owned:
                close = getattr(source, "aclose", None)
                if callable(close):
                    from lamtools_core.async_tasks import finish_on_cancel
                    await finish_on_cancel(close(), name="plugin-remote-invalid-stream-close")
                return 502, {"code": "gateway/invalid-stream", "error": "Use an owned async iterator"}
            response = RemoteStreamResponse(source, valid, release, async_valid=admit_resource if resource is not None else None)
            release = None
            return status, response
        source = result.get("payload")
        if callable(getattr(source, "__anext__", None)) and callable(getattr(source, "aclose", None)):
            # user:“第二阶段结束后 就继续开展第三阶段”+(业务失败或未声明流时，拒绝并真实关闭提供方，不能仅编码失败留下资源)。
            from lamtools_core.async_tasks import finish_on_cancel
            await finish_on_cancel(source.aclose(), name="plugin-remote-rejected-stream-close")
            return 502, {"code": "gateway/invalid-stream", "error": "Stream requires successful explicit ndjson method"}
        return status, RemotePayload(result, allow_binary=encoding == "multipart")
    finally:
        if release is not None:
            release()


def remote_response(status, payload):
    from .remote_stream import RemoteStreamResponse
    if isinstance(payload, RemoteStreamResponse):
        return payload
    return encode_remote_response(status, payload, limits=(MAX_BINARY_BYTES, MAX_RESULT_JSON_BYTES,
        MAX_ATTACHMENTS, MAX_RESULT_DEPTH, MAX_RESULT_NODES))
