"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(编码文件写入原会话附件存储，不伪造暂存凭证)。"""
import asyncio
import base64
import binascii
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from .session_data import PluginAttachmentAPI, SessionDataError, identifier

MAX_ENCODED_UPLOAD_BYTES = 512 * 1024
MAX_CHUNK_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_CHUNK_BYTES = 256 * 1024
MAX_UPLOAD_CHUNKS = 4096


async def _next_chunk(iterator, scope, validate):
    task = asyncio.ensure_future(anext(iterator))
    revoked = asyncio.create_task(scope._revoked.wait())
    async def cleanup():
        for pending in (task, revoked):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, revoked, return_exceptions=True)
    try:
        while True:
            await asyncio.wait((task, revoked), timeout=0.2, return_when=asyncio.FIRST_COMPLETED)
            scope.check_open()
            if task.done():
                return task.result()
            # user:“继续”+(空闲分块读取也复核会话，撤回后取消读取并等待清理)。
            await validate()
    finally:
        await finish_on_cancel(cleanup(), name="file-upload-chunk-pull-cleanup")


class FileUploadError(ValueError, RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginFileUploadsAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._host = context.require_service("session_data")

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope or self._context.service("session_data") is not self._host
                or Path(self._context.work_root).resolve() != self._root):
            raise FileUploadError("file-upload/host-changed", "Attachment host binding changed")

    def _check_after_write(self):
        try:
            self._check()
        except (RuntimeError, ValueError, OSError):
            raise FileUploadError("file-upload/host-changed", "Attachment was saved but host binding changed", may_have_changed=True) from None

    async def save_encoded(self, session_id, *, filename, content_base64, mime_type=None):
        self._check()
        if type(content_base64) is not str or len(content_base64) > ((MAX_ENCODED_UPLOAD_BYTES + 2) // 3) * 4:
            raise FileUploadError("file-upload/invalid-content", "Use bounded canonical base64")
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error, UnicodeEncodeError):
            raise FileUploadError("file-upload/invalid-content", "Use bounded canonical base64") from None
        if len(raw) > MAX_ENCODED_UPLOAD_BYTES or base64.b64encode(raw).decode("ascii") != content_base64:
            raise FileUploadError("file-upload/invalid-content", "Use bounded canonical base64")
        return await self._save(session_id, filename=filename, raw=raw, mime_type=mime_type)

    async def save_chunks(self, session_id, *, filename, source, size, mime_type=None):
        self._check()
        identifier(session_id)
        if type(filename) is not str or not filename.strip() or len(filename) > 256 or "\x00" in filename:
            raise SessionDataError("session-data/invalid-filename", "Use a bounded filename")
        if mime_type is not None and (type(mime_type) is not str or len(mime_type) > 256):
            raise SessionDataError("session-data/invalid-mime", "Use a bounded MIME type")
        if type(size) is not int or not 0 <= size <= MAX_CHUNK_UPLOAD_BYTES:
            raise FileUploadError("file-upload/invalid-content", "Use a declared size up to 8 MiB")
        try:
            iterator = aiter(source)
        except TypeError:
            raise FileUploadError("file-upload/invalid-content", "Use a closeable async byte stream") from None
        if not callable(getattr(iterator, "aclose", None)):
            raise FileUploadError("file-upload/invalid-content", "Use a closeable async byte stream")
        self._scope.acquire()
        try:
            data = bytearray()
            try:
                await self._host._read(session_id, self._root)
                self._check()
                count = 0
                async def validate():
                    self._check()
                    await self._host._read(session_id, self._root)
                    self._check()
                while True:
                    try:
                        chunk = await _next_chunk(iterator, self._scope, validate)
                    except StopAsyncIteration:
                        break
                    # user:“继续”+(每个分块后复核原会话和启动代；未完整接收前不创建持久附件)。
                    self._check()
                    await self._host._read(session_id, self._root)
                    self._check()
                    count += 1
                    if (type(chunk) is not bytes or len(chunk) > MAX_UPLOAD_CHUNK_BYTES
                            or count > MAX_UPLOAD_CHUNKS or len(data) + len(chunk) > size):
                        raise FileUploadError("file-upload/invalid-content", "Invalid upload chunk or declared size")
                    data.extend(chunk)
                if len(data) != size:
                    raise FileUploadError("file-upload/invalid-content", "Upload ended before declared size")
            finally:
                async def close_source():
                    await iterator.aclose()
                await finish_on_cancel(close_source(), name="file-upload-source-close")
            self._check()
            return await self._save(session_id, filename=filename, raw=bytes(data), mime_type=mime_type)
        finally:
            self._scope.release()

    async def _save(self, session_id, *, filename, raw, mime_type):
        self._check()
        self._scope.acquire()
        try:
            picker = PluginAttachmentAPI(self._host, self._scope, self._root, "attachments")
            # user:“复用原宿主权威”+(写入后再次经原附件服务核对会话和项目，不能发布失效作用域的结果)。
            try:
                result = await picker.create(session_id, filename=filename, content=raw, mime_type=mime_type)
            except SessionDataError as error:
                if error.code in {"session-data/invalid-id", "session-data/invalid-filename",
                                  "session-data/invalid-content", "session-data/invalid-mime"}:
                    raise
                self._check_after_write()
                # user:“完成真实接口、参数/错误、作用域、取消/清理”+(原写入抛错时文件或索引可能已经保存，不能假定回滚)。
                raise FileUploadError("file-upload/write-uncertain", "Attachment write failed; inspect current state", may_have_changed=True) from None
            except Exception:
                self._check_after_write()
                raise FileUploadError("file-upload/write-uncertain", "Attachment write failed; inspect current state", may_have_changed=True) from None
            self._check_after_write()
            try:
                await picker.get(session_id, result["id"])
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._check_after_write()
                code = "file-upload/host-changed" if getattr(error, "code", "") in {"session-data/host-changed", "session-data/closed"} else "file-upload/session-unavailable"
                raise FileUploadError(code, "Attachment was saved but its session cannot be verified", may_have_changed=True) from None
            self._check_after_write()
            return result
        finally:
            self._scope.release()
