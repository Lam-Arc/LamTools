"""user:“继续，把 2 阶段都做完”+(目录使用原会话元数据/CAS；不重绑项目，不改写已分配进程的目录)。"""
from copy import deepcopy
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.plugin_system.filesystem_access import PluginFilesystemAPI, FilesystemError
from lamtools_core.plugin_system.working_directory import WorkingDirectoryState, WorkingDirectoryError, PluginWorkingDirectoryAPI, directory_exists
from lamtools_core.plugin_system.sessions import SessionError
from .persistence_host import RevisionConflictError


class PluginWorkingDirectoryService:
    def __init__(self, sessions):
        self._sessions = sessions
        self._store = getattr(sessions._context().host, "session_store", None)

    def for_scope(self, scope):
        scope.check_open()
        return PluginWorkingDirectoryAPI(self, scope)

    async def _read(self, session_id):
        context = self._sessions._context()
        if context.host.session_store is not self._store:
            raise WorkingDirectoryError("working-directory/host-changed", "Session store changed")
        read = getattr(self._store, "get_readonly_revision", None)
        if not callable(read):
            raise WorkingDirectoryError("working-directory/unavailable", "Host has no coherent session revision reader")
        result = await read(session_id)
        if result is None:
            raise WorkingDirectoryError("working-directory/not-found", "Session is unknown or unavailable")
        return result

    def _state(self, scope, record, revision):
        try:
            raw_root = record.metadata.get("work_root")
            if type(raw_root) is not str or not Path(raw_root).is_absolute():
                raise ValueError
            project = Path(raw_root)
            if project.resolve() != project:
                raise ValueError
            raw = record.metadata.get("execution_directory", str(project))
            if type(raw) is not str or not Path(raw).is_absolute():
                raise ValueError
            path = Path(raw)
            if ".." in path.parts or not path.is_relative_to(project):
                raise ValueError
        except (ValueError, TypeError, OSError, RuntimeError):
            raise WorkingDirectoryError("working-directory/invalid-state", "Session project or execution directory is invalid") from None
        exists = directory_exists(project, path)
        return WorkingDirectoryState(record.id, str(project), str(path), revision, exists)

    async def runtime_path(self, session_id, project_root):
        # user:“继续”+(每次模型请求读取持久目录；原目录消失时按修订恢复原项目，不静默重绑配置)。
        for attempt in range(3):
            record, revision = await self._read(session_id)
            state = self._state(None, record, revision)
            if Path(state.project_root) != Path(project_root).resolve():
                raise WorkingDirectoryError("working-directory/project-mismatch", "Runtime project does not match session project")
            if state.exists:
                return state.path
            if not directory_exists(state.project_root, state.project_root):
                raise WorkingDirectoryError("working-directory/missing", "Current directory and original project are unavailable")
            try:
                saved = await finish_on_cancel(self._store.patch(session_id,
                    metadata={**deepcopy(record.metadata), "execution_directory": state.project_root}, expected_revision=revision), name="runtime-working-directory-restore")
            except RevisionConflictError:
                continue
            if saved is None:
                raise WorkingDirectoryError("working-directory/not-found", "Session became unavailable")
            return state.project_root
        raise WorkingDirectoryError("working-directory/conflict", "Session kept changing during directory recovery")

    async def call(self, scope, method, session_id, **kwargs):
        if type(session_id) is not str or not session_id.strip() or len(session_id) > 256 or "\x00" in session_id:
            raise WorkingDirectoryError("working-directory/invalid-id", "Use a bounded session identifier")
        mutation = method != "get"
        try:
            record, revision = await self._read(session_id)
            scope.check_open()
            current = self._state(scope, record, revision)
            if not mutation:
                return current
            expected = kwargs["expected_revision"]
            if type(expected) is not int or not 0 <= expected <= 2**63 - 1:
                raise WorkingDirectoryError("working-directory/invalid-revision", "Read the current session revision before changing directory")
            if revision != expected:
                raise WorkingDirectoryError("working-directory/conflict", "Session changed; read again before changing directory")
            if method == "ensure" and current.exists:
                return current
            target = current.project_root if method == "ensure" else kwargs["path"]
            try:
                path = PluginFilesystemAPI(current.project_root, scope).resolve(target)
                if not path.is_dir():
                    raise ValueError
            except (FilesystemError, ValueError, TypeError, OSError):
                raise WorkingDirectoryError("working-directory/invalid-path", "Choose an existing directory inside the original project") from None
            if str(path) == current.path:
                return current
            metadata = {**deepcopy(record.metadata), "execution_directory": str(path)}
            scope.check_open()
            saved = await finish_on_cancel(self._store.patch(session_id, metadata=metadata, expected_revision=expected), name="plugin-working-directory-save")
            if saved is None:
                raise WorkingDirectoryError("working-directory/not-found", "Session became unavailable")
            return WorkingDirectoryState(session_id, current.project_root, str(path), revision + 1, path.is_dir())
        except RevisionConflictError:
            raise WorkingDirectoryError("working-directory/conflict", "Session changed during the update") from None
        except SessionError as error:
            suffix = "closed" if error.code == "session/closed" else "host-changed"
            raise WorkingDirectoryError("working-directory/" + suffix, "Session host is unavailable") from None
        except WorkingDirectoryError:
            raise
        except Exception:
            raise WorkingDirectoryError("working-directory/operation-failed", "Working directory operation failed; read current state before retrying", may_have_changed=mutation) from None


def install_runtime_directory_source(toolbox, context):
    # user:“继续”+(主代理读取同一宿主目录服务；尚未安装桌面会话服务的CLI保持原目录行为)。
    async def source(session_id):
        # user:“继续”+(子代理沿用原独立执行权威，不要求存在主会话目录记录)。
        if ":sub:" in str(session_id):
            return None
        service = context.service("working_directory")
        if service is None:
            return None
        return await service.runtime_path(session_id, toolbox.work_root)
    toolbox.execution_directory_source = source
