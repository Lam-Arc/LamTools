"""user:“给我把 2 阶段做完，前端除外”+(授权流复用原服务租约及凭据存储，只有提交回读成功才返回authorized)。"""
import asyncio
import inspect
import math
import re

from .services import ServiceKey

_UNCONDITIONAL = object()


class AuthorizationError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _key(value):
    if type(value) is not str or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", value):
        raise AuthorizationError("authorization/invalid-key", "Use a bounded flow key")
    return "authorization.flow." + value


async def _settle_cancelled(task):
    if not task.done():
        task.cancel()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()


class AuthorizationControl:
    def __init__(self, entry, method, prompt, notify, requester_scope):
        self.method, self._entry = method, entry
        self._prompt, self._notify = prompt, notify
        self._requester_scope = requester_scope
        self._active, self._committed = True, False

    def _check_active(self):
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(撤回单个授权流也立即关闭控制器，提供方处理取消后不得提交或继续交互；固定原注册作用域)。
        if not self._active or self._entry.withdrawn or not self._requester_scope.accepting:
            raise AuthorizationError("authorization/closed", "Authorization attempt is no longer active")
        self._entry.scope.check_open()

    def commit(self, value, *, expected_value=_UNCONDITIONAL):
        self._check_active()
        credentials = self._entry.context.credentials
        # user:“复用现有宿主权威”+(可选条件提交仍由原授权控制器持有提交/回读权威，账户旧回调不得覆盖新grant)。
        if expected_value is _UNCONDITIONAL:
            credentials.set(self._entry.credential, value)
        elif not credentials.compare_exchange(self._entry.credential, expected=expected_value, value=value):
            raise AuthorizationError("authorization/conflict", "Credential changed before authorization commit")
        observed = credentials.resolve(self._entry.credential)
        if observed is None or observed.value != value:
            raise AuthorizationError("authorization/commit-failed", "Credential commit could not be observed")
        self._committed = True

    async def prompt(self, request):
        self._check_active()
        if self._prompt is None:
            raise AuthorizationError("authorization/interaction-unavailable", "The initiating surface supplied no prompt callback")
        from .content_access import _bounded
        result = self._prompt(_bounded(request, 65536))
        return _bounded(await result if inspect.isawaitable(result) else result, 65536)

    async def notify(self, record):
        self._check_active()
        if self._notify is not None:
            from .content_access import _bounded
            result = self._notify(_bounded(record, 65536))
            if inspect.isawaitable(result):
                await result


class _Flow:
    def __init__(self, context, key, label, methods, credential, run):
        self.context, self.key, self.label = context, key, label
        self.methods, self.credential, self.run = tuple(methods), credential, run
        self.scope = context._active_registration_scope()
        self.attempt, self.withdrawn = None, False
        self.control = None

    def cancel_attempt(self, task=None):
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(先撤回原控制器再请求任务取消，提供方捕获取消不能继续提交或交互)。
        if task is not None and self.attempt is not task:
            return
        if self.control is not None:
            self.control._active = False
        if self.attempt is not None:
            self.attempt.cancel()

    def describe(self):
        return {"key": self.key, "label": self.label, "methods": list(self.methods), "busy": self.attempt is not None}

    async def authorize(self, method, prompt, notify, requester_scope):
        if self.withdrawn:
            raise AuthorizationError("authorization/unavailable", "Authorization flow was withdrawn")
        if method not in self.methods:
            raise AuthorizationError("authorization/invalid-method", "Flow does not support this method")
        if self.attempt is not None:
            raise AuthorizationError("authorization/busy", "An authorization attempt is already active")
        self.attempt = asyncio.current_task()
        control = AuthorizationControl(self, method, prompt, notify, requester_scope)
        self.control = control
        try:
            result = self.run(control)
            if not inspect.isawaitable(result):
                raise AuthorizationError("authorization/invalid-flow", "Flow callback must be asynchronous")
            await result
            if not control._committed:
                raise AuthorizationError("authorization/not-committed", "Flow completed without an observed credential commit")
            return {"key": self.key, "status": "authorized"}
        finally:
            control._active, self.attempt = False, None
            self.control = None


class PluginAuthorizationAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope

    def register_flow(self, key, *, label, methods, credential, run):
        name = _key(key)
        self._scope.check_open()
        if type(label) is not str or not label or len(label) > 200 or type(methods) is not list or not 1 <= len(methods) <= 16 or any(type(m) is not str or not m or len(m) > 64 for m in methods) or len(set(methods)) != len(methods) or not callable(run):
            raise AuthorizationError("authorization/invalid-flow", "Provide a bounded label, distinct nonempty methods and async callback")
        # Validation reads no secret values and ensures the provider owns a real credential view.
        self._context.credentials.describe(credential)
        entry = _Flow(self._context, key, label, methods, credential, run)
        registration = self._context.register_service(ServiceKey(name), entry)
        def dispose():
            entry.withdrawn = True
            registration()
            entry.cancel_attempt()
        self._scope.on_dispose(dispose)
        return dispose

    def list(self):
        self._scope.check_open()
        entries = dict(self._scope.registry.records)
        entries.update(self._scope.entries)
        return [record.value.describe() for key, record in sorted(entries.items())
                if key.startswith("authorization.flow.") and record.live and record.scope.accepting and isinstance(record.value, _Flow)]

    def cancel(self, key):
        self._scope.check_open()
        ref = self._context.bind_service(_key(key))
        entry = ref.get()
        # Only the owning provider can cancel an attempt independently of its initiating caller.
        if entry.scope is not self._scope:
            raise AuthorizationError("authorization/not-owner", "Only the flow owner may cancel a separately initiated attempt")
        entry.cancel_attempt()

    async def begin(self, key, *, method, prompt=None, notify=None, timeout=300):
        self._scope.acquire()
        task = watcher = None
        try:
            if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 300 or any(callback is not None and not callable(callback) for callback in (prompt, notify)):
                raise AuthorizationError("authorization/invalid-request", "Use callback interactions and timeout in (0, 300]")
            ref = self._context.bind_service(_key(key))
            entry = ref.get()
            if not isinstance(entry, _Flow):
                raise AuthorizationError("authorization/invalid-provider", "Flow service does not implement the authorization contract")
            async def withdrawn():
                # user:“审查当前代码，然后继续”+(发起方停用同样撤回请求，避免其租约等到交互期限)。
                while self._scope.accepting and entry.scope.accepting and not entry.withdrawn:
                    await asyncio.sleep(0.02)
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(控制器也固定发起方作用域，撤回发起方后处理取消不能再写凭据或调用交互)。
            task = asyncio.create_task(ref.call("authorize", method, prompt, notify, self._scope), name="plugin-authorization")
            watcher = asyncio.create_task(withdrawn(), name="plugin-authorization-withdrawal")
            try:
                async with asyncio.timeout(timeout):
                    done, _ = await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
                    if task in done:
                        return {"key": key, "status": "cancelled"} if task.cancelled() else task.result()
                    entry.cancel_attempt(task)
                    await _settle_cancelled(task)
                    return {"key": key, "status": "cancelled"}
            except TimeoutError:
                entry.cancel_attempt(task)
                await _settle_cancelled(task)
                raise AuthorizationError("authorization/timeout", "Authorization deadline expired; inspect credential state before retrying") from None
        finally:
            if task is not None:
                entry.cancel_attempt(task)
                await _settle_cancelled(task)
            if watcher is not None:
                await _settle_cancelled(watcher)
            self._scope.release()
