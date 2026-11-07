"""user:“每一个地方 sunday 都有等价或者近似接口”+(无界面启动值由原CLI注入，只读且随插件启动代撤回)。"""
from dataclasses import asdict, dataclass


class StartupAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class HeadlessStartupValues:
    task: str
    thread_id: str
    requested_session_id: str | None
    json_summary: bool
    permission_preset: str
    approval_policy: str
    work_root: str
    additional_writable_roots: tuple[str, ...] = ()


class PluginHeadlessStartupAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._value = context.service("headless_startup")

    def get(self):
        if self._scope is not None:
            self._scope.check_open()
        if self._context.service("headless_startup") is not self._value:
            raise StartupAccessError("startup/host-changed", "Headless invocation was replaced")
        if not isinstance(self._value, HeadlessStartupValues):
            raise StartupAccessError("startup/unavailable", "This host has no local CLI invocation")
        result = asdict(self._value)
        result["additional_writable_roots"] = list(result["additional_writable_roots"])
        return result
