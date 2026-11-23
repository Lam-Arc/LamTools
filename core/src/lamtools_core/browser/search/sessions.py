"""搜索会话：结果 ID 只在自己那次搜索里有效（PRD §8）。

user:“结果 ID 只在其所属搜索会话中有效，不应假定跨刷新或跨导航稳定”+
(所以会话存进程内存，带容量上限与过期时间；ID 形如 `s3-2`，找不到就明确报错，
不去猜「大概是第几条」)。
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field

DEFAULT_CAPACITY = 16
DEFAULT_TTL = 1800.0


class SessionError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class SearchSession:
    id: str
    query: str
    engine: str
    created: float
    tab: str = ""
    # 打开结果时复用同一个标签，避免每点一条就多一个标签。
    result_tab: str = ""
    results: dict[str, dict] = field(default_factory=dict)

    def url_of(self, result_id: str) -> str:
        entry = self.results.get(result_id)
        if entry is None:
            raise SessionError(
                f"结果 {result_id} 不在搜索会话 {self.id} 里（会话可能已过期，或这是另一次搜索的结果 ID）"
            )
        return str(entry.get("url") or "")

    def summary(self) -> dict:
        return {
            "session": self.id,
            "query": self.query,
            "engine": self.engine,
            "tab": self.tab,
            "results": len(self.results),
            "ageSeconds": int(max(0.0, time.monotonic() - self.created)),
        }


class SessionStore:
    def __init__(self, capacity: int = DEFAULT_CAPACITY, ttl: float = DEFAULT_TTL) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, SearchSession] = {}
        self._counter = itertools.count(1)
        self.capacity = capacity
        self.ttl = ttl

    def create(self, query: str, engine: str, tab: str = "") -> SearchSession:
        with self._lock:
            self._purge_locked()
            session_id = f"s{next(self._counter)}"
            session = SearchSession(id=session_id, query=query, engine=engine, created=time.monotonic(), tab=tab)
            self._sessions[session_id] = session
            while len(self._sessions) > self.capacity:
                oldest = min(self._sessions.values(), key=lambda item: item.created)
                self._sessions.pop(oldest.id, None)
            return session

    def assign(self, session: SearchSession, results: list[dict]) -> list[dict]:
        """给结果补上会话内 ID（`s3-1`…）。结果本身是新建 dict，不改调用方那份。"""
        assigned: list[dict] = []
        with self._lock:
            for index, entry in enumerate(results, start=1):
                item = dict(entry)
                item["id"] = f"{session.id}-{index}"
                session.results[item["id"]] = item
                assigned.append(item)
        return assigned

    def get(self, session_id: str) -> SearchSession:
        key = str(session_id or "").strip()
        with self._lock:
            self._purge_locked()
            session = self._sessions.get(key)
        if session is None:
            raise SessionError(f"搜索会话 {key or '(空)'} 不存在或已过期；重新 search 一次即可")
        return session

    def find(self, session_id: str) -> SearchSession | None:
        with self._lock:
            self._purge_locked()
            return self._sessions.get(str(session_id or "").strip())

    def set_result_tab(self, session: SearchSession, tab: str) -> None:
        with self._lock:
            session.result_tab = tab

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._counter = itertools.count(1)

    def _purge_locked(self) -> None:
        now = time.monotonic()
        expired = [key for key, session in self._sessions.items() if now - session.created > self.ttl]
        for key in expired:
            self._sessions.pop(key, None)


_STORE = SessionStore()


def store() -> SessionStore:
    return _STORE
