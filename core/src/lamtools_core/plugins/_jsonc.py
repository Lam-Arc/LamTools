"""共享 JSONC 解析工具（plugins 包内复用，不引入 llm 包依赖）。

从 plugins/operations.py 的本地实现提升而来：同一套剥注释逻辑同时
服务注册表（plugins.jsonc）与插件配置（{data_dir}/plugins/<name>.jsonc）。
"""
from __future__ import annotations

import json
from typing import Any


def strip_jsonc_comments(text: str) -> str:
    """Strip JSONC comments without touching ``//`` inside string literals.

    A plain regex would also remove the ``//`` of a URL inside a quoted
    value, corrupting valid configs (audit 11). This scans line by line
    and only treats ``//`` / ``/* */`` outside strings as comments.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before ``}`` / ``]`` (JSONC allows them)."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            # Look ahead past whitespace for a closing brace/bracket.
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_jsonc_text(path: Any) -> dict[str, Any]:
    """Read a JSONC file (``utf-8-sig``) and parse it to a dict.

    Raises ValueError / json.JSONDecodeError on malformed content; the
    caller decides how to surface the error (discover skips, operations
    report status).
    """
    text = str(path)
    from pathlib import Path

    data = Path(text).read_text(encoding="utf-8-sig")
    parsed = json.loads(strip_trailing_commas(strip_jsonc_comments(data)))
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object: {text}")
    return parsed
