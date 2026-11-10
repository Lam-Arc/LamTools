"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(文件引用复用原会话目录准入和有界扫描)。"""
from pathlib import Path

from .content_access import PluginFileReferencesAPI
from .workspace_files import PluginWorkspaceFilesAPI, WorkspaceFileError


class PluginSessionFileReferencesAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._files = PluginWorkspaceFilesAPI(context, scope)

    def _check(self):
        self._files._check()
        if self._context._registration_scope is not self._scope or Path(self._context.work_root).resolve() != self._root:
            raise WorkspaceFileError("workspace-file/host-changed", "Original session project changed")

    async def list(self, session_id, query="", *, limit=100):
        if type(query) is not str or len(query) > 512 or "\x00" in query or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Use a query up to 512 characters and limit 1–1000")
        self._scope.acquire()
        try:
            self._check()
            fs = await self._files._filesystem(session_id, ".")
            # user:“复用原宿主权威”+(仅用原会话返回的执行目录扫描，原后台扫描负责协作取消和实际回收)。
            result = await PluginFileReferencesAPI(fs.root, self._scope).list(query, limit=limit)
            self._check()
            # user:“复用原宿主权威”+(扫描线程退出后复核会话可见性与执行目录，丢弃旧目录结果)。
            current = await self._files._filesystem(session_id, ".")
            self._check()
            if Path(current.root).resolve() != Path(fs.root).resolve():
                raise WorkspaceFileError("workspace-file/session-directory-changed", "Session execution directory changed during scan")
            return result
        finally:
            self._scope.release()
