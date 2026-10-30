"""user:“继续，把 2 阶段都做完”+(查询游标仅在宿主内存保存，绑定插件代和筛选条件，有限生命周期且不含隐藏 ID)。"""
import secrets
import time
from collections import OrderedDict

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

    async def query(self, owner, *, limit, cursor, title_contains):
        try:
            context = self._sessions._context()
        except SessionError as error:
            raise SessionQueryError("session-query/closed" if error.code == "session/closed" else "session-query/host-changed", "Session query host is unavailable") from None
        if context.host.session_store is not self._store:
            raise SessionQueryError("session-query/host-changed", "Host session store changed")
        if type(limit) is not int or not 1 <= limit <= 100 or type(title_contains) is not str or len(title_contains) > 200:
            raise SessionQueryError("session-query/invalid-query", "limit is 1–100; title filter is at most 200 characters")
        now = time.monotonic()
        self._cursors = OrderedDict((key, row) for key, row in self._cursors.items() if row[0] > now)
        after = ""
        if cursor is not None:
            if type(cursor) is not str or len(cursor) > 128:
                raise SessionQueryError("session-query/invalid-cursor", "Cursor is invalid or expired")
            row = self._cursors.get(cursor)
            if row is None or row[1] != owner or row[2] != title_contains:
                raise SessionQueryError("session-query/invalid-cursor", "Cursor is invalid, expired or belongs to another query")
            after = row[3]
        scan = getattr(self._store, "scan_readonly", None)
        if not callable(scan):
            raise SessionQueryError("session-query/unavailable", "Host provides no bounded read-only session scan")
        try:
            rows, more = await scan(after_id=after, scan_limit=1000)
        except Exception:
            raise SessionQueryError("session-query/read-failed", "Session query failed") from None
        items = []
        for index, (identifier, record) in enumerate(rows):
            after = identifier
            if record is not None and title_contains.casefold() in record.title.casefold():
                items.append(SessionSummary(record.id, record.title[:1024], record.status, len(record.title) > 1024))
            if len(items) == limit:
                more = more or index + 1 < len(rows)
                break
        next_cursor = None
        if more:
            while len(self._cursors) >= 128:
                self._cursors.popitem(last=False)
            next_cursor = secrets.token_urlsafe(24)
            self._cursors[next_cursor] = (now + 120, owner, title_contains, after)
        return SessionQueryPage(tuple(items), next_cursor, more)
