"""user:“给我把 2 阶段做完，前端除外”+(复用已有Web传输/工具限制，提供有限引用和Unicode内容裁剪近似接口)。"""
import asyncio
import copy
import json
import os
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from lamtools_core.tool import ToolCall
from .filesystem_access import PluginFilesystemAPI


def _bounded(value, maximum=8 * 1024 * 1024):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")) > maximum:
        raise ValueError("Payload exceeds bounded JSON limit")
    return copy.deepcopy(value)


class PluginResultPrunerAPI:
    def __init__(self, scope):
        self._scope = scope

    def _blocks(self, blocks):
        self._scope.check_open()
        if type(blocks) is not list or len(blocks) > 10000 or any(type(block) is not dict for block in blocks):
            raise ValueError("Use a bounded list of content blocks")
        result = _bounded(blocks)
        for block in result:
            if block.get("type") == "text" and type(block.get("text")) is not str:
                raise ValueError("Text blocks require text strings")
        return result

    def measure_content(self, blocks):
        return sum(len(block["text"]) for block in self._blocks(blocks) if block.get("type") == "text")

    def prune_content(self, blocks, *, threshold_chars=30000, head_chars=10000, tail_chars=5000):
        result = self._blocks(blocks)
        if any(type(v) is not int or not 0 <= v <= 8 * 1024 * 1024 for v in (threshold_chars, head_chars, tail_chars)) or threshold_chars <= head_chars + tail_chars:
            raise ValueError("threshold must exceed nonnegative head+tail budgets")
        total = sum(len(block["text"]) for block in result if block.get("type") == "text")
        if total <= threshold_chars:
            return None
        offset, marked = 0, False
        for block in result:
            if block.get("type") != "text":
                continue
            text = block["text"]
            start, end = offset, offset + len(text)
            prefix = text[:max(0, min(len(text), head_chars - start))]
            suffix_start = max(0, total - tail_chars - start)
            suffix = text[suffix_start:] if suffix_start < len(text) else ""
            removed = max(0, min(end, total - tail_chars) - max(start, head_chars))
            marker = ""
            if removed and not marked:
                marker = f"\n[Sunday omitted {total - head_chars - tail_chars} text characters]\n"
                marked = True
            block["text"] = prefix + marker + suffix
            offset = end
        return result


class PluginFileReferencesAPI:
    def __init__(self, root, scope):
        self._root, self._scope = Path(root), scope

    def resolve(self, path):
        self._scope.check_open()
        fs = PluginFilesystemAPI(self._root, self._scope)
        candidate = fs.resolve(path)
        if not candidate.exists():
            from lamtools_core.app.file_references import resolve_file_reference
            candidate = fs.resolve(resolve_file_reference(str(candidate), self._root))
        return {"path": str(candidate), "kind": "directory" if candidate.is_dir() else "file"}

    async def list(self, query="", *, limit=100):
        self._scope.acquire()
        try:
            if type(query) is not str or len(query) > 512 or "\x00" in query or type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError("Use a query up to 512 characters and limit 1–1000")
            root = PluginFilesystemAPI(self._root, self._scope).resolve(".")
            def scan():
                queue, matches, seen, truncated = deque([(root, 0)]), [], 0, False
                while queue and seen < 5000:
                    directory, depth = queue.popleft()
                    try:
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                seen += 1
                                if seen > 5000:
                                    truncated = True
                                    break
                                path = Path(entry.path)
                                if entry.is_symlink() or path.is_junction():
                                    continue
                                is_dir = entry.is_dir(follow_symlinks=False)
                                relative = path.relative_to(root).as_posix()
                                if query.casefold() in relative.casefold():
                                    matches.append({"path": relative, "kind": "directory" if is_dir else "file"})
                                if is_dir and entry.name not in {".git", "node_modules", ".venv", "__pycache__"}:
                                    if depth < 64:
                                        queue.append((path, depth + 1))
                                    else:
                                        truncated = True
                    except (FileNotFoundError, NotADirectoryError, PermissionError):
                        truncated = True
                matches.sort(key=lambda row: row["path"])
                return {"items": matches[:limit], "truncated": truncated or bool(queue) or len(matches) > limit,
                        "scanned": min(seen, 5000)}
            result = await asyncio.to_thread(scan)
            self._scope.check_open()
            return result
        finally:
            self._scope.release()


class PluginWebAPI:
    def __init__(self, context, scope):
        self._root, self._scope = str(context.work_root), scope

    async def _call(self, kind, arguments):
        self._scope.acquire()
        try:
            from lamtools_core.tool.web_tools import make_web_fetch_handler, make_web_search_handler
            handler = make_web_fetch_handler(self._root) if kind == "fetch" else make_web_search_handler(self._root)
            async with asyncio.timeout(90):
                result = await handler(ToolCall(id="plugin-web", name="web_" + kind, arguments=arguments))
            return _bounded(result.to_dict())
        finally:
            self._scope.release()

    async def fetch(self, url, *, expect=None):
        if type(url) is not str or len(url) > 8192:
            raise ValueError("Use a bounded HTTP(S) URL")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTP(S) URL without inline credentials")
        if expect is not None and (type(expect) is not str or len(expect) > 1000):
            raise ValueError("expect must be bounded text")
        return await self._call("fetch", {"url": url, "expect": expect})

    async def search(self, query):
        if type(query) is not str or not query.strip() or len(query) > 4096:
            raise ValueError("Use a nonempty search query, at most 4096 characters")
        return await self._call("search", {"query": query})


class PluginPlanModeAPI:
    # An epoch-local restrictive mode; this list cannot grant tools or bypass normal permissions.
    READ_TOOLS = frozenset({"read_file", "list_directory", "list_files", "search_files", "search_text", "glob", "grep",
                            "web_fetch", "web_search", "git_status", "git_diff"})

    def __init__(self, context, scope):
        self._context, self._scope, self._modes = context, scope, {}

    def get(self, session_id):
        from .session_data import identifier
        self._scope.check_open()
        return {"session_id": identifier(session_id), "active": session_id in self._modes, "persistent": False}

    def enter(self, session_id):
        self.get(session_id)
        if session_id not in self._modes:
            self._modes[session_id] = self._context.tools.restrict(allow=self.READ_TOOLS, session_id=session_id)
        return self.get(session_id)

    def exit(self, session_id):
        self.get(session_id)
        dispose = self._modes.pop(session_id, None)
        if dispose is not None:
            dispose()
        return self.get(session_id)
