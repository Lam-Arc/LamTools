"""user:“继续，把 2 阶段都做完”+(会话执行目录与原项目分开，固定插件启动代，复用原会话持久化和条件写入)。"""
from dataclasses import dataclass


def directory_exists(project, path):
    """Host path validation only; this helper does not grant file access."""
    # user:“继续”+(主代理与插件共用目录校验；检查已观察到的链接，不创建缺失目录)。
    from pathlib import Path
    import stat
    from .filesystem_access import _is_link
    try:
        root, target = Path(project), Path(path)
        if not root.is_absolute() or root.resolve() != root or ".." in target.parts:
            raise ValueError
        relative = target.relative_to(root)
        cursor = root
        for part in ("", *relative.parts):
            cursor = cursor / part
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                return False
            if _is_link(info):
                raise ValueError
        return stat.S_ISDIR(info.st_mode)
    except (ValueError, TypeError, OSError, RuntimeError):
        raise WorkingDirectoryError("working-directory/invalid-path", "Execution directory violates local path rules") from None


class WorkingDirectoryError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


@dataclass(frozen=True)
class WorkingDirectoryState:
    session_id: str
    project_root: str
    path: str
    revision: int
    exists: bool


class PluginWorkingDirectoryAPI:
    def __init__(self, host, scope):
        self._host, self._scope = host, scope

    async def get(self, session_id):
        return await self._call("get", session_id)

    async def set(self, session_id, path, *, expected_revision):
        return await self._call("set", session_id, path=path, expected_revision=expected_revision)

    async def ensure(self, session_id, *, expected_revision):
        return await self._call("ensure", session_id, expected_revision=expected_revision)

    async def _call(self, method, session_id, **kwargs):
        self._scope.acquire()
        try:
            return await self._host.call(self._scope, method, session_id, **kwargs)
        finally:
            self._scope.release()
