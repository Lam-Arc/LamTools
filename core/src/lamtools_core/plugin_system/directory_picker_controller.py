"""user:“第二阶段结束后 就继续开展第三阶段”+(目录控制器只包装真实项目内browse能力)。"""
import asyncio
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from .directory_picker import DirectoryPickerError


class DirectoryPickerControllerError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginDirectoryPickerController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._picker = context.directory_picker.capability()

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or Path(self._context.work_root).resolve() != self._root
                or self._context.directory_picker is not self._picker):
            raise DirectoryPickerControllerError('directory-picker/host-changed', 'Directory picker binding changed')

    def capability(self):
        self._check()
        return {'kind': 'browse'}

    def _check_after(self, mutation):
        try:
            self._check()
        except (RuntimeError, ValueError, OSError):
            raise DirectoryPickerControllerError('directory-picker/host-changed', 'Directory picker binding changed', may_have_changed=mutation) from None

    async def pick(self):
        self._check()
        raise DirectoryPickerControllerError('directory-picker/unavailable', 'Native chooser is unavailable in this backend')

    async def list(self, path=None, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('limit must be between 1 and 1000')
        return await self._call('list', path, limit=limit)

    async def create_directory(self, path, name):
        return await self._call('create_directory', path, name, mutation=True)

    async def _call(self, method, *args, mutation=False, **kwargs):
        self._scope.acquire()
        try:
            self._check()
            try:
                # user:“复用原宿主权威”+(原browse在线程执行，取消后等待真实扫描或目录创建结算)。
                result = await finish_on_cancel(asyncio.to_thread(getattr(self._picker, method), *args, **kwargs),
                                                name='directory-picker-' + method)
            except DirectoryPickerError as error:
                self._check_after(mutation)
                codes = {'directory-unreadable': 'directory-picker/unreadable', 'directory-exists': 'directory-picker/exists',
                         'directory-create-failed': 'directory-picker/create-failed'}
                raise DirectoryPickerControllerError(codes.get(error.code, 'directory-picker/failed'),
                    'Original directory picker rejected the request',
                    may_have_changed=mutation and error.code != 'directory-exists') from None
            except asyncio.CancelledError:
                raise
            except Exception:
                self._check_after(mutation)
                raise DirectoryPickerControllerError('directory-picker/failed', 'Original directory picker failed', may_have_changed=mutation) from None
            self._check_after(mutation)
            return result
        finally:
            self._scope.release()
