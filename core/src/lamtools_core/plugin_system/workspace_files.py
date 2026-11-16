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
        from .session_controller import _cancel_owned_read
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(监听创建及消费期间重复取消也等待原会话准入清理)。
        return await _cancel_owned_read(self._filesystem_owned(session_id, path), name="workspace-file-session-admission")

    async def _filesystem_owned(self, session_id, path):
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
        from .session_controller import _cancel_owned_read
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(重复取消等待原会话准入和作用域清理)。
        return await _cancel_owned_read(self._call_owned(action, session_id, path, **options),
                                        name="workspace-file-" + action)

    async def _call_owned(self, action, session_id, path, **options):
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
    def _list(fs, path, *, limit, ordered, relative_path, portable_entries):
        listing = fs._list_dir_ordered(path, limit=limit) if ordered else fs.list_dir(path, limit=limit)
        resolved = fs.resolve(path)
        # user:“逐项核对固定上游源码及手册”+(显式选择时目录路径相对原会话根并使用正斜杠)。
        if relative_path:
            relative = resolved.relative_to(fs.root)
            listed_path = relative.as_posix() if relative.parts else ""
        else:
            listed_path = str(resolved)
        if portable_entries:
            # user:“逐项核对固定上游源码及手册”+(目录条目投影为name/type及普通文件大小，不跟随链接)。
            entries = []
            for row in listing.entries:
                kind = row.kind if row.kind in {"file", "directory"} else "other"
                item = {"name": row.name, "type": kind}
                if kind == "file":
                    item["size"] = row.size
                entries.append(item)
        else:
            entries = [asdict(row) for row in listing.entries]
        return {"path": listed_path, "entries": entries, "truncated": listing.truncated}

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
        # user:“逐项核对固定上游源码及手册”+(复用原有界UTF-8流与路径检查，NUL只检查实际返回的页)。
        # user:“逐项核对固定上游源码及手册”+(大文件可读取预算内的前部页，深页仍受实际扫描上限约束)。
        source = fs._stream_text(path, max_bytes=MAX_SOURCE_BYTES, chunk_bytes=8192,
                                 reject_nul=False, limit_source_size=False)
        try:
            for chunk in source:
                pieces = chunk.split("\n")
                for index, part in enumerate(pieces):
                    terminated = index < len(pieces) - 1
                    if line >= offset + limit:
                        if part or terminated:
                            return {**result, "offset": offset, "text": "\n".join(rows), "lines": len(rows), "eof": False}
                    elif line >= offset:
                        if "\x00" in part:
                            raise WorkspaceFileError("workspace-file/not-text", "Selected page contains NUL bytes")
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

    async def list(self, session_id, path=".", *, limit=100, ordered=False, relative_path=False, portable_entries=False):
        # user:“逐项核对固定上游源码及手册”+(有界稳定目录排序须由调用方明确选择)。
        if type(ordered) is not bool:
            raise WorkspaceFileError("workspace-file/invalid-request", "ordered must be a boolean")
        if type(relative_path) is not bool:
            raise WorkspaceFileError("workspace-file/invalid-request", "relative_path must be a boolean")
        if type(portable_entries) is not bool:
            raise WorkspaceFileError("workspace-file/invalid-request", "portable_entries must be a boolean")
        return await self._call("list", session_id, path, limit=limit, ordered=ordered,
                                relative_path=relative_path, portable_entries=portable_entries)

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
