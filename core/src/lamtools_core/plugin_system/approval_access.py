"""user:“继续，把 2 阶段都做完”+(审批有明确的一次性结果、受管回答者和持久审计，缺失回答者不能放行)。"""
from dataclasses import dataclass
import inspect

from .services import ServiceKey

ANSWERER = ServiceKey("plugin.approval.answerer")
OUTCOMES = frozenset({"allowed-once", "rejected", "cancelled", "unavailable"})


class ApprovalAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    plugin: str
    session_id: str
    turn_id: str
    tool_name: str
    call_id: str
    reason: str


@dataclass(frozen=True)
class ApprovalResult:
    request_id: str
    outcome: str
    asked_seq: int
    decided_seq: int

    @property
    def allowed(self):
        return self.outcome == "allowed-once"


class _Answerer:
    def __init__(self, scope, callback):
        self.scope, self.callback = scope, callback

    async def decide(self, request):
        self.scope.acquire()
        try:
            try:
                result = self.callback(request)
                if inspect.isawaitable(result):
                    result = await result
                return result if type(result) is str and result in OUTCOMES else "unavailable"
            except Exception:
                return "unavailable"
        finally:
            self.scope.release()


class PluginApprovalAPI:
    def __init__(self, host, scope):
        self._host, self._scope = host, scope

    def answer(self, callback):
        if not callable(callback):
            raise TypeError("answerer must be callable")
        return self._scope.register(ANSWERER, _Answerer(self._scope, callback))

    async def request(self, session_id, *, tool_name, call_id, reason="", timeout=15):
        self._scope.acquire()
        try:
            return await self._host.request(self._scope, session_id, tool_name=tool_name, call_id=call_id, reason=reason, timeout=timeout)
        finally:
            self._scope.release()
