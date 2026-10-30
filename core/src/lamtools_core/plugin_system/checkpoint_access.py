"""user:“继续，把 2 阶段都做完”+(检查点门面共用原操作和会话可见性，只恢复对话，不引入第二套恢复权威)。"""
from lamtools_core.async_tasks import finish_on_cancel
from .durable_access import _json
from .sessions import SessionError


class CheckpointAccessError(RuntimeError):
    def __init__(self, code, message, *, details=None, may_have_changed=False):
        self.code, self.details, self.may_have_changed = code, details or {}, may_have_changed
        super().__init__(message)


def _id(value):
    if type(value) is not str or not value.strip() or len(value) > 256 or "\x00" in value:
        raise CheckpointAccessError("checkpoint/invalid-id", "Use a bounded nonempty identifier")
    return value


class PluginCheckpointAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._catalog = context.resolved_operation_catalog()
        self._sessions = context.service("sessions")

    async def _call(self, name, session_id, **fields):
        self._scope.acquire()
        mutation = name != "session.checkpoints.list"
        try:
            session_id = _id(session_id)
            if self._context.resolved_operation_catalog() is not self._catalog or self._context.service("sessions") is not self._sessions:
                raise CheckpointAccessError("checkpoint/host-changed", "Checkpoint host changed")
            if self._sessions is None or self._catalog is None or not self._catalog.has(name):
                raise CheckpointAccessError("checkpoint/unavailable", "Required native checkpoint operation is unavailable")
            host = self._sessions._context().host
            read = getattr(getattr(host, "session_store", None), "get_readonly", None)
            if not callable(read):
                raise CheckpointAccessError("checkpoint/unavailable", "Host has no read-only session visibility check")
            try:
                record = await read(session_id)
            except Exception:
                raise CheckpointAccessError("checkpoint/read-failed", "Session visibility read failed") from None
            if record is None:
                raise CheckpointAccessError("checkpoint/not-found", "Session is unknown or unavailable")
            registry = getattr(host, "runtime_task_registry", None)
            active = registry.active_run_id(session_id) if registry is not None else None
            if mutation and (record.status in {"running", "waiting", "paused"} or active):
                raise CheckpointAccessError("checkpoint/active-session", "Finish or cancel the active session before changing checkpoints")
            self._scope.check_open()
            work = self._catalog.execute(name, {"session_id": session_id, **fields},
                                         metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            try:
                result = await finish_on_cancel(work, name="plugin-checkpoint-operation") if mutation else await work
            except Exception:
                raise CheckpointAccessError("checkpoint/operation-failed", "Native checkpoint operation failed; inspect current state before retrying", may_have_changed=mutation) from None
            try:
                payload = _json(result.payload)
            except Exception:
                raise CheckpointAccessError("checkpoint/result-too-large", "Checkpoint result is not bounded JSON; inspect native state", may_have_changed=mutation) from None
            if result.status != "ok":
                raise CheckpointAccessError("checkpoint/rejected", "Native checkpoint operation rejected the request", details=payload, may_have_changed=mutation)
            return payload
        except SessionError as error:
            raise CheckpointAccessError("checkpoint/closed" if error.code == "session/closed" else "checkpoint/host-changed", "Session host is unavailable") from None
        finally:
            self._scope.release()

    async def list(self, session_id):
        return await self._call("session.checkpoints.list", session_id)

    async def create(self, session_id, *, label=""):
        if type(label) is not str or len(label) > 256 or "\x00" in label:
            raise CheckpointAccessError("checkpoint/invalid-label", "Label must be text of at most256 characters")
        return await self._call("session.checkpoints.create", session_id, label=label, reason="plugin-manual", actor_kind="tool")

    async def restore(self, session_id, checkpoint_id):
        return await self._call("session.checkpoints.restore", session_id, checkpoint_id=_id(checkpoint_id), scope="conversation")

    async def rollback(self, session_id, *, turn_id):
        return await self._call("session.rollback", session_id, turn_id=_id(turn_id))

    async def fork(self, session_id, *, checkpoint_id=None, turn_id=None, new_session_id=None, title=""):
        if (checkpoint_id is None) == (turn_id is None):
            raise CheckpointAccessError("checkpoint/invalid-boundary", "Choose exactly one checkpoint or turn boundary")
        if type(title) is not str or len(title) > 256 or "\x00" in title:
            raise CheckpointAccessError("checkpoint/invalid-title", "Title must be text of at most256 characters")
        fields = {"checkpoint_id": _id(checkpoint_id)} if checkpoint_id is not None else {"turn_id": _id(turn_id)}
        if new_session_id is not None:
            fields["new_session_id"] = _id(new_session_id)
        return await self._call("session.fork", session_id, **fields, title=title)
