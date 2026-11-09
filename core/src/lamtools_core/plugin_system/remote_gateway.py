"""user:“第二阶段结束后 就继续开展第三阶段”+(明确的一元Remote映射复用原HTTP路由与认证，不开放任意操作目录或推断服务方法)。"""
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
        if (type(row) is not dict or set(row) - {"namespace", "method", "route", "argsSchema", "resultEncoding"}
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
        methods[key] = (route.path, copy.deepcopy(schema), encoding)
    return methods


async def dispatch_remote_request(*, host, catalog, plugin, namespace, method, body, headers=None, remote=""):
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
    try:
        if type(body) is not dict or set(body) != {"args"}:
            raise ValueError("Use one exact args object")
        check_arguments(schema, body["args"])
    except (ValueError, TypeError, RecursionError):
        return 400, {"error": "invalid Remote arguments"}
    def pre_dispatch(_manifest, route, spec):
        # user:“复用原宿主权威”+(最后派发前复核实际声明、路由、操作、启动代和既有令牌；未引入新授权体系)。
        try:
            current = host.get(plugin)
            if (current is None or current.raw != declaration or getattr(host, "backend_manager", None) is not manager
                    or (manager is not None and manager.generation.get(plugin) != generation)
                    or read_remote_methods(current).get((namespace, method)) != descriptor):
                return 409, {"error": "Remote binding changed"}
            current_routes = read_http_routes(current)
            if route not in current_routes or spec not in read_operations(current):
                return 409, {"error": "Remote binding changed"}
            return authenticate_remote(host, plugin, headers)
        except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
            return 409, {"error": "Remote binding changed"}
    # user:“复用原宿主权威”+(原路由再次检查可用性、令牌、操作归属和审批；不直连catalog.execute，不回退到未声明方法)。
    release = None
    if encoding == "ndjson":
        from .remote_stream import reserve, binding_check, RemoteStreamResponse
        release = reserve(host, plugin)
        if release is None:
            return 429, {"error": "Remote stream capacity exceeded"}
    try:
        if encoding == "ndjson":
            valid = binding_check(host, catalog, plugin, manifest, path)
        status, result = await dispatch_http_request(host=host, catalog=catalog, plugin=plugin, method="POST", path=path,
            body=body["args"], headers=headers, remote=remote, create_token=False, pre_dispatch=pre_dispatch)
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
            response = RemoteStreamResponse(source, valid, release)
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
