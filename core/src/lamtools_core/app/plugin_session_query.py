"""user:“继续，把 2 阶段都做完”+(查询游标仅在宿主内存保存，绑定插件代和筛选条件，有限生命周期且不含隐藏 ID)。"""
import secrets
import time
from collections import OrderedDict
from pathlib import Path

from lamtools_core.plugin_system.session_query import SessionQueryError, SessionSummary, SessionQueryPage, PluginSessionQueryAPI
from lamtools_core.plugin_system.sessions import SessionError


class PluginSessionQueryService:
    def __init__(self, sessions):
        self._sessions = sessions
        self._store = getattr(sessions._context().host, "session_store", None)
        self._cursors = OrderedDict()

    def for_scope(self, scope):
        scope.check_open()
        return PluginSessionQueryAPI(self, scope)

    def _context(self):
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(查询前后共用同一原宿主检查，扫描等待期间关闭或替换不能发布旧结果)。
        try:
            context = self._sessions._context()
        except SessionError as error:
            raise SessionQueryError("session-query/closed" if error.code == "session/closed" else "session-query/host-changed", "Session query host is unavailable") from None
        if context.host.session_store is not self._store:
            raise SessionQueryError("session-query/host-changed", "Host session store changed")
        return context

    async def query(self, owner, *, limit, cursor, title_contains, project_root=None):
        self._context()
        if type(limit) is not int or not 1 <= limit <= 100 or type(title_contains) is not str or len(title_contains) > 200:
            raise SessionQueryError("session-query/invalid-query", "limit is 1–100; title filter is at most 200 characters")
        now = time.monotonic()
        self._cursors = OrderedDict((key, row) for key, row in self._cursors.items() if row[0] > now)
        after = ""
        if cursor is not None:
            if type(cursor) is not str or len(cursor) > 128:
                raise SessionQueryError("session-query/invalid-cursor", "Cursor is invalid or expired")
            row = self._cursors.get(cursor)
            if row is None or row[1] != owner or row[2] != title_contains or row[4] != project_root:
                raise SessionQueryError("session-query/invalid-cursor", "Cursor is invalid, expired or belongs to another query")
            after = row[3]
        scan = getattr(self._store, "scan_readonly", None)
        read_current = getattr(self._store, "get_readonly", None)
        if not callable(scan) or (project_root is not None and not callable(read_current)):
            raise SessionQueryError("session-query/unavailable", "Host provides no bounded read-only session scan")
        try:
            rows, more = await scan(after_id=after, scan_limit=1000)
        except Exception:
            raise SessionQueryError("session-query/read-failed", "Session query failed") from None
        self._context()
        items = []
        for index, (identifier, record) in enumerate(rows):
            after = identifier
            if record is not None and project_root is not None:
                # user:“复用原宿主权威”+(扫描后重新读取原可见会话，不能发布等待期间已隐藏或移动的记录)。
                try:
                    record = await read_current(identifier)
                except Exception:
                    raise SessionQueryError("session-query/read-failed", "Session query failed") from None
                self._context()
            in_project = project_root is None
            if record is not None and project_root is not None:
                # user:“复用原宿主权威”+(只接受原会话记录中归属当前项目的路径，不让请求方指定授权根)。
                root = record.metadata.get("work_root")
                try:
                    in_project = type(root) is str and bool(root) and "\x00" not in root and Path(root).is_absolute() and str(Path(root).resolve()) == project_root
                except (OSError, ValueError, RuntimeError):
                    in_project = False
            if record is not None and in_project and title_contains.casefold() in record.title.casefold():
                items.append(SessionSummary(record.id, record.title[:1024], record.status, len(record.title) > 1024))
            if len(items) == limit:
                more = more or index + 1 < len(rows)
                break
        next_cursor = None
        if more:
            while len(self._cursors) >= 128:
                self._cursors.popitem(last=False)
            next_cursor = secrets.token_urlsafe(24)
            self._cursors[next_cursor] = (now + 120, owner, title_contains, after, project_root)
        return SessionQueryPage(tuple(items), next_cursor, more)
