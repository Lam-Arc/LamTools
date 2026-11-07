"""user:“第二阶段结束后 就继续开展第三阶段”+(一元Remote结果按明确选择传原始字节附件，结果有界且失败不发送半份响应)。"""
import json
import math
import secrets
from dataclasses import dataclass, fields, is_dataclass

from fastapi.responses import JSONResponse, Response

MAX_BINARY_BYTES = 8 * 1024 * 1024
MAX_RESULT_JSON_BYTES = 1024 * 1024
MAX_ATTACHMENTS = 64
MAX_RESULT_DEPTH = 32
MAX_RESULT_NODES = 10000


@dataclass(frozen=True)
class RemotePayload:
    value: object
    allow_binary: bool


def encode_remote_response(status, payload, *, limits):
    if not isinstance(payload, RemotePayload):
        return JSONResponse(payload, status_code=status)
    binary_limit, json_limit, attachment_limit, depth_limit, node_limit = limits
    attachments, ancestors = [], set()
    binary_bytes, text_bytes, nodes = 0, 0, 0

    def charge(value):
        nonlocal text_bytes
        if len(value) > json_limit:
            raise ValueError("result text exceeds limit")
        text_bytes += len(value.encode("utf8"))
        if text_bytes > json_limit:
            raise ValueError("result text exceeds limit")

    def project(value, path=()):
        nonlocal binary_bytes, nodes
        nodes += 1
        if nodes > node_limit or len(path) > depth_limit:
            raise ValueError("result structure exceeds limit")
        if type(value) is bytes:
            if not payload.allow_binary or status != 200:
                raise ValueError("binary result requires explicit successful multipart method")
            binary_bytes += len(value)
            if binary_bytes > binary_limit or len(attachments) >= attachment_limit:
                raise ValueError("binary attachments exceed limit")
            attachments.append((list(path), value))
            return None
        if type(value) is str:
            charge(value)
            return value
        if value is None or type(value) is bool:
            return value
        if type(value) in {int, float}:
            if type(value) is float and not math.isfinite(value):
                raise ValueError("non-finite result")
            charge(str(value))
            return value
        record = is_dataclass(value) and not isinstance(value, type)
        if (type(value) not in {dict, list, tuple} and not record) or id(value) in ancestors:
            raise ValueError("result must be acyclic finite JSON and declared bytes")
        ancestors.add(id(value))
        try:
            if record:
                # user:“第二阶段结束后 就继续开展第三阶段”+(原会话SDK记录按字段进入同一限额/循环检测，不能先asdict无界深拷贝或冒充DSH字段)。
                result = {}
                for field in fields(value):
                    charge(field.name)
                    result[field.name] = project(getattr(value, field.name), (*path, field.name))
                return result
            if type(value) is dict:
                result = {}
                for key, item in value.items():
                    if type(key) is not str:
                        raise ValueError("result keys must be strings")
                    charge(key)
                    result[key] = project(item, (*path, key))
                return result
            return [project(item, (*path, index)) for index, item in enumerate(value)]
        finally:
            ancestors.remove(id(value))

    try:
        result = project(payload.value)
        if attachments:
            result["attachments"] = [{"path": path, "codec": "bytes", "part": f"bytes-{index}"}
                for index, (path, _) in enumerate(attachments)]
        metadata = bytearray()
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).iterencode(result):
            data = chunk.encode("utf8")
            if len(metadata) + len(data) > json_limit:
                raise ValueError("encoded metadata exceeds limit")
            metadata.extend(data)
        if not attachments:
            return Response(bytes(metadata), status_code=status, media_type="application/json")
        boundary = "sunday-remote-" + secrets.token_hex(16)
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n'.encode(), bytes(metadata), b"\r\n"]
        for index, (_, data) in enumerate(attachments):
            parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="bytes-{index}"; filename="blob"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(), data, b"\r\n"])
        parts.append(f"--{boundary}--\r\n".encode())
        return Response(b"".join(parts), status_code=status, media_type="multipart/form-data; boundary=" + boundary)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(在任何响应发送前完成投影和限额检查，错误只公开稳定代码，不带业务值或半份二进制)。
        return JSONResponse({"error": {"code": "gateway/invalid-result", "message": "Remote result is invalid or exceeds limits"}}, status_code=502)
