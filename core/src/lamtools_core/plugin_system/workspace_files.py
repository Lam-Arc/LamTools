"""user:“第二阶段结束后 就继续开展第三阶段”+(会话文件控制器只复用原目录/文件权威，不接受客户端授权根或激活Agent)。"""
from dataclasses import asdict
from pathlib import Path
import re

from .filesystem_access import FilesystemError, PluginFilesystemAPI

MAX_PAGE_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024


class WorkspaceFileError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginWorkspaceFilesAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._host = context.require_service("working_directory")
        self._project = Path(context.work_root).resolve()

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or Path(self._context.work_root).resolve() != self._project
                or self._context.service("working_directory") is not self._host):
            raise WorkspaceFileError("workspace-file/host-changed", "Original directory host changed")

    async def _filesystem(self, session_id, path):
        self._check()
        if type(path) is not str or not path or "\x00" in path:
            raise WorkspaceFileError("workspace-file/invalid-request", "Use a nonempty session-relative or root-contained path")
        state = await self._host.for_scope(self._scope).get(session_id)
        # user:“复用原宿主权威”+(原目录读取负责可见性，等待后核对同一宿主/启动代，目录和项目取原返回值而非请求字段)。
        self._check()
        if Path(state.project_root).resolve() != self._project:
            raise WorkspaceFileError("workspace-file/outside-workspace", "Session belongs to another project")
        if not state.exists:
            raise WorkspaceFileError("workspace-file/not-found", "Session directory is unavailable")
        return PluginFilesystemAPI(Path(state.path), self._scope, self._context.data_dir)

    async def _call(self, action, session_id, path, **options):
        self._scope.acquire()
        try:
            fs = await self._filesystem(session_id, path)
            result = getattr(self, "_" + action)(fs, path, **options)
            self._check()
            # user:“复用原宿主权威”+(文件读取后重新核对会话可见性和执行目录，旧作用域不发布结果)。
            current = await self._filesystem(session_id, path)
            self._check()
            if Path(current.root).resolve() != Path(fs.root).resolve():
                raise WorkspaceFileError("workspace-file/session-directory-changed", "Session execution directory changed during read")
            return result
        except FilesystemError as error:
            mapped = {"fs/not-found": "not-found", "fs/not-file": "not-regular-file", "fs/not-text": "not-text", "fs/too-large": "too-large"}
            raise WorkspaceFileError("workspace-file/" + mapped[error.code] if error.code in mapped else error.code,
                "Session file operation was rejected") from None
        finally:
            self._scope.release()

    @staticmethod
    def _stat(fs, path):
        info = fs.stat(path)
        if info.kind != "file":
            raise WorkspaceFileError("workspace-file/not-regular-file", "Choose a regular file")
        return {"absolute_path": str(fs.resolve(path)), "version": f"stat:{info.size}:{info.modified_ns}", "bytes": info.size}

    @staticmethod
    def _list(fs, path, *, limit):
        listing = fs.list_dir(path, limit=limit)
        return {"path": str(fs.resolve(path)), "entries": [asdict(row) for row in listing.entries], "truncated": listing.truncated}

    def _read_bytes(self, fs, path, *, offset, length, base_file):
        if base_file is not None:
            if type(base_file) is not str or not base_file or path.replace("\\", "/").startswith("/") or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", path):
                raise WorkspaceFileError("workspace-file/invalid-request", "Use a regular base file and relative target")
            base = Path(self._stat(fs, base_file)["absolute_path"])
            path = str(base.parent / path)
        result = self._stat(fs, path)
        if offset is None and length is None:
            data, start = fs.read_bytes(path, max_bytes=1024 * 1024), 0
        else:
            start = 0 if offset is None else offset
            data = fs.read_byte_range(path, offset=start, length=1024 * 1024 if length is None else length)
        return {**result, "offset": start, "data": data, "eof": start + len(data) >= result["bytes"]}

    def _read(self, fs, path, *, offset, limit):
        if type(offset) is not int or not 1 <= offset <= 2**31 - 1 or type(limit) is not int or not 1 <= limit <= 5000:
            raise WorkspaceFileError("workspace-file/invalid-request", "Use a positive line offset and 1–5000 lines")
        result = self._stat(fs, path)
        rows, fragments, line, used, current = [], [], 1, 0, 0
        source = fs.stream_text(path, max_bytes=MAX_SOURCE_BYTES, chunk_bytes=8192)
        try:
            for chunk in source:
                pieces = chunk.split("\n")
                for index, part in enumerate(pieces):
                    terminated = index < len(pieces) - 1
                    if line >= offset + limit:
                        if part or terminated:
                            return {**result, "offset": offset, "text": "\n".join(rows), "lines": len(rows), "eof": False}
                    elif line >= offset:
                        size = len(part.encode("utf8"))
                        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(只有真实片段或行终止符才占新行预算，文件末尾的空切片不是额外空行)。
                        if (part or terminated) and used + current + size + bool(rows) > MAX_PAGE_BYTES:
                            raise WorkspaceFileError("workspace-file/too-large", "Text page exceeds 1 MiB")
                        if part:
                            fragments.append(part)
                            current += size
                        if terminated:
                            used += current + bool(rows)
                            rows.append("".join(fragments))
                            fragments, current = [], 0
                    if terminated:
                        line += 1
            if fragments:
                rows.append("".join(fragments))
            return {**result, "offset": offset, "text": "\n".join(rows), "lines": len(rows), "eof": True}
        finally:
            source.close()

    async def stat(self, session_id, path):
        return await self._call("stat", session_id, path)

    async def list(self, session_id, path=".", *, limit=100):
        return await self._call("list", session_id, path, limit=limit)

    async def read(self, session_id, path, *, offset=1, limit=100):
        return await self._call("read", session_id, path, offset=offset, limit=limit)

    async def read_bytes(self, session_id, path, *, offset=None, length=None, base_file=None):
        return await self._call("read_bytes", session_id, path, offset=offset, length=length, base_file=base_file)

    async def changes(self, session_id, path, *, interval=0.5):
        from .workspace_file_changes import open_changes
        self._scope.acquire()
        stream = None
        try:
            fs = await self._filesystem(session_id, path)
            stream = await open_changes(self, fs, path, interval, session_id)
            self._check()
            return stream
        except BaseException:
            if stream is not None:
                await stream.aclose()
            raise
        finally:
            self._scope.release()
