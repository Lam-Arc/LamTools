"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(批量凭据状态复用原所有者视图，不读取或输出凭据值)。"""
import re


class CredentialControllerError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code = code
        self.may_have_changed = may_have_changed
        super().__init__(message)


class PluginCredentialController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._store = context._secret_store

    def _check(self):
        self._scope.check_open()
        if self._context._registration_scope is not self._scope or self._context._secret_store is not self._store:
            raise CredentialControllerError("credentials/host-changed", "Credential store binding changed")
        if self._store is None:
            raise CredentialControllerError("credentials/unavailable", "Credential store is unavailable")

    def describe(self, refs):
        if type(refs) is not list or len(refs) > 64 or any(
                type(ref) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", ref) is None for ref in refs):
            raise ValueError("Use at most 64 credential identifiers")
        self._check()
        credentials = self._store.for_scope(self._scope)
        result = {}
        for ref, info in credentials.describe_many(refs).items():
            # user:“复用原宿主权威”+(逐字段投影现有元数据，绝不读取或输出机密值)。
            result[ref] = {"configured": info.configured, "source": info.source, "writable": info.writable}
        self._check()
        return result

    def _write(self, action, ref, value=None):
        self._check()
        credentials = self._store.for_scope(self._scope)
        credentials._key(ref)
        if action == "set":
            credentials._value(value)
        # user:“复用原宿主权威”+(只调用当前插件的原加密凭据写入，响应绝不包含密值)。
        try:
            if action == "set":
                credentials.set(ref, value)
            else:
                credentials.unset(ref)
        except Exception:
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(底层写入报错可能发生在提交后，避免泄露原错误与密值)。
            try:
                self._check()
            except RuntimeError:
                raise CredentialControllerError("credentials/host-changed", "Credential binding changed during write", may_have_changed=True) from None
            raise CredentialControllerError("credentials/write-uncertain", "Credential write failed; inspect current state", may_have_changed=True) from None
        try:
            self._check()
        except RuntimeError:
            # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(已提交后绑定变化不能声称回滚，明确告知可能已变化)。
            raise CredentialControllerError("credentials/host-changed", "Credential binding changed after write", may_have_changed=True) from None

    def set(self, ref, value):
        self._write("set", ref, value)

    def unset(self, ref):
        self._write("unset", ref)
