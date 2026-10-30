"""user:“继续，把 2 阶段都做完”+(会话目录以有限扫描和不透明游标公开，不暴露完整状态或隐藏会话标识)。"""
from dataclasses import dataclass


class SessionQueryError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    title: str
    status: str
    title_truncated: bool = False


@dataclass(frozen=True)
class SessionQueryPage:
    items: tuple[SessionSummary, ...]
    next_cursor: str | None
    has_more: bool


class PluginSessionQueryAPI:
    def __init__(self, host, scope):
        self._host, self._scope = host, scope

    async def query(self, *, limit=50, cursor=None, title_contains=""):
        self._scope.acquire()
        try:
            return await self._host.query((self._scope.owner, self._scope.epoch), limit=limit, cursor=cursor, title_contains=title_contains)
        finally:
            self._scope.release()
